"""Tests for build_optimiser.partitioning."""

import networkx as nx
import pandas as pd

from build_optimiser.partitioning import (
    bicluster_exe_library,
    extract_feature_groups,
    hierarchical_communities,
    simulated_annealing_partition,
)


def make_bipartite_matrix():
    """Create a binary exe-library matrix with clear block structure."""
    # 4 executables, 6 libraries
    # Exes 1-2 use libs 1-3, exes 3-4 use libs 4-6
    data = {
        "lib_1": [1, 1, 0, 0],
        "lib_2": [1, 1, 0, 0],
        "lib_3": [1, 1, 0, 0],
        "lib_4": [0, 0, 1, 1],
        "lib_5": [0, 0, 1, 1],
        "lib_6": [0, 0, 1, 1],
    }
    return pd.DataFrame(data, index=["exe_1", "exe_2", "exe_3", "exe_4"])


def make_community_graph():
    """Create a graph with two clear communities connected by a bridge."""
    G = nx.DiGraph()
    # Community 1
    G.add_edge("a1", "a2")
    G.add_edge("a2", "a3")
    G.add_edge("a1", "a3")
    # Community 2
    G.add_edge("b1", "b2")
    G.add_edge("b2", "b3")
    G.add_edge("b1", "b3")
    # Bridge
    G.add_edge("a3", "b1")
    return G


class TestBiclusterExeLibrary:
    def test_returns_structure(self):
        matrix = make_bipartite_matrix()
        result = bicluster_exe_library(matrix, k_range=range(2, 4))
        assert "results" in result
        assert "best_k" in result
        assert len(result["results"]) > 0

    def test_two_clusters_optimal(self):
        matrix = make_bipartite_matrix()
        result = bicluster_exe_library(matrix, k_range=range(2, 5))
        # With perfect block structure, k=2 should have high within-density
        k2_result = [r for r in result["results"] if r["k"] == 2]
        assert len(k2_result) == 1
        assert k2_result[0]["within_density"] > 0.8

    def test_labels_assigned(self):
        matrix = make_bipartite_matrix()
        result = bicluster_exe_library(matrix, k_range=range(2, 3))
        r = result["results"][0]
        assert len(r["row_labels"]) == len(matrix)
        assert len(r["col_labels"]) == len(matrix.columns)


class TestHierarchicalCommunities:
    def test_returns_structure(self):
        G = make_community_graph()
        result = hierarchical_communities(G, resolution_range=[1.0])
        assert "results" in result
        assert len(result["results"]) == 1

    def test_detects_communities(self):
        G = make_community_graph()
        result = hierarchical_communities(G, resolution_range=[1.0])
        # At least two communities should be detected
        assert result["results"][0]["n_communities"] >= 2

    def test_resolution_sweep(self):
        G = make_community_graph()
        result = hierarchical_communities(G, resolution_range=[0.5, 1.0, 2.0])
        assert len(result["results"]) == 3
        # Higher resolution should give same or more communities
        n_communities = [r["n_communities"] for r in result["results"]]
        assert n_communities[-1] >= n_communities[0]


class TestExtractFeatureGroups:
    def test_core_assignment(self):
        G = make_community_graph()
        communities = hierarchical_communities(G, resolution_range=[1.0])
        fg = extract_feature_groups(communities, core=["a3", "b1"])
        core_targets = fg[fg["feature_group"] == "core"]["cmake_target"].tolist()
        assert "a3" in core_targets
        assert "b1" in core_targets

    def test_non_core_get_feature_group(self):
        G = make_community_graph()
        communities = hierarchical_communities(G, resolution_range=[1.0])
        fg = extract_feature_groups(communities, core=[])
        # All targets should have a feature group
        assert len(fg) == len(G.nodes())
        assert all(fg["feature_group"].str.startswith("feature_"))


class TestSimulatedAnnealingPartition:
    def test_returns_all_targets(self):
        G = make_community_graph()
        initial = pd.DataFrame({
            "cmake_target": list(G.nodes()),
            "feature_group": [
                "core" if n == "a3" else "group_a" if n.startswith("a") else "group_b"
                for n in G.nodes()
            ],
        })
        result = simulated_annealing_partition(G, initial, iterations=100)
        assert set(result["cmake_target"]) == set(initial["cmake_target"])

    def test_reduces_cross_group_edges(self):
        G = make_community_graph()
        # Start with a bad partition
        initial = pd.DataFrame({
            "cmake_target": list(G.nodes()),
            "feature_group": ["core", "group_a", "group_b", "group_a", "group_b", "group_a"],
        })

        initial_cost = 0
        assignment = dict(zip(initial["cmake_target"], initial["feature_group"]))
        for u, v in G.edges():
            g_u = assignment.get(u, "core")
            g_v = assignment.get(v, "core")
            if g_u != g_v and g_u != "core" and g_v != "core":
                initial_cost += 1

        result = simulated_annealing_partition(G, initial, iterations=1000)
        result_assignment = dict(zip(result["cmake_target"], result["feature_group"]))
        final_cost = 0
        for u, v in G.edges():
            g_u = result_assignment.get(u, "core")
            g_v = result_assignment.get(v, "core")
            if g_u != g_v and g_u != "core" and g_v != "core":
                final_cost += 1

        assert final_cost <= initial_cost

    def test_preserves_core(self):
        G = make_community_graph()
        initial = pd.DataFrame({
            "cmake_target": list(G.nodes()),
            "feature_group": ["core" if n in ("a3", "b1") else "group_a" for n in G.nodes()],
        })
        result = simulated_annealing_partition(G, initial, iterations=100)
        core = result[result["feature_group"] == "core"]["cmake_target"].tolist()
        assert "a3" in core
        assert "b1" in core
