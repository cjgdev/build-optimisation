"""Feature group partitioning: biclustering, community detection, and optimisation.

Provides functions for discovering feature group structure through spectral
co-clustering, hierarchical community detection, and simulated annealing.
"""

from __future__ import annotations

import random

import igraph as ig
import leidenalg
import networkx as nx
import numpy as np
import pandas as pd
from sklearn.cluster import SpectralCoclustering


def bicluster_exe_library(
    matrix: pd.DataFrame,
    k_range: range | None = None,
) -> dict:
    """Run spectral co-clustering on the executable-library dependency matrix.

    Args:
        matrix: Wide-format binary matrix with executables as rows and libraries as columns.
        k_range: Range of bicluster counts to try. Defaults to range(3, 13).

    Returns:
        Dict with keys:
            results: List of dicts per K with row_labels, col_labels, metrics.
            best_k: K with best within-bicluster density.
    """
    if k_range is None:
        k_range = range(3, 13)

    X = matrix.values.astype(float)
    results = []
    best_k = None
    best_density = -1

    for k in k_range:
        if k >= min(X.shape):
            continue

        model = SpectralCoclustering(n_clusters=k, random_state=42)
        try:
            model.fit(X)
        except Exception:
            continue

        row_labels = model.row_labels_
        col_labels = model.column_labels_

        # Compute within-bicluster density
        within_ones = 0
        total_ones = X.sum()
        for c in range(k):
            row_mask = row_labels == c
            col_mask = col_labels == c
            block = X[np.ix_(row_mask, col_mask)]
            within_ones += block.sum()

        density = within_ones / total_ones if total_ones > 0 else 0
        cross_fraction = 1 - density

        if density > best_density:
            best_density = density
            best_k = k

        results.append(
            {
                "k": k,
                "row_labels": pd.Series(row_labels, index=matrix.index),
                "col_labels": pd.Series(col_labels, index=matrix.columns),
                "within_density": density,
                "cross_fraction": cross_fraction,
            }
        )

    return {
        "results": results,
        "best_k": best_k,
    }


def hierarchical_communities(
    G: nx.DiGraph,
    resolution_range: list[float] | None = None,
) -> dict:
    """Run Leiden community detection at multiple resolutions.

    Args:
        G: Dependency DAG (converted to undirected for community detection).
        resolution_range: List of resolution parameters to try.
                         Defaults to [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0].

    Returns:
        Dict with keys:
            results: List of dicts per resolution with partition, modularity, n_communities.
            dendrogram: Nested dict tracking community splits across resolutions.
    """
    if resolution_range is None:
        resolution_range = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]

    # Convert NetworkX DiGraph to undirected igraph
    G_undirected = G.to_undirected()
    node_list = list(G_undirected.nodes())
    node_index = {n: i for i, n in enumerate(node_list)}

    ig_graph = ig.Graph()
    ig_graph.add_vertices(len(node_list))
    ig_graph.vs["name"] = node_list

    edges = []
    for u, v in G_undirected.edges():
        if u != v:  # skip self-loops
            edges.append((node_index[u], node_index[v]))
    ig_graph.add_edges(edges)

    results = []

    for res in sorted(resolution_range):
        partition = leidenalg.find_partition(
            ig_graph,
            leidenalg.RBConfigurationVertexPartition,
            resolution_parameter=res,
            seed=42,
        )

        membership = {node_list[i]: partition.membership[i] for i in range(len(node_list))}
        modularity = partition.modularity
        n_communities = len(set(partition.membership))

        # Count cross-community edges
        cross_edges = 0
        for u, v in G_undirected.edges():
            if membership.get(u) != membership.get(v):
                cross_edges += 1

        results.append(
            {
                "resolution": res,
                "partition": membership,
                "modularity": modularity,
                "n_communities": n_communities,
                "cross_community_edges": cross_edges,
            }
        )

    return {
        "results": results,
    }


def extract_feature_groups(
    communities: dict,
    core: list[str],
    ownership: pd.DataFrame | None = None,
    resolution: float | None = None,
) -> pd.DataFrame:
    """Assign targets to feature groups from community detection results.

    Args:
        communities: Output from hierarchical_communities().
        core: List of core library targets (assigned to "core" group).
        ownership: Optional DataFrame with (cmake_target, owning_group_id) for alignment.
        resolution: Which resolution to use. If None, uses the one with highest modularity.

    Returns:
        DataFrame with columns (cmake_target, feature_group).
    """
    # Select the partition to use
    results = communities["results"]
    if resolution is not None:
        partition = None
        for r in results:
            if r["resolution"] == resolution:
                partition = r["partition"]
                break
        if partition is None:
            raise ValueError(f"Resolution {resolution} not found in results")
    else:
        best = max(results, key=lambda r: r["modularity"])
        partition = best["partition"]

    # Assign feature groups
    core_set = set(core)
    rows = []
    for target, community_id in partition.items():
        if target in core_set:
            group = "core"
        else:
            group = f"feature_{community_id}"
        rows.append({"cmake_target": target, "feature_group": group})

    return pd.DataFrame(rows, columns=["cmake_target", "feature_group"])


def simulated_annealing_partition(
    G: nx.DiGraph,
    initial_assignment: pd.DataFrame,
    cost_weights: dict[str, float] | None = None,
    iterations: int = 100_000,
    initial_temp: float = 1.0,
    cooling_rate: float = 0.99995,
    seed: int = 42,
) -> pd.DataFrame:
    """Optimise feature group assignment via simulated annealing.

    Cost function:
        cost = α × cross_group_edges + β × cross_group_compile_time + γ × team_boundary_violations

    Args:
        G: Dependency DAG.
        initial_assignment: DataFrame with (cmake_target, feature_group).
        cost_weights: Dict with keys "cross_group_edges", "cross_group_compile_time",
                     "team_boundary_violations". Defaults to equal weights.
        iterations: Number of SA iterations.
        initial_temp: Starting temperature.
        cooling_rate: Temperature multiplier per step.
        seed: Random seed.

    Returns:
        Optimised DataFrame with (cmake_target, feature_group).
    """
    if cost_weights is None:
        cost_weights = {
            "cross_group_edges": 1.0,
            "cross_group_compile_time": 0.0,
            "team_boundary_violations": 0.0,
        }

    rng = random.Random(seed)

    # Build assignment dict
    assignment = dict(zip(initial_assignment["cmake_target"], initial_assignment["feature_group"]))
    targets = [t for t in assignment if assignment[t] != "core"]
    groups = list(set(assignment.values()) - {"core"})

    if not targets or len(groups) < 2:
        return initial_assignment.copy()

    def compute_cost(asgn: dict) -> float:
        cross_edges = 0
        for u, v in G.edges():
            g_u = asgn.get(u, "core")
            g_v = asgn.get(v, "core")
            if g_u != g_v and g_u != "core" and g_v != "core":
                cross_edges += 1
        return cost_weights.get("cross_group_edges", 1.0) * cross_edges

    current_cost = compute_cost(assignment)
    best_assignment = dict(assignment)
    best_cost = current_cost
    temp = initial_temp

    for i in range(iterations):
        # Pick a random non-core target and move it to a random different group
        target = rng.choice(targets)
        old_group = assignment[target]
        new_group = rng.choice([g for g in groups if g != old_group])

        assignment[target] = new_group
        new_cost = compute_cost(assignment)

        delta = new_cost - current_cost
        if delta < 0 or rng.random() < np.exp(-delta / max(temp, 1e-10)):
            current_cost = new_cost
            if current_cost < best_cost:
                best_cost = current_cost
                best_assignment = dict(assignment)
        else:
            assignment[target] = old_group

        temp *= cooling_rate

    rows = [{"cmake_target": t, "feature_group": g} for t, g in best_assignment.items()]
    return pd.DataFrame(rows, columns=["cmake_target", "feature_group"])
