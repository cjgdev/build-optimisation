"""Rebuild cost estimation, merge/split simulation, and incremental build modelling.

All functions operate on the dependency graph with metrics attached as node attributes.
"""

from __future__ import annotations

import networkx as nx
import pandas as pd

from buildanalysis.build import simulate_build as _simulate_build
from buildanalysis.types import BuildGraph


def rebuild_cost(G: nx.DiGraph, target: str, metrics_df: pd.DataFrame) -> int:
    """Total transitive rebuild cost if a target changes.

    Includes the target itself plus all targets that depend on it.
    Dependants are found in the reversed graph: nx.descendants(G.reverse(), target)
    which gives all nodes that have target as a transitive dependency.
    """
    metrics = metrics_df.set_index("cmake_target")["total_build_time_ms"]
    rev = G.reverse()
    dependants = nx.descendants(rev, target)
    affected = dependants | {target}

    total = 0
    for node in affected:
        if node in metrics.index:
            val = metrics[node]
            if pd.notna(val):
                total += int(val)
    return total


def expected_daily_cost(
    G: nx.DiGraph,
    target: str,
    metrics_df: pd.DataFrame,
    git_df: pd.DataFrame,
    git_history_months: int = 12,
) -> float:
    """Expected rebuild cost per working day.

    change_probability = git_commit_count / (git_history_months * 20 working days)
    cost = change_probability * rebuild_cost
    """
    metrics = metrics_df.set_index("cmake_target")

    # Compute change probability from authored file commits
    if target in metrics.index:
        commit_count = metrics.loc[target].get("git_commit_count_total", 0)
        if pd.isna(commit_count):
            commit_count = 0
    else:
        commit_count = 0

    working_days = git_history_months * 20
    change_prob = commit_count / working_days if working_days > 0 else 0

    return change_prob * rebuild_cost(G, target, metrics_df)


def simulate_merge(
    G: nx.DiGraph,
    targets: list[str],
    metrics_df: pd.DataFrame,
) -> dict:
    """Simulate merging multiple targets into one.

    Returns before/after metrics and savings estimate.
    """
    metrics = metrics_df.set_index("cmake_target")

    # Before: sum of individual build costs
    before_compile = 0
    before_total = 0
    codegen_notes = []

    for t in targets:
        if t in metrics.index:
            row = metrics.loc[t]
            before_compile += int(row.get("compile_time_sum_ms", 0) or 0)
            before_total += int(row.get("total_build_time_ms", 0) or 0)
            if row.get("codegen_file_count", 0) > 0:
                codegen_notes.append(f"{t} has {int(row['codegen_file_count'])} codegen files")

    # After: merged target has same total compile time,
    # but saves redundant archive/link steps (only one archive/link instead of N)
    archive_savings = 0
    link_savings = 0
    for t in targets[1:]:  # keep one archive/link, save the rest
        if t in metrics.index:
            row = metrics.loc[t]
            archive_savings += int(row.get("archive_time_ms", 0) or 0)
            link_savings += int(row.get("link_time_ms", 0) or 0)

    after_total = before_total - archive_savings - link_savings
    savings = before_total - after_total

    notes = []
    if codegen_notes:
        notes.extend(codegen_notes)
        notes.append("Merged target inherits all codegen steps")

    # Check for inter-target dependencies that would be eliminated
    inter_edges = 0
    target_set = set(targets)
    for t in targets:
        for dep in G.successors(t):
            if dep in target_set:
                inter_edges += 1
    if inter_edges > 0:
        notes.append(f"Eliminates {inter_edges} inter-target dependencies")

    return {
        "before_ms": before_total,
        "after_ms": after_total,
        "savings_ms": savings,
        "notes": notes,
    }


def simulate_split(
    G: nx.DiGraph,
    target: str,
    file_groups: list[list[str]],
    metrics_df: pd.DataFrame,
) -> dict:
    """Simulate splitting a target into partitions.

    file_groups: list of lists of source file paths, one per partition.
    Returns before/after metrics per partition.
    """
    metrics = metrics_df.set_index("cmake_target")

    # Before
    before = {}
    if target in metrics.index:
        row = metrics.loc[target]
        before = {
            "compile_time_sum_ms": int(row.get("compile_time_sum_ms", 0) or 0),
            "total_build_time_ms": int(row.get("total_build_time_ms", 0) or 0),
            "file_count": int(row.get("file_count", 0) or 0),
        }

    # After: estimate per partition
    partitions = []
    notes = []

    for i, group in enumerate(file_groups):
        partition = {
            "partition": i,
            "file_count": len(group),
            "files": group,
        }
        partitions.append(partition)

    # Check for generated files spanning partitions
    if target in metrics.index:
        row = metrics.loc[target]
        gen_count = int(row.get("codegen_file_count", 0) or 0)
        if gen_count > 0:
            notes.append(f"Target has {gen_count} generated files — ensure they stay with consumers")

    # Cross-partition edge count (would create new inter-target deps)
    cross_edges = len(file_groups) - 1  # minimum new edges
    notes.append(f"Split creates {len(file_groups)} new targets with ~{cross_edges} new dependency edges")

    return {
        "before": before,
        "partitions": partitions,
        "cross_partition_edges": cross_edges,
        "notes": notes,
    }


def simulate_incremental_build(
    G: nx.DiGraph,
    modified_targets: list[str],
    target_times: dict[str, float],
    n_cores: int,
    enabled_targets: set[str] | None = None,
) -> float:
    """Simulate a parallel incremental build and return wall-clock time.

    Models a Ninja v1.12-faithful scheduler with depth-based critical path
    weights. Delegates to buildanalysis.build.simulate_build.

    Args:
        G: Dependency DAG where A -> B means A depends on B.
        modified_targets: Targets directly changed.
        target_times: Dict mapping target name to compile time in ms.
        n_cores: Number of parallel build slots (0 = unlimited).
        enabled_targets: If provided, restrict rebuild set to these targets only.

    Returns:
        Simulated wall-clock build time in ms.
    """
    if not modified_targets:
        return 0.0

    # Find all targets that need rebuilding: modified + their transitive dependants
    rev = G.reverse()
    rebuild_set: set[str] = set()
    for t in modified_targets:
        if t in rev:
            rebuild_set |= nx.descendants(rev, t)
        rebuild_set.add(t)

    if enabled_targets is not None:
        rebuild_set &= enabled_targets

    if not rebuild_set:
        return 0.0

    sub = G.subgraph(rebuild_set).copy()

    try:
        nx.topological_sort(sub)
    except nx.NetworkXUnfeasible:
        return sum(target_times.get(t, 0) for t in rebuild_set)

    empty_meta = pd.DataFrame(index=pd.Index(list(rebuild_set), name="cmake_target"))
    bg = BuildGraph(graph=sub, target_metadata=empty_meta)

    timing_df = pd.DataFrame(
        [{"cmake_target": t, "total_build_time_ms": target_times.get(t, 0.0)} for t in rebuild_set]
    )

    effective_cores = len(rebuild_set) if n_cores <= 0 else n_cores
    schedule = _simulate_build(bg, timing_df, n_cores=effective_cores)
    return float(schedule["end_ms"].max()) if len(schedule) > 0 else 0.0


def replay_git_history(
    G: nx.DiGraph,
    commits: pd.DataFrame,
    file_to_target: dict[str, str],
    target_times: dict[str, float],
    n_cores: int,
    enabled_targets_per_team: dict[str, set[str]] | None = None,
) -> pd.DataFrame:
    """Replay historical commits and compute per-commit incremental build times.

    Args:
        G: Dependency DAG.
        commits: DataFrame with columns (commit_hash, author_email, source_file).
                 May also have (commit_date, team).
        file_to_target: Mapping from source file path to target name.
        target_times: Dict mapping target name to compile time in ms.
        n_cores: Number of parallel build slots.
        enabled_targets_per_team: Optional dict mapping team name to set of enabled targets.

    Returns:
        DataFrame with columns (commit_hash, author_email, modified_targets,
        rebuild_count, build_time_ms, team).
    """
    results = []

    for commit_hash, group in commits.groupby("commit_hash"):
        author = group["author_email"].iloc[0] if "author_email" in group.columns else ""
        team = group["team"].iloc[0] if "team" in group.columns else ""

        # Find modified targets
        modified = set()
        for f in group["source_file"]:
            t = file_to_target.get(f)
            if t and t in G:
                modified.add(t)

        if not modified:
            results.append(
                {
                    "commit_hash": commit_hash,
                    "author_email": author,
                    "modified_targets": 0,
                    "rebuild_count": 0,
                    "build_time_ms": 0.0,
                    "team": team,
                }
            )
            continue

        # Determine enabled targets
        enabled = None
        if enabled_targets_per_team and team in enabled_targets_per_team:
            enabled = enabled_targets_per_team[team]

        build_time = simulate_incremental_build(
            G,
            list(modified),
            target_times,
            n_cores,
            enabled_targets=enabled,
        )

        # Count rebuild set
        rev = G.reverse()
        rebuild_set = set()
        for t in modified:
            if t in rev:
                rebuild_set |= nx.descendants(rev, t)
            rebuild_set.add(t)
        if enabled is not None:
            rebuild_set &= enabled

        results.append(
            {
                "commit_hash": commit_hash,
                "author_email": author,
                "modified_targets": len(modified),
                "rebuild_count": len(rebuild_set),
                "build_time_ms": build_time,
                "team": team,
            }
        )

    return pd.DataFrame(results)
