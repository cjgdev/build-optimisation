"""Critical path analysis, build simulation, and what-if modelling."""

from __future__ import annotations

import heapq
from dataclasses import dataclass

import networkx as nx
import pandas as pd

from buildanalysis.types import AnalysisScope, BuildGraph


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


def compute_critical_path(
    bg: BuildGraph,
    timing: pd.DataFrame,
    time_col: str = "total_build_time_ms",
) -> CriticalPathResult:
    """Compute the critical path through the build DAG using longest-path DP."""
    g = bg.graph
    durations = _get_durations(bg, timing, time_col)

    # Forward pass: process dependencies before dependants
    # Since A→B means "A depends on B", reversed topological order gives deps first
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
        rows.append({
            "cmake_target": node,
            "build_time_ms": durations[node],
            "earliest_start_ms": earliest_start[node],
            "earliest_finish_ms": earliest_finish[node],
            "latest_start_ms": latest_start[node],
            "latest_finish_ms": latest_finish[node],
            "slack_ms": slack,
            "on_critical_path": abs(slack) < 1e-9,
        })
    target_slack = pd.DataFrame(rows)

    # Reconstruct the critical path as an ordered list of targets
    cp_nodes = [r["cmake_target"] for r in rows if abs(r["slack_ms"]) < 1e-9]
    # Sort by earliest_start to get proper order
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
) -> pd.DataFrame:
    """Simulate a parallel build using greedy list-scheduling."""
    if scope is not None:
        bg = bg.subgraph(scope)

    g = bg.graph
    durations = _get_durations(bg, timing, time_col)

    # Priority = longest path from target to any root (dependant chain)
    # Process in topological order so dependants are computed before dependencies
    longest_to_root: dict[str, float] = {}
    for node in nx.topological_sort(g):
        dependants = list(g.predecessors(node))
        longest_to_root[node] = durations[node] + max(
            (longest_to_root[d] for d in dependants), default=0.0
        )

    # Track remaining dependency counts and when each target becomes ready
    remaining_deps: dict[str, int] = {}
    ready_at: dict[str, float] = {}  # time when last dependency finishes

    for node in g.nodes():
        n_deps = g.out_degree(node)
        remaining_deps[node] = n_deps
        if n_deps == 0:
            ready_at[node] = 0.0

    # ready heap: (-priority, target_name, ready_time)
    ready: list[tuple[float, str, float]] = []
    for node in g.nodes():
        if remaining_deps[node] == 0:
            heapq.heappush(ready, (-longest_to_root[node], node, 0.0))

    # Core availability: min-heap of (free_at_time, core_id)
    core_heap: list[tuple[float, int]] = [(0.0, i) for i in range(n_cores)]

    schedule: list[dict] = []
    finish_events: list[tuple[float, str]] = []  # (finish_time, node)

    def _process_finish(finished_time: float, finished_node: str) -> None:
        for dependant in g.predecessors(finished_node):
            remaining_deps[dependant] -= 1
            # Track the latest dependency finish time
            ready_at[dependant] = max(ready_at.get(dependant, 0.0), finished_time)
            if remaining_deps[dependant] == 0:
                heapq.heappush(ready, (-longest_to_root[dependant], dependant, ready_at[dependant]))

    while ready or finish_events:
        if ready:
            # Get the earliest available core
            core_time, core_id = heapq.heappop(core_heap)

            # Pop the highest-priority ready target
            _, node, node_ready_at = heapq.heappop(ready)

            # Target can't start before both core is free AND dependencies done
            start = max(core_time, node_ready_at)
            end = start + durations[node]
            schedule.append({
                "cmake_target": node,
                "start_ms": start,
                "end_ms": end,
                "core": core_id,
            })
            heapq.heappush(core_heap, (end, core_id))
            heapq.heappush(finish_events, (end, node))

            # Process any finish events that have occurred by now
            while finish_events and finish_events[0][0] <= start:
                ft, fn = heapq.heappop(finish_events)
                _process_finish(ft, fn)

        elif finish_events:
            ft, fn = heapq.heappop(finish_events)
            _process_finish(ft, fn)

    return pd.DataFrame(schedule)


def validate_simulation(
    simulated: pd.DataFrame,
    observed: pd.DataFrame,
    tolerance_pct: float = 10,
) -> dict:
    """Compare a simulated build schedule against observed data."""
    sim_wall = simulated["end_ms"].max()

    # Aggregate observed to target level
    obs_by_target = observed.groupby("cmake_target").agg(
        start_ms=("start_ms", "min"),
        end_ms=("end_ms", "max"),
    )
    obs_wall = obs_by_target["end_ms"].max()

    error_pct = abs(sim_wall - obs_wall) / obs_wall * 100 if obs_wall > 0 else 0.0

    # Utilisation: fraction of core-time actually used
    sim_n_cores = simulated["core"].nunique()
    sim_total_work = (simulated["end_ms"] - simulated["start_ms"]).sum()
    sim_util = sim_total_work / (sim_wall * sim_n_cores) if sim_wall > 0 and sim_n_cores > 0 else 0.0

    obs_n_cores = observed["core"].nunique() if "core" in observed.columns else 1
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

    original_time = timing.loc[timing["cmake_target"] == target, time_col].iloc[0]
    reduced_time = int(original_time * (1 - reduction_pct / 100))

    modified_timing = timing.copy()
    modified_timing.loc[modified_timing["cmake_target"] == target, time_col] = reduced_time

    new_cp = compute_critical_path(bg, modified_timing, time_col)

    baseline_ms = baseline.total_time_s * 1000
    new_ms = new_cp.total_time_s * 1000

    on_cp = baseline.target_slack[
        baseline.target_slack["cmake_target"] == target
    ].iloc[0]["on_critical_path"]

    return {
        "target": target,
        "original_time_ms": original_time,
        "reduced_time_ms": reduced_time,
        "baseline_critical_path_ms": baseline_ms,
        "new_critical_path_ms": new_ms,
        "delta_ms": baseline_ms - new_ms,
        "on_original_critical_path": bool(on_cp),
    }
