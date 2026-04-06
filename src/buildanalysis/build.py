"""Critical path analysis, build simulation, and what-if modelling.

The simulate_build scheduler faithfully models Ninja v1.12's scheduling:
- Depth-based critical path weights (non-phony node count, not duration)
- Max-heap priority queue keyed on critical_path_weight
- Per-pool concurrency limits with delayed priority sets
- Global -j cap as hard upper bound on parallelism
- Flat graph with no target grouping — compilation freely interleaves
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

import networkx as nx
import pandas as pd

from buildanalysis.types import AnalysisScope, BuildGraph

_PHONY_TARGET_TYPES: frozenset[str] = frozenset({"interface_library", "custom_target"})

_LINK_TARGET_TYPES: frozenset[str] = frozenset({"executable", "shared_library", "module_library"})


@dataclass(frozen=True, slots=True)
class PoolConfig:
    """Per-pool concurrency limits for the Ninja-faithful scheduler.

    Depth 0 means unlimited. The default pool is always unlimited.
    """

    pools: dict[str, int]

    @classmethod
    def default(cls) -> PoolConfig:
        return cls(pools={})

    @classmethod
    def with_link_pool(cls, link_depth: int = 4) -> PoolConfig:
        return cls(pools={"link_pool": link_depth})

    def depth(self, pool_name: str) -> int:
        return self.pools.get(pool_name, 0)

    def is_unlimited(self, pool_name: str) -> bool:
        return self.depth(pool_name) == 0


@dataclass
class CriticalPathResult:
    path: list[str]
    total_time_s: float
    target_slack: pd.DataFrame
    parallelism_ratio: float
    total_work_s: float


def _get_durations(bg: BuildGraph, timing: pd.DataFrame, time_col: str) -> dict[str, float]:
    """Map each node to its build duration in ms, defaulting to 0."""
    timing_map = timing.set_index("cmake_target")[time_col].to_dict()
    return {node: timing_map.get(node, 0.0) for node in bg.graph.nodes()}


def _compute_cp_weights(bg: BuildGraph) -> dict[str, int]:
    """Compute Ninja v1.12+ depth-based critical path weights.

    Each node's weight = count of non-phony nodes on the longest chain from
    that node to any leaf (node with no dependencies), inclusive of the node
    itself if non-phony.

    Computed via DP in reverse topological order (leaves processed first).
    """
    g = bg.graph
    phony: set[str] = set()
    if "target_type" in bg.target_metadata.columns:
        for n in g.nodes():
            if n in bg.target_metadata.index:
                t_type = bg.target_metadata.loc[n, "target_type"]
                if t_type in _PHONY_TARGET_TYPES:
                    phony.add(n)

    weights: dict[str, int] = {}
    for node in reversed(list(nx.topological_sort(g))):
        own = 0 if node in phony else 1
        dep_max = max((weights[dep] for dep in g.successors(node)), default=0)
        weights[node] = own + dep_max
    return weights


def _pool_assignments(bg: BuildGraph, pool_config: PoolConfig, pool_col: str) -> dict[str, str]:
    """Return mapping from target name to pool name."""
    if pool_col in bg.target_metadata.columns:
        raw = bg.target_metadata[pool_col].where(bg.target_metadata[pool_col].notna(), other="default")
        return raw.to_dict()

    result: dict[str, str] = {}
    has_link_pool = not pool_config.is_unlimited("link_pool")
    for node in bg.graph.nodes():
        pool = "default"
        if has_link_pool and node in bg.target_metadata.index:
            t_type = bg.target_metadata.loc[node, "target_type"]
            if t_type in _LINK_TARGET_TYPES:
                pool = "link_pool"
        result[node] = pool
    return result


def compute_critical_path(
    bg: BuildGraph,
    timing: pd.DataFrame,
    time_col: str = "total_build_time_ms",
) -> CriticalPathResult:
    """Compute the critical path through the build DAG using longest-path DP."""
    g = bg.graph
    durations = _get_durations(bg, timing, time_col)

    # Forward pass: process dependencies before dependants
    # Since A->B means "A depends on B", reversed topological order gives deps first
    earliest_start: dict[str, float] = {}
    earliest_finish: dict[str, float] = {}
    topo_order = list(nx.topological_sort(g))

    for node in reversed(topo_order):
        deps = list(g.successors(node))
        es = max((earliest_finish[d] for d in deps), default=0.0)
        earliest_start[node] = es
        earliest_finish[node] = es + durations[node]

    cp_length = max(earliest_finish.values()) if earliest_finish else 0.0

    # Backward pass: process dependants before dependencies (original topo order)
    latest_finish: dict[str, float] = {}
    latest_start: dict[str, float] = {}

    for node in topo_order:
        dependants = list(g.predecessors(node))
        lf = min((latest_start[d] for d in dependants), default=cp_length)
        latest_finish[node] = lf
        latest_start[node] = lf - durations[node]

    # Build slack DataFrame
    rows = []
    for node in g.nodes():
        slack = latest_start[node] - earliest_start[node]
        rows.append(
            {
                "cmake_target": node,
                "build_time_ms": durations[node],
                "earliest_start_ms": earliest_start[node],
                "earliest_finish_ms": earliest_finish[node],
                "latest_start_ms": latest_start[node],
                "latest_finish_ms": latest_finish[node],
                "slack_ms": slack,
                "on_critical_path": abs(slack) < 1e-9,
            }
        )
    target_slack = pd.DataFrame(rows)

    # Reconstruct the critical path as an ordered list of targets
    cp_nodes = [r["cmake_target"] for r in rows if abs(r["slack_ms"]) < 1e-9]
    cp_nodes.sort(key=lambda n: earliest_start[n])

    total_work = sum(durations.values())

    return CriticalPathResult(
        path=cp_nodes,
        total_time_s=cp_length / 1000.0,
        target_slack=target_slack,
        parallelism_ratio=total_work / cp_length if cp_length > 0 else 1.0,
        total_work_s=total_work / 1000.0,
    )


def simulate_build(
    bg: BuildGraph,
    timing: pd.DataFrame,
    n_cores: int = 8,
    time_col: str = "total_build_time_ms",
    scope: AnalysisScope | None = None,
    target: str | None = None,
    pool_config: PoolConfig | None = None,
    pool_col: str = "pool",
) -> pd.DataFrame:
    """Simulate a parallel build using a Ninja v1.12-faithful scheduler.

    Scheduling policy:
    - Priority = Ninja-style depth-based critical path weight (non-phony
      nodes only). Higher weight = dequeued first.
    - Global concurrency bounded by n_cores.
    - Per-pool concurrency bounded by PoolConfig.depth(pool_name).
    - Flat graph: no target grouping. All ready nodes compete globally.

    Args:
        bg: Build graph (A -> B means A depends on B).
        timing: DataFrame with cmake_target and time_col columns.
        n_cores: Global parallelism cap (-j equivalent).
        time_col: Column in timing to use as duration.
        scope: Restrict to scoped subgraph (mutually exclusive with target).
        target: Build only this target and its transitive dependencies.
        pool_config: Per-pool depth limits. None = no pool constraints.
        pool_col: Column in bg.target_metadata holding pool assignments.

    Returns:
        DataFrame with columns: cmake_target, start_ms, end_ms, core.
    """
    if scope is not None and target is not None:
        raise ValueError("'scope' and 'target' are mutually exclusive")
    if scope is not None:
        bg = bg.subgraph(scope)
    if target is not None:
        if target not in bg.graph:
            raise KeyError(f"Target '{target}' not found in build graph")
        nodes = {target} | nx.descendants(bg.graph, target)
        sub_g = bg.graph.subgraph(nodes).copy()
        sub_meta = bg.target_metadata.loc[bg.target_metadata.index.intersection(nodes)]
        bg = BuildGraph(graph=sub_g, target_metadata=sub_meta)

    if pool_config is None:
        pool_config = PoolConfig.default()

    g = bg.graph
    durations = _get_durations(bg, timing, time_col)
    cp_weights = _compute_cp_weights(bg)
    pool_map = _pool_assignments(bg, pool_config, pool_col)

    # Track dependency readiness
    remaining_deps: dict[str, int] = {node: g.out_degree(node) for node in g.nodes()}
    ready_at: dict[str, float] = {node: 0.0 for node in g.nodes() if g.out_degree(node) == 0}

    # Ready queue: max-heap keyed on cp_weight via negation. Entry = (-weight, node, ready_time)
    ready: list[tuple[int, str, float]] = []
    for node in g.nodes():
        if remaining_deps[node] == 0:
            heapq.heappush(ready, (-cp_weights[node], node, 0.0))

    # Per-pool state: running count + delayed priority queue
    pool_running: dict[str, int] = {}
    pool_delayed: dict[str, list[tuple[int, str, float]]] = {}

    # Core availability: min-heap of (free_at_time, core_id)
    core_heap: list[tuple[float, int]] = [(0.0, i) for i in range(n_cores)]

    schedule: list[dict[str, object]] = []
    finish_events: list[tuple[float, str]] = []

    def _release_dependants(finished_time: float, finished_node: str) -> None:
        for dependant in g.predecessors(finished_node):
            remaining_deps[dependant] -= 1
            ready_at[dependant] = max(ready_at.get(dependant, 0.0), finished_time)
            if remaining_deps[dependant] == 0:
                heapq.heappush(ready, (-cp_weights[dependant], dependant, ready_at[dependant]))

    def _release_pool(finished_time: float, finished_node: str) -> None:
        pool = pool_map[finished_node]
        pool_running[pool] = pool_running.get(pool, 0) - 1
        delayed = pool_delayed.get(pool)
        if delayed:
            depth = pool_config.depth(pool)
            while delayed and (depth == 0 or pool_running.get(pool, 0) < depth):
                neg_w, node, node_ready_at = heapq.heappop(delayed)
                # Item cannot start before pool capacity freed up
                effective_ready = max(node_ready_at, finished_time)
                heapq.heappush(ready, (neg_w, node, effective_ready))
                if depth > 0:
                    break  # release one at a time; scheduler loop will check again

    def _process_finish(finished_time: float, finished_node: str) -> None:
        _release_pool(finished_time, finished_node)
        _release_dependants(finished_time, finished_node)

    while ready or finish_events:
        # Try to start tasks on available cores
        started_any = False
        while ready and core_heap:
            core_time, core_id = core_heap[0]

            neg_w, node, node_ready_at = heapq.heappop(ready)

            # Check pool capacity
            pool = pool_map[node]
            pool_depth = pool_config.depth(pool)
            if pool_depth > 0 and pool_running.get(pool, 0) >= pool_depth:
                if pool not in pool_delayed:
                    pool_delayed[pool] = []
                heapq.heappush(pool_delayed[pool], (neg_w, node, node_ready_at))
                continue

            # Start the task
            heapq.heappop(core_heap)
            start = max(core_time, node_ready_at)
            end = start + durations[node]
            schedule.append({"cmake_target": node, "start_ms": start, "end_ms": end, "core": core_id})
            heapq.heappush(core_heap, (end, core_id))
            heapq.heappush(finish_events, (end, node))
            pool_running[pool] = pool_running.get(pool, 0) + 1
            started_any = True

        if not started_any:
            # Advance time to next finish event
            if finish_events:
                ft, fn = heapq.heappop(finish_events)
                _process_finish(ft, fn)
            else:
                break

    # Drain remaining finish events to release dependants
    while finish_events:
        ft, fn = heapq.heappop(finish_events)
        _process_finish(ft, fn)

    return pd.DataFrame(schedule)


def validate_simulation(
    simulated: pd.DataFrame,
    observed: pd.DataFrame,
    tolerance_pct: float = 10,
) -> dict:
    """Compare a simulated build schedule against observed data.

    The simulated schedule (from ``simulate_build``) uses ``start_ms`` /
    ``end_ms`` columns.  The observed schedule (``build_schedule.parquet``)
    may use ``start_time_ms`` / ``end_time_ms`` instead — both conventions
    are handled transparently.
    """
    sim_wall = simulated["end_ms"].max()

    # Normalise observed column names to start_ms / end_ms
    obs = observed.copy()
    if "start_time_ms" in obs.columns and "start_ms" not in obs.columns:
        obs = obs.rename(columns={"start_time_ms": "start_ms", "end_time_ms": "end_ms"})

    # Aggregate observed to target level
    obs_by_target = obs.groupby("cmake_target").agg(
        start_ms=("start_ms", "min"),
        end_ms=("end_ms", "max"),
    )
    obs_wall = obs_by_target["end_ms"].max()

    error_pct = abs(sim_wall - obs_wall) / obs_wall * 100 if obs_wall > 0 else 0.0

    # Utilisation: fraction of core-time actually used
    sim_n_cores = simulated["core"].nunique()
    sim_total_work = (simulated["end_ms"] - simulated["start_ms"]).sum()
    sim_util = sim_total_work / (sim_wall * sim_n_cores) if sim_wall > 0 and sim_n_cores > 0 else 0.0

    obs_n_cores = obs["core"].nunique() if "core" in obs.columns else 1
    obs_total_work = (obs_by_target["end_ms"] - obs_by_target["start_ms"]).sum()
    obs_util = obs_total_work / (obs_wall * obs_n_cores) if obs_wall > 0 and obs_n_cores > 0 else 0.0

    return {
        "simulated_wall_time_ms": sim_wall,
        "observed_wall_time_ms": obs_wall,
        "wall_time_error_pct": error_pct,
        "within_tolerance": error_pct <= tolerance_pct,
        "simulated_avg_utilisation": sim_util,
        "observed_avg_utilisation": obs_util,
    }


def whatif_remove_edge(
    bg: BuildGraph,
    timing: pd.DataFrame,
    source: str,
    dependency: str,
    time_col: str = "total_build_time_ms",
) -> dict:
    """Simulate removing a single dependency edge and report the impact."""
    baseline = compute_critical_path(bg, timing, time_col)

    # Create modified graph
    new_g = bg.graph.copy()
    if new_g.has_edge(source, dependency):
        new_g.remove_edge(source, dependency)

    is_valid = nx.is_directed_acyclic_graph(new_g)
    new_bg = BuildGraph(graph=new_g, target_metadata=bg.target_metadata)
    new_cp = compute_critical_path(new_bg, timing, time_col)

    baseline_ms = baseline.total_time_s * 1000
    new_ms = new_cp.total_time_s * 1000

    return {
        "removed_edge": (source, dependency),
        "baseline_critical_path_ms": baseline_ms,
        "new_critical_path_ms": new_ms,
        "delta_ms": baseline_ms - new_ms,
        "new_critical_path": new_cp.path,
        "is_valid": is_valid,
    }


def whatif_reduce_target_time(
    bg: BuildGraph,
    timing: pd.DataFrame,
    target: str,
    reduction_pct: float,
    time_col: str = "total_build_time_ms",
) -> dict:
    """Simulate reducing a target's build time and report the impact."""
    baseline = compute_critical_path(bg, timing, time_col)

    matches = timing.loc[timing["cmake_target"] == target, time_col]
    if matches.empty:
        raise KeyError(f"Target '{target}' not found in timing DataFrame")
    original_time = matches.iloc[0]
    reduced_time = int(original_time * (1 - reduction_pct / 100))

    modified_timing = timing.copy()
    modified_timing.loc[modified_timing["cmake_target"] == target, time_col] = reduced_time

    new_cp = compute_critical_path(bg, modified_timing, time_col)

    baseline_ms = baseline.total_time_s * 1000
    new_ms = new_cp.total_time_s * 1000

    on_cp = baseline.target_slack[baseline.target_slack["cmake_target"] == target].iloc[0]["on_critical_path"]

    return {
        "target": target,
        "original_time_ms": original_time,
        "reduced_time_ms": reduced_time,
        "baseline_critical_path_ms": baseline_ms,
        "new_critical_path_ms": new_ms,
        "delta_ms": baseline_ms - new_ms,
        "on_original_critical_path": bool(on_cp),
    }
