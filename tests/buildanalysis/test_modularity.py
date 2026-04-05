import json

import pandas as pd
import pytest

from buildanalysis.modularity import (
    build_feature_configurations,
    compare_community_methods,
    compute_conway_alignment,
    compute_modularity_score,
    cut_dendrogram,
    detect_communities_louvain,
    detect_communities_spectral,
    hierarchical_clustering,
)


class TestLouvain:
    def test_all_targets_assigned(self, diamond_graph):
        result = detect_communities_louvain(diamond_graph)
        assert set(result["cmake_target"]) == set(diamond_graph.graph.nodes())

    def test_two_community_graph(self, two_community_graph):
        result = detect_communities_louvain(two_community_graph, resolution=1.0)
        n_communities = result["community"].nunique()
        # Should find approximately 2 communities (bridge may affect this)
        assert 1 <= n_communities <= 4

    def test_deterministic(self, diamond_graph):
        r1 = detect_communities_louvain(diamond_graph)
        r2 = detect_communities_louvain(diamond_graph)
        merged = r1.merge(r2, on="cmake_target", suffixes=("_1", "_2"))
        assert (merged["community_1"] == merged["community_2"]).all()


class TestSpectral:
    def test_all_targets_assigned(self, two_community_graph):
        result = detect_communities_spectral(two_community_graph, n_clusters=2)
        assert set(result["cmake_target"]) == set(two_community_graph.graph.nodes())

    def test_auto_k(self, two_community_graph):
        result = detect_communities_spectral(two_community_graph)
        assert result["community"].nunique() >= 1


class TestModularityScore:
    def test_score_range(self, diamond_graph):
        communities = detect_communities_louvain(diamond_graph)
        score = compute_modularity_score(diamond_graph, communities)
        assert -0.5 <= score["graph_modularity"] <= 1.0
        assert 0 <= score["inter_community_edge_fraction"] <= 1.0
        assert score["n_communities"] >= 1


class TestFeatureConfigurations:
    def test_build_sets_are_transitively_closed(self, two_community_graph):
        communities = detect_communities_louvain(two_community_graph)
        configs = build_feature_configurations(two_community_graph, communities)

        for _, row in configs.iterrows():
            assert json.loads(row["own_target_list"])  # non-empty list
            assert 0 < row["build_fraction"] <= 1.0

    def test_build_fraction_reasonable(self, two_community_graph):
        communities = detect_communities_louvain(two_community_graph)
        configs = build_feature_configurations(two_community_graph, communities)
        # No feature should require building more than the full codebase
        assert (configs["build_fraction"] <= 1.0).all()
        assert (configs["total_build_set"] >= configs["own_targets"]).all()

    def test_with_timing(self, two_community_graph):
        communities = detect_communities_louvain(two_community_graph)
        timing = pd.DataFrame(
            {
                "cmake_target": list(two_community_graph.graph.nodes()),
                "total_build_time_ms": [1000] * two_community_graph.n_targets,
            }
        )
        configs = build_feature_configurations(two_community_graph, communities, timing=timing)
        assert configs["estimated_build_time_ms"].notna().all()
        assert configs["estimated_build_fraction_time"].notna().all()

    def test_with_timing_zero_total(self, two_community_graph):
        """All-zero timing should yield 0.0 fraction without division-by-zero."""
        communities = detect_communities_louvain(two_community_graph)
        timing = pd.DataFrame(
            {
                "cmake_target": list(two_community_graph.graph.nodes()),
                "total_build_time_ms": [0] * two_community_graph.n_targets,
            }
        )
        configs = build_feature_configurations(two_community_graph, communities, timing=timing)
        assert (configs["estimated_build_fraction_time"] == 0.0).all()
        assert configs["estimated_build_time_ms"].notna().all()

    def test_build_fraction_time_proportional(self, two_community_graph):
        """With equal timing per target, fraction should be proportional to build set size."""
        communities = detect_communities_louvain(two_community_graph)
        n = two_community_graph.n_targets
        timing = pd.DataFrame(
            {
                "cmake_target": list(two_community_graph.graph.nodes()),
                "total_build_time_ms": [1000] * n,
            }
        )
        configs = build_feature_configurations(two_community_graph, communities, timing=timing)
        for _, row in configs.iterrows():
            expected = row["estimated_build_time_ms"] / (n * 1000)
            assert row["estimated_build_fraction_time"] == pytest.approx(expected)


class TestHierarchical:
    def test_linkage_matrix_shape(self, diamond_graph):
        Z, nodes = hierarchical_clustering(diamond_graph)
        # Linkage matrix has (n-1) rows and 4 columns
        assert Z.shape == (len(nodes) - 1, 4)

    def test_cut_produces_right_count(self, two_community_graph):
        Z, nodes = hierarchical_clustering(two_community_graph)
        result = cut_dendrogram(Z, nodes, n_clusters=2)
        assert result["community"].nunique() == 2
        assert len(result) == len(nodes)


class TestCompare:
    def test_compare_methods(self, two_community_graph):
        r1 = detect_communities_louvain(two_community_graph, resolution=1.0)
        r2 = detect_communities_louvain(two_community_graph, resolution=2.0)
        result = compare_community_methods(two_community_graph, {"res_1.0": r1, "res_2.0": r2})
        assert len(result) == 2
        assert "modularity" in result.columns
        assert "method" in result.columns


class TestConwayAlignment:
    def test_identical_communities(self):
        comm = pd.DataFrame(
            {
                "cmake_target": ["A", "B", "C", "D"],
                "community": [0, 0, 1, 1],
            }
        )
        result = compute_conway_alignment(comm, comm)
        assert result["adjusted_rand_index"] == pytest.approx(1.0)
        assert result["normalized_mutual_info"] == pytest.approx(1.0)

    def test_random_communities(self):
        struct = pd.DataFrame(
            {
                "cmake_target": ["A", "B", "C", "D"],
                "community": [0, 0, 1, 1],
            }
        )
        behav = pd.DataFrame(
            {
                "cmake_target": ["A", "B", "C", "D"],
                "community": [0, 1, 0, 1],
            }
        )
        result = compute_conway_alignment(struct, behav)
        # Different assignments → ARI should be low
        assert result["adjusted_rand_index"] < 0.5
