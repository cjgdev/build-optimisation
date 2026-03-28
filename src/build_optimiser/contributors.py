"""Contributor analysis: clustering, ownership scoring, and bus factor computation.

Provides functions to identify contributor groups from commit patterns,
compute time-decayed code ownership, and assess knowledge risk via bus factor.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import dendrogram, fcluster, linkage
from scipy.spatial.distance import jensenshannon, pdist
from sklearn.decomposition import NMF
from sklearn.metrics import silhouette_score


def build_contributor_target_matrix(
    commits_df: pd.DataFrame,
    min_contributor_commits: int = 10,
    min_target_commits: int = 5,
) -> pd.DataFrame:
    """Build a contributor-target commit count matrix.

    Args:
        commits_df: DataFrame with columns (contributor, cmake_target, commit_count).
        min_contributor_commits: Exclude contributors with fewer total commits.
        min_target_commits: Exclude targets with fewer total commits.

    Returns:
        DataFrame with contributors as rows and targets as columns, values are commit counts.
    """
    # Filter contributors by total commit count
    contributor_totals = commits_df.groupby("contributor")["commit_count"].sum()
    active_contributors = contributor_totals[contributor_totals >= min_contributor_commits].index

    # Filter targets by total commit count
    target_totals = commits_df.groupby("cmake_target")["commit_count"].sum()
    active_targets = target_totals[target_totals >= min_target_commits].index

    filtered = commits_df[
        commits_df["contributor"].isin(active_contributors) & commits_df["cmake_target"].isin(active_targets)
    ]

    matrix = filtered.pivot_table(
        index="contributor",
        columns="cmake_target",
        values="commit_count",
        aggfunc="sum",
        fill_value=0,
    )
    return matrix


def normalise_to_distributions(matrix: pd.DataFrame) -> pd.DataFrame:
    """Normalise each row to sum to 1 (probability distribution over targets).

    Rows that sum to zero are left as zero vectors.
    """
    row_sums = matrix.sum(axis=1)
    row_sums = row_sums.replace(0, np.nan)
    return matrix.div(row_sums, axis=0).fillna(0)


def cluster_contributors_hierarchical(
    matrix: pd.DataFrame,
    metric: str = "jensenshannon",
    cut_levels: list[int] | None = None,
) -> dict:
    """Cluster contributors using hierarchical clustering with Ward linkage.

    Args:
        matrix: Contributor-target matrix (raw counts, will be normalised internally).
        metric: Distance metric. Default "jensenshannon" for probability distributions.
        cut_levels: Number of clusters to cut at. Defaults to [3, 5, 7, 10].

    Returns:
        Dict with keys:
            linkage_matrix: The scipy linkage matrix.
            dendrogram_data: Data for plotting the dendrogram.
            assignments: Dict mapping cut_level -> DataFrame(contributor, cluster_id).
    """
    if cut_levels is None:
        cut_levels = [3, 5, 7, 10]

    normed = normalise_to_distributions(matrix)

    # Compute pairwise distances
    if metric == "jensenshannon":
        # Add small epsilon to avoid zero vectors
        eps = 1e-10
        normed_safe = normed + eps
        normed_safe = normed_safe.div(normed_safe.sum(axis=1), axis=0)
        dist_vector = pdist(normed_safe.values, metric=jensenshannon)
    else:
        dist_vector = pdist(normed.values, metric=metric)

    # Replace any NaN distances with max distance
    dist_vector = np.nan_to_num(dist_vector, nan=1.0)

    Z = linkage(dist_vector, method="ward")
    dendro = dendrogram(Z, labels=list(matrix.index), no_plot=True)

    assignments = {}
    for k in cut_levels:
        if k > len(matrix):
            continue
        labels = fcluster(Z, t=k, criterion="maxclust")
        assignments[k] = pd.DataFrame({
            "contributor": matrix.index,
            "cluster_id": labels,
        })

    return {
        "linkage_matrix": Z,
        "dendrogram_data": dendro,
        "assignments": assignments,
    }


def cluster_contributors_nmf(
    matrix: pd.DataFrame,
    k_range: range | None = None,
) -> dict:
    """Cluster contributors using Non-negative Matrix Factorisation.

    Args:
        matrix: Contributor-target matrix (raw counts, non-negative).
        k_range: Range of K values to try. Defaults to range(3, 16).

    Returns:
        Dict with keys:
            results: List of dicts per K with W, H, reconstruction_error, silhouette_score.
            best_k: K with best silhouette score.
    """
    if k_range is None:
        k_range = range(3, 16)

    # Ensure non-negative
    X = matrix.values.astype(float)
    X = np.maximum(X, 0)

    results = []
    best_k = None
    best_silhouette = -1

    for k in k_range:
        if k >= len(matrix) or k >= matrix.shape[1]:
            continue

        model = NMF(n_components=k, init="nndsvda", max_iter=500, random_state=42)
        W = model.fit_transform(X)
        H = model.components_
        error = model.reconstruction_err_

        # Assign each contributor to their dominant component
        labels = np.argmax(W, axis=1)

        # Compute silhouette score if we have at least 2 clusters with members
        n_unique = len(set(labels))
        if n_unique >= 2 and n_unique < len(matrix):
            sil = silhouette_score(X, labels)
        else:
            sil = -1

        if sil > best_silhouette:
            best_silhouette = sil
            best_k = k

        results.append({
            "k": k,
            "W": pd.DataFrame(W, index=matrix.index, columns=[f"group_{i}" for i in range(k)]),
            "H": pd.DataFrame(H, index=[f"group_{i}" for i in range(k)], columns=matrix.columns),
            "reconstruction_error": error,
            "silhouette_score": sil,
            "labels": labels,
        })

    return {
        "results": results,
        "best_k": best_k,
    }


def compute_ownership(
    commits_df: pd.DataFrame,
    groups_df: pd.DataFrame,
    half_life_days: int = 90,
    reference_date: str | None = None,
) -> pd.DataFrame:
    """Compute time-decayed ownership scores per target per contributor group.

    Args:
        commits_df: DataFrame with (contributor, cmake_target, commit_count) and
                    optionally commit_date for time decay. If commit_date is not
                    present, uses commit_count without time decay.
        groups_df: DataFrame with (contributor, group_id) mapping.
        half_life_days: Exponential decay half-life in days.
        reference_date: Reference date for age computation (ISO format).
                       Defaults to max date in the data.

    Returns:
        DataFrame with columns (cmake_target, group_id, ownership_score, ownership_normalised).
    """
    lam = np.log(2) / half_life_days

    # Join contributors to groups
    merged = commits_df.merge(groups_df[["contributor", "group_id"]], on="contributor", how="inner")

    if "commit_date" in merged.columns and not merged["commit_date"].isna().all():
        merged["commit_date"] = pd.to_datetime(merged["commit_date"], utc=True)
        if reference_date is None:
            ref = merged["commit_date"].max()
        else:
            ref = pd.Timestamp(reference_date, tz="UTC")
        merged["age_days"] = (ref - merged["commit_date"]).dt.total_seconds() / 86400
        merged["weight"] = np.exp(-lam * merged["age_days"]) * merged["commit_count"]
    else:
        merged["weight"] = merged["commit_count"].astype(float)

    # Aggregate per target per group
    scores = merged.groupby(["cmake_target", "group_id"], as_index=False)["weight"].sum()
    scores.rename(columns={"weight": "ownership_score"}, inplace=True)

    # Normalise per target
    target_totals = scores.groupby("cmake_target")["ownership_score"].transform("sum")
    scores["ownership_normalised"] = scores["ownership_score"] / target_totals.replace(0, np.nan)
    scores["ownership_normalised"] = scores["ownership_normalised"].fillna(0)

    return scores


def compute_bus_factor(
    detail_df: pd.DataFrame,
    groups_df: pd.DataFrame,
    recent_months: int = 3,
) -> pd.DataFrame:
    """Compute active contributor count per target per group.

    Args:
        detail_df: DataFrame with per-commit detail rows containing
                   (author_email/contributor, source_file, commit_date, cmake_target).
        groups_df: DataFrame with (contributor, group_id) mapping.
        recent_months: Only count contributors active within this many months.

    Returns:
        DataFrame with columns (cmake_target, group_id, bus_factor).
    """
    df = detail_df.copy()

    # Determine contributor column
    contrib_col = "contributor" if "contributor" in df.columns else "author_email"

    if "commit_date" in df.columns:
        df["commit_date"] = pd.to_datetime(df["commit_date"], utc=True)
        cutoff = df["commit_date"].max() - pd.DateOffset(months=recent_months)
        df = df[df["commit_date"] >= cutoff]

    # Map contributors to groups
    df = df.merge(groups_df[["contributor", "group_id"]], left_on=contrib_col, right_on="contributor", how="inner")

    if "cmake_target" not in df.columns:
        return pd.DataFrame(columns=["cmake_target", "group_id", "bus_factor"])

    # Count distinct active contributors per target per group
    bus = (
        df.groupby(["cmake_target", "group_id"])[contrib_col]
        .nunique()
        .reset_index()
        .rename(columns={contrib_col: "bus_factor"})
    )

    return bus
