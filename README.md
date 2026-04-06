# Build Optimiser

## Why this exists

Large C++ codebases are difficult to analyse in any meaningful way. Build times creep upward, dependency graphs become tangled, header inclusions balloon, and nobody can say with confidence *where the time goes* or *what to fix first*. Traditional approaches — profiling a single build, eyeballing compile times, or relying on tribal knowledge — don't scale.

Build Optimiser applies modern data science techniques to build analysis. It instruments a CMake + Ninja build pipeline, then joins the build graph with compile times, GCC phase breakdowns, preprocessed sizes, header inclusion trees, git history, code metrics, and just the right amount of organisational knowledge (team ownership, module boundaries) to analyse codebases of almost any size and complexity. The result is a complete, quantitative picture of where build time is spent, why it's spent there, and what to do about it — backed by data rather than intuition.

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- CMake 4.2+ with [File API](https://cmake.org/cmake/help/latest/manual/cmake-file-api.7.html) support
- Ninja build system
- GCC (for `-ftime-report` and `-H` instrumentation)

## Quick start

```zsh
# Clone and install
git clone <repo-url> && cd build-optimisation
uv sync --all-extras

# Configure — edit config.yaml to point at your C++ project
cp config.yaml config.yaml.local
$EDITOR config.yaml.local

# Collect build data
./scripts/collect_all.sh

# Consolidate into parquet tables
./scripts/consolidate_all.sh

# Launch notebooks
uv run jupyter lab notebooks/optimisation/
```

## Configuration

Copy `config.yaml` and fill in paths for your environment:

```yaml
source_dir: /path/to/your/cpp/project
build_dir: ./data/builds/main
raw_data_dir: ./data/raw
processed_data_dir: ./data/processed

cc: /usr/bin/gcc
cxx: /usr/bin/g++

cmake_prefix_path: []
cmake_cache_variables:
  CMAKE_MAKE_PROGRAM: "/usr/bin/ninja"
  CMAKE_EXPORT_COMPILE_COMMANDS: "ON"

git_history_months: 12
ninja_jobs: 0           # 0 = auto (number of cores)
preprocess_workers: 0   # 0 = auto (cpu_count)
```

Optional team and module configuration files go in the project root:
- `teams.yaml` — map email patterns to teams for ownership analysis
- `modules.yaml` — define logical module boundaries for self-containment metrics

---

## Analysis notebooks

Ten sequenced notebooks in `notebooks/optimisation/` that progressively build a complete picture of the codebase. Each notebook produces intermediate parquet files consumed by later notebooks, so they should be run in order.

### 01 — Data Validation

Validates every parquet table produced by the collection pipeline before analysis begins. Checks schemas, referential integrity (do all `cmake_target` foreign keys resolve?), null distributions, and value ranges. This catches collection errors early — a broken header parse or a missing ninja log — before they silently corrupt downstream analysis.

### 02 — Teams and Ownership

Maps git contributors to teams using `teams.yaml` email aliases, then computes per-target ownership metrics: which team owns each target, how concentrated that ownership is (Herfindahl-Hirschman Index), and what the bus factor looks like. This reveals targets with diffuse ownership where no team feels responsible, cross-team coupling where changes in one team's code force rebuilds of another's, and unresolved contributors whose emails don't match any team.

### 03 — Global Profile

Establishes the overall shape of the codebase: how many targets, how they break down by type (executable, static library, shared library), how much code is hand-written versus generated, and what the preprocessor expansion ratios look like. K-means segmentation groups targets into behavioural clusters (e.g. "large generated libraries", "small hand-written utilities") to reveal structural patterns. This provides the baseline context that makes all subsequent analysis interpretable.

### 04 — Build Performance

The core build time analysis. Breaks down wall-clock build time by compilation phase (GCC parse, template instantiation, code generation), computes the critical path through the dependency graph, simulates build parallelism to find bottlenecks, and runs what-if scenarios (what if this target compiled 50% faster? what if we split this library?). This directly identifies the highest-impact optimisation targets — where time savings translate into actual build speedup.

### 05 — Header and PCH Analysis

Analyses the header inclusion graph to find headers that are included widely, changed frequently, and contribute disproportionately to preprocessed output. Computes PageRank and impact scores to rank headers by their effect on build time. Identifies precompiled header (PCH) candidates per target — headers that are stable, widely included, and would yield measurable parse-time savings. This is where some of the easiest wins live: a single high-impact header change can shave minutes off a full build.

### 06 — Dependency Graph

Analyses the CMake target dependency graph for structural problems. Computes centrality metrics (betweenness, PageRank) to find bottleneck targets that everything flows through. Assigns architectural layers and detects layer violations (lower layers depending on higher ones). Runs community detection (Louvain) to discover natural clustering and compares it against declared module boundaries. This reveals unnecessary transitive dependencies, over-coupled targets, and architectural drift.

### 07 — Module Analysis

Evaluates the declared module structure from `modules.yaml` against the actual dependency graph. Measures self-containment (what fraction of a module's dependencies are internal), inter-module coupling, and whether community detection agrees with the declared boundaries. When modules have low self-containment or community detection suggests a very different grouping, it indicates the declared architecture has drifted from reality — a signal that restructuring would reduce cross-module rebuilds.

### 08 — Recommendations

Synthesises findings from all prior notebooks into a prioritised list of concrete interventions. Each recommendation includes estimated build time impact, engineering effort, confidence level, owning team, and rationale. Recommendations are categorised as quick wins, medium-effort, or strategic, and Pareto-optimal items (best impact-to-effort ratio) are flagged. This is the actionable output — the ranked list of what to fix and in what order. This notebook also produces the Gephi graph exports.

### 09 — Comparison

Compares two snapshots side-by-side to measure the effect of interventions. Computes global deltas (total build time, SLOC, dependency count), per-target deltas (which targets improved or regressed), edge deltas (added/removed dependencies), and critical path changes. This closes the feedback loop — after implementing a recommendation, take a new snapshot and run this notebook to verify the improvement.

### 10 — Trend Analysis

Plots metrics across all available snapshots as time series: total build time, compile time, link time, target count, SLOC, dependency density, and code generation ratio. Applies regression detection to flag when a metric has crossed a threshold or is trending in the wrong direction. This provides the long-term view — are build times improving over time, or is complexity creeping back in?

---

## Data pipeline

### Collection

Collection is orchestrated by `scripts/collect_all.sh` and runs in stages with controlled parallelism. Each stage instruments a different aspect of the build.

**Stage 1 — CMake File API** (serial, runs first)
Configures the build and parses the CMake File API codemodel-v2 reply. This produces the target list, source file assignments, and dependency edges that everything else is built on.

**Stage 2 — Git history** (parallel with stage 3)
Extracts the commit log for the configured history window. Per-file commit counts, lines added/deleted, churn, contributor emails, and timestamps. Merge commits and bulk-change commits (>500 files) are excluded.

**Stage 3 — Instrumented build** (parallel with stage 2)
Runs a full Ninja build with GCC's `-ftime-report` (phase timing) and `-H` (header inclusion tree) flags, captured via a stderr wrapper script. This produces per-file compile phase breakdowns and the complete header inclusion graph.

**Stages 4–6** (parallel, after stages 2 and 3)
- **Post-build metrics** — object file sizes, SLOC counts
- **Preprocessed sizes** — runs the preprocessor (`-E`) on each translation unit to measure expansion
- **Ninja log** — parses `.ninja_log` for per-step start/end timestamps to reconstruct the build schedule

### Consolidation

Consolidation is orchestrated by `scripts/consolidate_all.sh` and joins the raw collection outputs into analysis-ready parquet tables. It runs in tiered dependency order:

- **Tier 1** (parallel): `build_schedule`, `edge_list`, `file_metrics`, `contributor_metrics`
- **Tier 2** (serial, needs file_metrics): `target_metrics`
- **Tier 3** (serial, needs file_metrics + target_metrics): `header_edges`

### Output tables

A complete attribute reference for all fields is in [research/attribute_reference.md](research/attribute_reference.md).

#### `file_metrics.parquet` — one row per source file

The most granular table. Each row represents a single `.cpp`/`.cc`/`.c` file with its identity (path, target, language, generated flag), wall-clock compile time, GCC phase breakdown (parse, template instantiation, code generation), source line counts, header inclusion depth and unique header count, preprocessed and object sizes, git history (commits, churn, distinct authors), and derived ratios (expansion ratio, compile rate, object efficiency).

#### `target_metrics.parquet` — one row per CMake target

The primary analysis table. Aggregates file-level metrics up to the target level with sum, max, mean, median, standard deviation, and percentile statistics for compile times. Includes source file counts (authored vs generated), SLOC totals, GCC phase sums, header depth and inclusion stats, preprocessed size aggregates, object file totals, build step timing (compile, codegen, archive, link), git activity summaries, dependency graph metrics (direct/transitive dependency and dependant counts, topological depth, fan-in/fan-out, betweenness centrality, critical path contribution), and JSON file lists.

#### `edge_list.parquet` — one row per dependency edge

Every dependency relationship between CMake targets. Each edge records source and destination targets (with their types), whether the dependency is direct or transitive, CMake visibility (`PUBLIC`, `PRIVATE`, `INTERFACE`, `TRANSITIVE`, `UNKNOWN`), and the originating CMake dependency specification.

#### `contributor_target_commits.parquet` — one row per contributor per target

The contributor-target matrix: how many commits each git contributor has made to each CMake target. Used for ownership analysis, bus factor calculation, and team coupling metrics.

#### `git_commit_log.parquet` — one row per commit per file

The raw commit-level detail: commit hash, timestamp, contributor email, file path, lines added, and lines deleted. Merge commits and bulk changes (>500 files) are excluded.

#### `build_schedule.parquet` — one row per build step

Reconstructed from `.ninja_log`. Each row is a build step (compile, codegen, archive, link, or other) with its output file, source file (for compile steps), owning CMake target, and start/end timestamps in milliseconds since build start.

#### `header_edges.parquet` — one row per include relationship

The header inclusion graph, deduplicated within each translation unit. Each edge records the including file, included file, nesting depth, root translation unit, and whether the included file is a system/third-party header.

#### `header_metrics.parquet` — one row per unique header file

Per-header metadata: canonical path, owning CMake target (where determinable), SLOC, file size, and system header flag.

---

## Gephi graph exports

The recommendations notebook (08) produces four GEXF graph exports in `data/intermediate/gephi/`. These are designed for [Gephi](https://gephi.org/), providing interactive visual exploration of the codebase that static tables and charts cannot match. Every node and edge carries rich attributes that can be mapped to size, colour, partitioning, and filtering in Gephi, making it possible to generate beautiful, publication-quality reports that communicate codebase structure to stakeholders.

A complete attribute reference for all GEXF exports is in [research/attribute_reference.md](research/attribute_reference.md).

### `dependency_graph.gexf` — target-level dependency graph

The full CMake target dependency graph. Each node represents a CMake target with attributes covering identity (target type, module, team, source directory), build performance (compile time, total build time, link time, codegen time), code size (file count, SLOC, preprocessed size, codegen ratio), graph structure (layer, community, betweenness centrality, PageRank, in/out degree, transitive dependency count and fraction), critical path status (on critical path, slack time), and git activity (commit count, churn, ownership HHI, cross-team fraction, contributor count). Edges carry CMake visibility, and boolean flags for cross-community, cross-module, cross-team, and layer violation edges — enabling powerful filtering to isolate problematic coupling.

**Gephi usage:** Size nodes by compile time or SLOC. Colour by module or community. Filter to critical path targets. Filter edges to cross-module dependencies to see coupling. Use ForceAtlas2 layout with layer as a vertical axis for architectural visualisation.

### `module_graph.gexf` — module-level dependency graph

A compact, high-level view of inter-module relationships (~15–25 nodes). Each node represents a declared module with its category (shared, domain, infrastructure, test), owning team, target count, build time, SLOC, file count, codegen ratio, self-containment score, build fraction, and critical path target count. Edges carry a weight (number of underlying target-level edges), public/private dependency counts, and flags for cross-category and bidirectional dependencies.

**Gephi usage:** Size nodes by build time or target count. Colour by category or self-containment. Filter edges to bidirectional dependencies to find circular module coupling. This graph communicates the architecture at a level that managers and architects can engage with.

### `include_graph.gexf` — header inclusion graph

The file-level header inclusion graph (~30,000 nodes with system headers excluded). Each node represents a source file or header with its full path, origin (handwritten or generated), owning target, module, team, SLOC, file size, preprocessed bytes, PageRank, impact score, fan-in/fan-out metrics, amplification ratio, git activity (commits, churn), compile time, expansion ratio, and PCH candidate score. Edges carry a weight (number of translation units sharing this inclusion) and flags for cross-target and cross-module inclusions.

**Gephi usage:** Size nodes by impact score or fan-in. Colour by module or PCH candidate score. Filter to high-impact headers. This reveals the "header hubs" that drive preprocessor bloat and identifies where precompiled headers would be most effective.

### `cochange_graph.gexf` — co-change graph

An undirected graph where edges connect targets that change together in git commits, filtered by pointwise mutual information (PMI) threshold to suppress noise. Each node carries target type, module, team, structural community (from the dependency graph), build time, commit count, churn, contributor count, ownership HHI, codegen ratio, and SLOC. Edges carry co-change count, PMI score, Jaccard similarity, and flags for cross-module, cross-team, and whether a structural (dependency) edge exists between the targets.

**Gephi usage:** Size nodes by churn or commit count. Colour by module or team. Filter edges where `has_structural_edge` is false to find hidden coupling — targets that change together but have no declared dependency, suggesting a missing abstraction or an undeclared relationship.

---

## Snapshots

Build Optimiser supports named snapshots for tracking progress over time:

```
data/snapshots/
├── baseline-2025-01-15/
│   ├── processed/          # All parquet files
│   └── metadata.yaml       # Label, date, git ref, compiler, flags, notes
├── snapshot-2025-02-01/
│   ├── processed/
│   └── metadata.yaml
└── latest -> snapshot-2025-02-01/
```

Each snapshot captures all parquet tables along with metadata recording the git ref, branch, build configuration, compiler version, flags, core count, and notes about what interventions were applied.

Use notebook 09 (Comparison) to diff any two snapshots and notebook 10 (Trend Analysis) to visualise metrics over time with regression detection.

---

## Project structure

```
src/buildanalysis/       # Core library — all analysis code
scripts/
├── collect/             # Data collection scripts (01–06)
├── collect_all.sh       # Orchestrates collection
├── consolidate/         # Parquet consolidation scripts
└── consolidate_all.sh   # Orchestrates consolidation
notebooks/optimisation/  # Analysis notebooks (01–10)
tests/                   # Unit and integration tests
research/                # Attribute reference and design documents
data/                    # Collected data, snapshots, results
```

## Development

```zsh
# Install with dev dependencies
uv sync --all-extras

# Run unit tests
uv run pytest -m "not integration"

# Run integration tests (requires CMake, GCC, Ninja)
uv run pytest -m integration

# Lint and format check
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/
```
