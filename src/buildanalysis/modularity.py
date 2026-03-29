"""Community detection and feature clustering for build dependency graphs."""

from __future__ import annotations

import json
from statistics import median

import networkx as nx
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.cluster import SpectralClustering
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

from buildanalysis.types import BuildGraph


def detect_communities_louvain(bg: BuildGraph, resolution: float = 1.0) -> pd.DataFrame:
    """Detect communities using the Louvain method on the undirected projection."""
    undirected = bg.graph.to_undirected()
    communities = nx.community.louvain_communities(undirected, resolution=resolution, seed=42)

    rows = []
    for idx, community in enumerate(communities):
        for target in community:
            rows.append({"cmake_target": target, "community": idx})

    return pd.DataFrame(rows)


def detect_communities_spectral(bg: BuildGraph, n_clusters: int | None = None) -> pd.DataFrame:
    """Detect communities using spectral clustering on the graph Laplacian."""
    from scipy.sparse import csgraph
    from scipy.sparse.linalg import eigsh

    undirected = bg.graph.to_undirected()
    nodes = list(undirected.nodes())
    n = len(nodes)
    adj_matrix = nx.to_numpy_array(undirected, nodelist=nodes)

    if n_clusters is None:
        max_k = min(10, n - 1)
        laplacian = csgraph.laplacian(adj_matrix, normed=True)
        n_components = min(max_k + 1, n - 1)
        eigenvalues = eigsh(laplacian, k=n_components, which="SM", return_eigenvectors=False)
        eigenvalues = np.sort(eigenvalues)
        gaps = np.diff(eigenvalues[1:])
        n_clusters = int(np.argmax(gaps)) + 2

    n_clusters = min(n_clusters, n)

    clustering = SpectralClustering(
        n_clusters=n_clusters,
        affinity="precomputed",
        random_state=42,
    )
    # Use adjacency matrix as precomputed affinity
    labels = clustering.fit_predict(adj_matrix)

    return pd.DataFrame({
        "cmake_target": nodes,
        "community": labels,
    })


def hierarchical_clustering(bg: BuildGraph, method: str = "ward") -> tuple[np.ndarray, list[str]]:
    """Produce a dendrogram via agglomerative clustering using Jaccard distance on neighbourhoods."""
    undirected = bg.graph.to_undirected()
    nodes = list(undirected.nodes())
    n = len(nodes)

    # Compute neighbourhoods (neighbours + self)
    neighbourhoods = []
    for node in nodes:
        neighbourhood = set(undirected.neighbors(node))
        neighbourhood.add(node)
        neighbourhoods.append(neighbourhood)

    # Compute pairwise Jaccard distance
    dist_matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            intersection = len(neighbourhoods[i] & neighbourhoods[j])
            union = len(neighbourhoods[i] | neighbourhoods[j])
            jaccard_dist = 1.0 - (intersection / union) if union > 0 else 0.0
            dist_matrix[i, j] = jaccard_dist
            dist_matrix[j, i] = jaccard_dist

    condensed = squareform(dist_matrix)
    Z = linkage(condensed, method=method)

    return Z, nodes


def cut_dendrogram(Z: np.ndarray, nodes: list[str], n_clusters: int) -> pd.DataFrame:
    """Cut the dendrogram at a level producing n_clusters groups."""
    labels = fcluster(Z, t=n_clusters, criterion="maxclust")
    # Convert to 0-indexed
    labels = labels - 1

    return pd.DataFrame({
        "cmake_target": nodes,
        "community": labels,
    })


def compute_modularity_score(bg: BuildGraph, communities: pd.DataFrame) -> dict:
    """Compute quality metrics for a given community assignment."""
    undirected = bg.graph.to_undirected()

    # Build community sets for nx.community.modularity
    community_map = communities.set_index("cmake_target")["community"].to_dict()
    community_ids = set(community_map.values())
    community_sets = []
    for cid in sorted(community_ids):
        community_sets.append({t for t, c in community_map.items() if c == cid})

    modularity = nx.community.modularity(undirected, community_sets)

    # Inter-community edge fraction
    total_edges = undirected.number_of_edges()
    inter_edges = 0
    for u, v in undirected.edges():
        if community_map.get(u) != community_map.get(v):
            inter_edges += 1
    inter_frac = inter_edges / total_edges if total_edges > 0 else 0.0

    # Average self-containment
    self_containments = []
    for comm_nodes in community_sets:
        internal = 0
        total = 0
        for node in comm_nodes:
            for neighbor in undirected.neighbors(node):
                total += 1
                if neighbor in comm_nodes:
                    internal += 1
        sc = internal / total if total > 0 else 1.0
        self_containments.append(sc)

    sizes = [len(s) for s in community_sets]

    return {
        "graph_modularity": modularity,
        "inter_community_edge_fraction": inter_frac,
        "avg_self_containment": sum(self_containments) / len(self_containments) if self_containments else 0.0,
        "n_communities": len(community_sets),
        "min_community_size": min(sizes) if sizes else 0,
        "max_community_size": max(sizes) if sizes else 0,
        "median_community_size": float(median(sizes)) if sizes else 0.0,
    }


def build_feature_configurations(
    bg: BuildGraph,
    communities: pd.DataFrame,
    timing: pd.DataFrame | None = None,
    time_col: str = "total_build_time_ms",
) -> pd.DataFrame:
    """For each community, compute the full set of targets needed to build it."""
    community_map = communities.set_index("cmake_target")["community"].to_dict()
    community_ids = sorted(set(community_map.values()))
    total_targets = bg.n_targets

    # Build timing lookup
    timing_map = {}
    if timing is not None:
        timing_map = timing.set_index("cmake_target")[time_col].to_dict()
        total_build_time = sum(timing_map.values())

    # Track which deps are used by multiple features
    dep_usage: dict[str, int] = {}

    rows = []
    for cid in community_ids:
        own = {t for t, c in community_map.items() if c == cid}

        # Compute transitive dependencies for all own targets
        all_deps: set[str] = set()
        for target in own:
            if target in bg.graph:
                all_deps |= nx.descendants(bg.graph, target)

        external_deps = all_deps - own
        total_build_set = len(own) + len(external_deps)

        for dep in external_deps:
            dep_usage[dep] = dep_usage.get(dep, 0) + 1

        row = {
            "feature_id": cid,
            "own_targets": len(own),
            "transitive_deps": len(external_deps),
            "total_build_set": total_build_set,
            "build_fraction": total_build_set / total_targets if total_targets > 0 else 0.0,
            "own_target_list": json.dumps(sorted(own)),
            "_external_deps": external_deps,
        }

        if timing is not None:
            build_set = own | external_deps
            est_time = sum(timing_map.get(t, 0) for t in build_set)
            row["estimated_build_time_ms"] = est_time
            row["estimated_build_fraction_time"] = est_time / total_build_time if total_build_time > 0 else 0.0
        else:
            row["estimated_build_time_ms"] = None
            row["estimated_build_fraction_time"] = None

        rows.append(row)

    # Identify shared deps (used by multiple features)
    shared_deps = {dep for dep, count in dep_usage.items() if count > 1}
    for row in rows:
        external_deps = row.pop("_external_deps")
        row["shared_deps_list"] = json.dumps(sorted(external_deps & shared_deps))

    result = pd.DataFrame(rows)
    return result.sort_values("total_build_set", ascending=True).reset_index(drop=True)


def compare_community_methods(bg: BuildGraph, methods_results: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compare multiple community detection results side by side."""
    rows = []
    for method_name, communities in methods_results.items():
        score = compute_modularity_score(bg, communities)
        sizes = communities.groupby("community").size()
        rows.append({
            "method": method_name,
            "n_communities": score["n_communities"],
            "modularity": score["graph_modularity"],
            "inter_community_edges": score["inter_community_edge_fraction"],
            "avg_self_containment": score["avg_self_containment"],
            "min_size": int(sizes.min()),
            "max_size": int(sizes.max()),
        })

    result = pd.DataFrame(rows)
    return result.sort_values("modularity", ascending=False).reset_index(drop=True)


def compute_conway_alignment(
    structural_communities: pd.DataFrame,
    behavioral_communities: pd.DataFrame,
) -> dict:
    """Measure alignment between structural and behavioral community assignments."""
    merged = structural_communities.merge(
        behavioral_communities,
        on="cmake_target",
        suffixes=("_struct", "_behav"),
    )

    ari = adjusted_rand_score(merged["community_struct"], merged["community_behav"])
    nmi = normalized_mutual_info_score(merged["community_struct"], merged["community_behav"])

    return {
        "adjusted_rand_index": ari,
        "normalized_mutual_info": nmi,
        "n_targets_compared": len(merged),
        "n_mismatched": None,  # Non-trivial without Hungarian algorithm; use ARI/NMI instead
    }
