# How Ninja's build scheduler actually works

**Ninja uses a critical-path-aware priority scheduler** that, since v1.12.0 (February 2024), prioritizes build edges by their depth in the dependency graph — edges on the longest chain run first. Before v1.12.0, scheduling was effectively arbitrary (sorted by pointer address). The scheduler operates on a flat, monolithic dependency graph with no concept of "targets," freely interleaving compilation of files from different libraries. Parallelism is bounded by three layers: the global `-j` cap, per-pool depth limits, and system load average. This report provides the implementation-level detail needed to build a discrete-event simulation that faithfully approximates Ninja's scheduling behavior.

## The core scheduling loop and data structures

Ninja's scheduling is split between two classes: **`Plan`** (decides what to run next) and **`Builder`** (manages execution). The central data structures in `Plan` are:

- **`want_`** (`std::map<Edge*, Want>`): Tracks every edge that needs building and its state — `kWantNothing` (dependency only), `kWantToStart` (needs building, not yet scheduled), or `kWantToFinish` (scheduled, awaiting completion).
- **`ready_`** (`EdgePriorityQueue`): A max-heap priority queue wrapping `std::priority_queue<Edge*, vector<Edge*>, EdgePriorityCompare>`. The comparator uses `<` on `critical_path_weight` (type `int64_t`), so edges with **higher weight are dequeued first**.

The `Builder::Build()` main loop repeats three phases. **Phase 1 — start work**: while `CommandRunner::CanRunMore()` returns a nonzero `size_t` count (indicating available job slots below the `-j` limit), pop the highest-priority edge from `ready_` via `Plan::FindWork()` and launch it as a subprocess. **Phase 2 — wait**: block until any running subprocess completes. **Phase 3 — finish**: call `Plan::EdgeFinished()`, which releases pool slots, marks output nodes as ready, and cascades — for each output node, iterate its downstream edges (`out_edges()`); if a downstream edge is in `want_` with state `kWantToStart` and all its inputs are now satisfied, call `ScheduleWork()` to push it into the `ready_` priority queue. This cascade is how completing one compilation unlocks the next link step.

The `CanRunMore()` method on `RealCommandRunner` checks two conditions: the count of running + finished-but-unprocessed subprocesses must be below `config_.parallelism` (set by `-j`, defaulting to **nproc + 2**), and if `-l` is set, the system load average must be below the threshold. It returns the number of additional commands that can start, not a boolean.

## Critical path computation: depth-based, not time-based

Before any edges execute, `Plan::PrepareQueue()` calls `ComputeCriticalPath()` followed by `ScheduleInitialEdges()`. The critical path algorithm works in three steps:

**Step 1 — Topological sort.** A DFS-based topological sort of all edges reachable from the requested targets produces a list where each edge appears after its parents (the edges producing its inputs).

**Step 2 — Weight assignment.** Each non-phony edge receives weight **1**. Phony edges receive weight **0**. Notably, this is a simplified heuristic — it does not use historical build times from `.ninja_log`. The decision to use uniform weights rather than recorded execution times was a deliberate compromise to avoid pathologies with ccache, distributed builds, and first-time builds where no log exists.

**Step 3 — Back-propagation.** Iterating edges in reverse topological order (from targets toward leaves), the algorithm propagates weights backward. For each edge's input nodes, it finds the producing edge and computes `candidate_weight = current_edge_weight + producer_own_weight`. The producer keeps the maximum of its existing weight and this candidate. This is classic longest-path computation — after one pass, each edge's `critical_path_weight` equals the **length of the longest chain of non-phony edges from that edge to any build target**.

The practical effect: if a code generator edge sits at the root of a deep dependency chain (generate → compile → link), it gets the highest weight and runs first, unblocking the entire chain. A leaf compilation with no downstream dependents gets weight 1. **This was introduced in PR #2177** (merged February 29, 2024, released in Ninja 1.12.0), replacing the pre-1.12 behavior where `ready_` was a `std::set<Edge*>` sorted by pointer value — effectively arbitrary scheduling.

## How pools throttle parallelism

Pools provide **per-resource concurrency limits** below the global `-j` cap. A pool declaration specifies a `depth` (maximum concurrent jobs):

```ninja
pool link_pool
  depth = 4
```

The `Pool` class (in `state.h`) maintains `current_use_` (running count) and a `delayed_` collection of edges waiting for capacity. The scheduling interaction works as follows: when `ScheduleWork()` is called for a newly-ready edge, it checks `pool->ShouldDelayEdge()` (returns true when `current_use_ >= depth_`). If the pool is full, the edge enters `pool->DelayEdge(edge)` rather than `ready_`. When any pooled edge finishes, `EdgeFinished()` decrements `current_use_` and calls `RetrieveReadyEdges(&ready_)`, which moves delayed edges into the priority queue up to available capacity. After PR #2177, the `delayed_` set maintains priority ordering via `EdgePriorityCompare`, so the highest-priority delayed edge is released first.

Three pools exist by default. The **default pool** has effectively infinite depth — edges in this pool are constrained only by `-j`. The **console pool** (predefined, `depth = 1`) gives direct access to stdin/stdout and buffers all other Ninja output while its task runs. **Custom pools** are user-defined. The critical rule: **`-j` is always a hard global cap**. With `-j 16` and a `link_pool` of `depth = 4`, at most 4 link edges run concurrently, but only if total running jobs across all pools hasn't hit 16. Conversely, `-j 2` with `pool depth = 4` effectively limits the pool to 2.

## Ninja's flat graph has no concept of "targets"

This is perhaps the most important insight for simulation: **Ninja operates on a flat dependency graph of edges and nodes with no notion of CMake targets**. It freely interleaves compilation of `.cpp` files from different libraries. A file from `libA` and a file from `libB` may compile simultaneously with no coordination. The only constraint is explicit dependency edges: a library's link step lists all its object files as inputs, so it cannot start until every object file finishes. But nothing prevents `libA`'s object files from compiling in parallel with `libB`'s, and nothing forces `libA` to fully complete before `libB` begins.

The critical path scheduler amplifies this: if `libC` depends on `libB` depends on `libA`, then `libA`'s compilations get the highest priority (deepest chain to final target), `libB`'s compilations get intermediate priority, and `libC`'s compilations get the lowest. The scheduler will preferentially start `libA` files, but once `-j` slots are available and `libA` files are all running, it starts `libB` and `libC` files in priority order. This naturally tends to **complete deep dependency chains first** without artificially sequentializing the build.

## How CMake structures the build.ninja file

CMake's Ninja generator produces a **single monolithic `build.ninja`** file (plus an included `rules.ninja`). The structure maps CMake concepts to Ninja primitives through several mechanisms:

**Compile edges** are one per source file, with per-target rules (e.g., `CXX_COMPILER__mylib`). Each compile edge has an **order-only dependency** (`||`) on a phony target named `cmake_object_order_depends_target_<name>`, which ensures generated headers are available before compilation starts but doesn't trigger rebuilds on its own.

**Link edges** list all object files as explicit inputs and use **implicit dependencies** (`|`) on library outputs. For example, `build myapp: CXX_EXECUTABLE_LINKER__myapp main.o | libmylib.a` ensures `libmylib.a` is fully built before `myapp` links. This is the mechanism that enforces inter-target ordering.

**Phony aliases** allow building by target name: `build mylib: phony libmylib.a`. The `default all` statement builds everything. CMake exposes Ninja pools through the `JOB_POOLS` global property and per-target `JOB_POOL_LINK` / `JOB_POOL_COMPILE` properties. The regeneration step (`cmake --regenerate`) uses the `console` pool.

For your simulation, the key implication is that inter-target dependencies are expressed purely through file-level edges. A "target" is just a cluster of compile edges feeding into a link edge, with the link edge depending on upstream library outputs via implicit deps. The scheduler sees only edges and nodes.

## Observed scheduling behavior and known limitations

The **"long tail" problem** was Ninja's most documented scheduling deficiency before v1.12.0. With thousands of `.cpp` files ready and several expensive link steps, the old arbitrary scheduler would sometimes delay compilations that sat on critical chains, pushing all linking to the end of the build. GitHub Issue #232 captured this clearly: "a cpp file from a lower-level project is not scheduled to compile until much later, blocking all the linking actions." Developer benchmarks on PR #2019 showed that **weighted critical path scheduling reduced wall time by ~25%** (20 minutes → 15 minutes) on one real project, primarily by starting deep-chain compilations earlier.

The simplified depth-based heuristic in v1.12.0 helps but is not optimal. Issue #2682 (still active) proposes using **summed historical build times** from `.ninja_log` as weights instead of uniform edge counts, which would better prioritize chains containing expensive linker invocations. Testing showed significant improvements on link-heavy builds at high `-j` counts.

**Benchmark data on scaling**: Hammad Mazhar tested Make vs Ninja from `-j1` through `-j8` on a 4-core/8-thread system with projects of ~400-500 files. Full-build wall times were **virtually identical** between Make and Ninja at every core count — the difference was <3%. David Röthlisberger's benchmark with 100,000 C files showed Ninja ~3% faster on fresh builds. The real difference is incremental builds: **Ninja's no-op build on 100k files took 1.5 seconds vs Make's 73 seconds**, because Ninja's binary `.ninja_log` avoids reparsing `.d` files. Android's build system reports a "perfect parallelism ratio" (critical path time / wall time) of roughly **60%**, indicating significant room for improvement even with critical path scheduling.

## Simulation model specification

To build a faithful discrete-event simulation of Ninja's scheduler, implement these components:

- **Graph representation**: Directed graph of edges (build commands) and nodes (files). Each edge has inputs, outputs, a pool assignment, and a `critical_path_weight` (int64_t).
- **Critical path precomputation**: Topological sort all edges. Assign weight 1 to non-phony, 0 to phony. Back-propagate max weights from targets to leaves. This is O(V+E).
- **Ready queue**: Max-heap priority queue keyed on `critical_path_weight`. Initialize with all edges whose inputs are all satisfied.
- **Pool tracking**: Per pool, maintain `current_use` counter and `delayed` priority set. When scheduling an edge, check `current_use < depth`; if not, delay it. When an edge finishes, decrement and release the highest-priority delayed edge.
- **Job slots**: Global counter bounded by `-j`. Each simulation tick: start as many edges as `min(ready_queue.size(), j - running_count, available_pool_capacity)` allows, selecting by priority. When an edge completes (after its simulated duration), run the cascade: mark outputs ready, check all downstream edges, push newly-ready ones into the ready queue (or pool delay set).
- **Event loop**: Maintain a time-ordered event queue of completion times. Advance to the earliest completion, process it, start new work, repeat until the ready queue is empty and nothing is running.

The simulation should reproduce Ninja's key behaviors: interleaving across targets, critical-path prioritization of deep chains, pool throttling of link steps, and the cascading unlock pattern. For maximum fidelity, parse an actual `build.ninja` file and use recorded durations from `.ninja_log` as edge execution times.

## Conclusion

Ninja's scheduler is more sophisticated than commonly assumed. The v1.12.0 critical path scheduler transformed it from effectively random ordering into a depth-weighted priority system that preferentially builds edges on the longest dependency chain. The three-layer parallelism model (global `-j`, per-pool depth, load average) provides flexible resource control. The flat graph architecture — with no target-level grouping — means compilation freely interleaves across what CMake considers separate targets, constrained only by explicit file dependencies. The remaining optimization frontier is using actual recorded build times rather than uniform weights, which Issue #2682 addresses. For simulation purposes, the algorithm is straightforward to replicate: precompute longest-path weights via back-propagation on the topological sort, use a max-heap ready queue, and model pools as gated capacity counters with priority-ordered delay sets.