"""Rebuild cost estimation and merge/split simulation.

All functions operate on the dependency graph with metrics attached as node attributes.
"""

from __future__ import annotations

import networkx as nx
import pandas as pd


def rebuild_cost(G: nx.DiGraph, target: str, metrics_df: pd.DataFrame) -> int:
    """Total transitive rebuild cost if a target changes.

    Includes the target itself plus all targets that depend on it.
    Dependants are found in the reversed graph: nx.descendants(G.reverse(), target)
    which gives all nodes that have target as a transitive dependency.
    """
    metrics = metrics_df.set_index("cmake_target")["total_build_time_ms"]
    affected = nx.ancestors(G, target) | {target}  # ancestors = things that depend on target
    # Wait — convention is A->B means A depends on B.
    # So ancestors(G, target) = things target depends on.
    # To find things that depend on target, we need predecessors transitively:
    # which is ancestors in the REVERSED graph, or equivalently: nodes that have
    # target as a descendant.
    # Let's use the correct approach:
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


def codegen_cascade_cost(G: nx.DiGraph, codegen_target: str, metrics_df: pd.DataFrame) -> int:
    """Total downstream rebuild cost triggered by a codegen step.

    Answers: "if this codegen changes, how much total build time does it cause?"
    This is equivalent to rebuild_cost but highlights the codegen-specific impact.
    """
    return rebuild_cost(G, codegen_target, metrics_df)


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
    file_metrics = pd.read_parquet  # placeholder — caller should pass file_df

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
            notes.append(
                f"Target has {gen_count} generated files — ensure they stay with consumers"
            )

    # Cross-partition edge count (would create new inter-target deps)
    cross_edges = len(file_groups) - 1  # minimum new edges
    notes.append(f"Split creates {len(file_groups)} new targets with ~{cross_edges} new dependency edges")

    return {
        "before": before,
        "partitions": partitions,
        "cross_partition_edges": cross_edges,
        "notes": notes,
    }
