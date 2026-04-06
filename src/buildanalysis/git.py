"""Git history analysis: churn, co-change coupling, ownership, and team inference."""

from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd

from buildanalysis.types import AnalysisScope


def compute_file_churn(git_log: pd.DataFrame, scope: AnalysisScope | None = None) -> pd.DataFrame:
    """Aggregate per-file change frequency and volume metrics."""
    df = git_log.copy()
    if scope is not None:
        df = scope.filter_files(df)

    grouped = df.groupby("source_file")
    result = grouped.agg(
        n_commits=("commit_hash", "nunique"),
        n_authors=("contributor", "nunique"),
        total_lines_added=("lines_added", "sum"),
        total_lines_deleted=("lines_deleted", "sum"),
        first_commit=("timestamp", "min"),
        last_commit=("timestamp", "max"),
    ).reset_index()

    result["total_churn"] = result["total_lines_added"] + result["total_lines_deleted"]
    result["age_days"] = (result["last_commit"] - result["first_commit"]).dt.total_seconds() / 86400
    result["commits_per_month"] = np.where(
        result["age_days"] > 0,
        result["n_commits"] / (result["age_days"] / 30.44),
        result["n_commits"].astype(float),
    )

    return result.sort_values("n_commits", ascending=False).reset_index(drop=True)


def compute_cochange_matrix(
    git_log: pd.DataFrame,
    file_to_target: pd.Series | dict | None = None,
    level: str = "file",
    min_cochanges: int = 3,
    max_commit_size: int = 50,
) -> pd.DataFrame:
    """Compute co-change frequency between files or targets."""
    df = git_log.copy()

    if level == "target":
        if file_to_target is None:
            raise ValueError("file_to_target is required when level='target'")
        if isinstance(file_to_target, dict):
            file_to_target = pd.Series(file_to_target)
        df = df[df["source_file"].isin(file_to_target.index)]
        df["item"] = df["source_file"].map(file_to_target)
    else:
        df["item"] = df["source_file"]

    # Unique items per commit
    commit_items = df.groupby("commit_hash")["item"].apply(lambda x: frozenset(x.unique()))

    # Filter by max_commit_size
    commit_items = commit_items[commit_items.apply(len) <= max_commit_size]

    # Total commits per item (for PMI/Jaccard)
    total_commits = commit_items.shape[0]
    item_counts: dict[str, int] = {}
    pair_counts: dict[tuple[str, str], int] = {}

    for items in commit_items:
        for item in items:
            item_counts[item] = item_counts.get(item, 0) + 1
        for a, b in itertools.combinations(sorted(items), 2):
            pair_counts[(a, b)] = pair_counts.get((a, b), 0) + 1

    # Filter by min_cochanges
    rows = []
    for (a, b), count in pair_counts.items():
        if count >= min_cochanges:
            count_a = item_counts[a]
            count_b = item_counts[b]
            p_ab = count / total_commits
            p_a = count_a / total_commits
            p_b = count_b / total_commits
            pmi = math.log2(p_ab / (p_a * p_b)) if p_a > 0 and p_b > 0 and p_ab > 0 else 0.0
            jaccard = count / (count_a + count_b - count)
            rows.append(
                {
                    "item_a": a,
                    "item_b": b,
                    "cochange_count": count,
                    "pmi": pmi,
                    "jaccard": jaccard,
                }
            )

    if not rows:
        return pd.DataFrame(columns=["item_a", "item_b", "cochange_count", "pmi", "jaccard"])

    return pd.DataFrame(rows).sort_values("pmi", ascending=False).reset_index(drop=True)


def _gini(values: np.ndarray) -> float:
    """Compute Gini coefficient of an array of values."""
    values = np.sort(values).astype(float)
    n = len(values)
    if n == 0 or values.sum() == 0:
        return 0.0
    index = np.arange(1, n + 1)
    return float((2 * np.sum(index * values) - (n + 1) * np.sum(values)) / (n * np.sum(values)))


def compute_ownership_concentration(
    git_log: pd.DataFrame,
    file_to_target: pd.Series | dict,
    entity_col: str = "cmake_target",
) -> pd.DataFrame:
    """Compute ownership concentration per target using the Gini coefficient."""
    if isinstance(file_to_target, dict):
        file_to_target = pd.Series(file_to_target)

    df = git_log[git_log["source_file"].isin(file_to_target.index)].copy()
    df[entity_col] = df["source_file"].map(file_to_target)

    # Count commits per contributor per target
    commit_counts = df.groupby([entity_col, "contributor"])["commit_hash"].nunique().reset_index(name="commits")

    rows = []
    for target, group in commit_counts.groupby(entity_col):
        counts = group["commits"].values
        total = int(counts.sum())
        top_idx = counts.argmax()
        top_contributor = group.iloc[top_idx]["contributor"]
        top_share = float(counts[top_idx]) / total

        rows.append(
            {
                entity_col: target,
                "n_contributors": len(group),
                "gini": _gini(counts),
                "top_contributor": top_contributor,
                "top_contributor_share": top_share,
                "total_commits": total,
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                entity_col,
                "n_contributors",
                "gini",
                "top_contributor",
                "top_contributor_share",
                "total_commits",
            ]
        )

    return pd.DataFrame(rows).sort_values("gini", ascending=False).reset_index(drop=True)


def compute_file_to_target_map(file_metrics: pd.DataFrame) -> pd.Series:
    """Extract the file-to-target mapping from file_metrics."""
    deduped = file_metrics.drop_duplicates(subset="source_file", keep="first")
    return deduped.set_index("source_file")["cmake_target"]
