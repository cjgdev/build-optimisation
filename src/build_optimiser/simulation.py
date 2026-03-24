"""Rebuild cost and simulation logic for build structure changes."""

from __future__ import annotations

from typing import Any

import networkx as nx
import numpy as np
import pandas as pd


def rebuild_cost(
    G: nx.DiGraph,
    target: str,
    metrics_df: pd.DataFrame,
    cost_column: str = "compile_time_sum_ms",
    target_column: str = "cmake_target",
) -> int:
    """Total transitive rebuild cost if a target changes.

    This is the sum of compile times of the target itself plus all
    transitive dependants (everything that must rebuild).
    """
    dependants = nx.ancestors(G, target)  # targets that depend on this one
    affected = dependants | {target}

    costs = metrics_df[metrics_df[target_column].isin(affected)]
    return int(costs[cost_column].sum())


def expected_daily_cost(
    G: nx.DiGraph,
    target: str,
    metrics_df: pd.DataFrame,
    git_df: pd.DataFrame,
    cost_column: str = "compile_time_sum_ms",
    target_column: str = "cmake_target",
    commit_column: str = "git_commit_count_total",
) -> float:
    """Rebuild cost weighted by change probability.

    change_probability = target_commits / total_commits
    expected_cost = change_probability * rebuild_cost
    """
    total_commits = git_df[commit_column].sum() if commit_column in git_df.columns else 1
    if total_commits == 0:
        return 0.0

    row = metrics_df[metrics_df[target_column] == target]
    if row.empty:
        return 0.0

    target_commits = row[commit_column].iloc[0]
    change_prob = target_commits / total_commits
    cost = rebuild_cost(G, target, metrics_df, cost_column, target_column)
    return change_prob * cost


def simulate_merge(
    G: nx.DiGraph,
    targets: list[str],
    metrics_df: pd.DataFrame,
    cost_column: str = "compile_time_sum_ms",
    target_column: str = "cmake_target",
    commit_column: str = "git_commit_count_total",
) -> dict[str, Any]:
    """Simulate merging targets and return before/after build cost metrics.

    The merged target inherits all dependencies and dependants of the
    constituent targets. Its compile time is the sum of the parts.
    Its change probability is the union (max of individual probabilities,
    or sum of commit counts).
    """
    merged_name = "+".join(sorted(targets))

    # Before metrics
    before_costs = {}
    for t in targets:
        if t in G:
            before_costs[t] = rebuild_cost(G, t, metrics_df, cost_column, target_column)

    # Build new graph
    G_new = G.copy()

    # Collect all predecessors and successors of merged targets
    all_preds: set[str] = set()
    all_succs: set[str] = set()
    for t in targets:
        if t in G_new:
            all_preds.update(G_new.predecessors(t))
            all_succs.update(G_new.successors(t))

    # Remove internal edges and the original nodes
    all_preds -= set(targets)
    all_succs -= set(targets)

    for t in targets:
        if t in G_new:
            G_new.remove_node(t)

    # Add merged node
    G_new.add_node(merged_name)
    for pred in all_preds:
        if pred in G_new:
            G_new.add_edge(pred, merged_name)
    for succ in all_succs:
        if succ in G_new:
            G_new.add_edge(merged_name, succ)

    # Build merged metrics row
    merged_rows = metrics_df[metrics_df[target_column].isin(targets)]
    merged_metrics = metrics_df.copy()
    merged_metrics = merged_metrics[~merged_metrics[target_column].isin(targets)]

    new_row = {target_column: merged_name}
    for col in merged_metrics.columns:
        if col == target_column:
            continue
        if col in merged_rows.columns and pd.api.types.is_numeric_dtype(merged_rows[col]):
            new_row[col] = merged_rows[col].sum()

    new_row_df = pd.DataFrame([new_row])
    merged_metrics = pd.concat([merged_metrics, new_row_df], ignore_index=True)

    after_cost = rebuild_cost(G_new, merged_name, merged_metrics, cost_column, target_column)

    return {
        "merged_target": merged_name,
        "before_individual_costs": before_costs,
        "before_total_cost": sum(before_costs.values()),
        "after_cost": after_cost,
        "delta": after_cost - sum(before_costs.values()),
        "new_graph": G_new,
        "new_metrics": merged_metrics,
    }


def simulate_split(
    G: nx.DiGraph,
    target: str,
    file_groups: list[list[str]],
    metrics_df: pd.DataFrame,
    file_metrics_df: pd.DataFrame,
    cost_column: str = "compile_time_sum_ms",
    target_column: str = "cmake_target",
) -> dict[str, Any]:
    """Simulate splitting a target and return before/after metrics.

    Args:
        G: Dependency graph.
        target: Target to split.
        file_groups: List of file groups, each group becomes a new target.
        metrics_df: Target-level metrics.
        file_metrics_df: File-level metrics with 'source_file' and 'cmake_target' columns.
        cost_column: Column for compile cost.
        target_column: Column for target name.

    Returns:
        Dict with before/after comparison.
    """
    before_cost = rebuild_cost(G, target, metrics_df, cost_column, target_column)

    # Create new target names
    new_targets = [f"{target}_part{i}" for i in range(len(file_groups))]

    # Build new graph
    G_new = G.copy()
    preds = list(G_new.predecessors(target))
    succs = list(G_new.successors(target))
    G_new.remove_node(target)

    for new_t in new_targets:
        G_new.add_node(new_t)
        # All parts depend on same dependencies
        for succ in succs:
            if succ in G_new:
                G_new.add_edge(new_t, succ)
        # All dependants depend on all parts (conservative)
        for pred in preds:
            if pred in G_new:
                G_new.add_edge(pred, new_t)

    # Build new metrics
    target_files = file_metrics_df[file_metrics_df[target_column] == target]
    new_rows = []
    for i, group in enumerate(file_groups):
        group_files = target_files[target_files["source_file"].isin(group)]
        row = {target_column: new_targets[i]}
        if "compile_time_ms" in group_files.columns:
            row[cost_column] = int(group_files["compile_time_ms"].sum())
        new_rows.append(row)

    new_metrics = metrics_df[metrics_df[target_column] != target].copy()
    new_rows_df = pd.DataFrame(new_rows)
    # Fill missing columns with 0
    for col in new_metrics.columns:
        if col not in new_rows_df.columns and col != target_column:
            new_rows_df[col] = 0
    new_metrics = pd.concat([new_metrics, new_rows_df], ignore_index=True)

    after_costs = {}
    for new_t in new_targets:
        if new_t in G_new:
            after_costs[new_t] = rebuild_cost(G_new, new_t, new_metrics, cost_column, target_column)

    return {
        "original_target": target,
        "new_targets": new_targets,
        "before_cost": before_cost,
        "after_costs": after_costs,
        "after_total_cost": sum(after_costs.values()),
        "delta": sum(after_costs.values()) - before_cost,
        "new_graph": G_new,
        "new_metrics": new_metrics,
    }


def monte_carlo_rebuild_cost(
    G: nx.DiGraph,
    metrics_df: pd.DataFrame,
    n_simulations: int = 1000,
    cost_column: str = "compile_time_sum_ms",
    target_column: str = "cmake_target",
    commit_column: str = "git_commit_count_total",
    seed: int | None = None,
) -> dict[str, Any]:
    """Monte Carlo simulation of daily rebuild costs.

    For each simulation, randomly select which targets change based on
    empirical change probabilities, then compute total rebuild cost.

    Returns:
        Dict with mean, median, std, p95, and per-target breakdown.
    """
    rng = np.random.default_rng(seed)

    # Compute per-target change probabilities
    total_commits = metrics_df[commit_column].sum()
    if total_commits == 0:
        return {"mean": 0, "median": 0, "std": 0, "p95": 0}

    targets = metrics_df[target_column].tolist()
    probs = (metrics_df[commit_column] / total_commits).tolist()

    daily_costs = []
    for _ in range(n_simulations):
        # Each target changes independently with its probability
        changed = rng.random(len(targets)) < np.array(probs)
        total_cost = 0
        affected: set[str] = set()
        for i, t in enumerate(targets):
            if changed[i] and t in G:
                affected.add(t)
                affected.update(nx.ancestors(G, t))

        cost_map = metrics_df.set_index(target_column)[cost_column]
        for t in affected:
            if t in cost_map.index:
                total_cost += cost_map[t]

        daily_costs.append(total_cost)

    daily_costs_arr = np.array(daily_costs)
    return {
        "mean": float(daily_costs_arr.mean()),
        "median": float(np.median(daily_costs_arr)),
        "std": float(daily_costs_arr.std()),
        "p95": float(np.percentile(daily_costs_arr, 95)),
        "raw": daily_costs_arr,
    }
