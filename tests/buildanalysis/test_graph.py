"""Tests for buildanalysis.graph module (consolidated)."""

from pathlib import Path

import networkx as nx
import pandas as pd
import pytest

from buildanalysis.graph import (
    build_dependency_graph,
    build_include_graph,
    compute_centrality_metrics,
    compute_graph_summary,
    compute_layer_assignments,
    compute_transitive_deps,
    find_layer_violations,
)
from buildanalysis.types import BuildGraph

DATA_DIR = Path("data/processed")
HAS_DATA = DATA_DIR.exists() and (DATA_DIR / "target_metrics.parquet").exists()


# ---------------------------------------------------------------------------
# Tests: build_dependency_graph
# ---------------------------------------------------------------------------


class TestBuildDependencyGraph:
    def test_diamond(self, diamond_targets, diamond_edges):
        bg = build_dependency_graph(diamond_targets, diamond_edges)
        assert bg.n_targets == 4
        assert bg.n_edges == 4
        assert nx.is_directed_acyclic_graph(bg.graph)

    def test_edge_direction(self, diamond_targets, diamond_edges):
        bg = build_dependency_graph(diamond_targets, diamond_edges)
        # A depends on B, so (A, B) should be an edge
        assert bg.graph.has_edge("A", "B")
        # B does not depend on A
        assert not bg.graph.has_edge("B", "A")

    def test_node_attributes(self, diamond_targets, diamond_edges):
        bg = build_dependency_graph(diamond_targets, diamond_edges)
        assert bg.graph.nodes["A"]["target_type"] == "executable"
        assert bg.graph.nodes["D"]["target_type"] == "static_library"

    def test_edge_attributes(self, diamond_targets, diamond_edges):
        bg = build_dependency_graph(diamond_targets, diamond_edges)
        assert bg.graph.edges["A", "B"]["dependency_type"] == "link"

    def test_direct_only_filters(self, diamond_targets):
        edges = pd.DataFrame(
            {
                "source_target": ["A", "A", "A", "B"],
                "dest_target": ["B", "C", "D", "D"],
                "is_direct": [True, True, False, True],
                "dependency_type": ["link", "link", "link", "link"],
            }
        )
        bg = build_dependency_graph(diamond_targets, edges, direct_only=True)
        assert bg.n_edges == 3  # A->D filtered out
        assert not bg.graph.has_edge("A", "D")

    def test_cycle_raises(self):
        targets = pd.DataFrame(
            {
                "cmake_target": ["A", "B"],
                "target_type": ["executable", "static_library"],
            }
        )
        edges = pd.DataFrame(
            {
                "source_target": ["A", "B"],
                "dest_target": ["B", "A"],
                "is_direct": [True, True],
                "dependency_type": ["link", "link"],
            }
        )
        with pytest.raises(ValueError, match="cycles"):
            build_dependency_graph(targets, edges)

    def test_metadata_indexed_by_cmake_target(self, diamond_targets, diamond_edges):
        bg = build_dependency_graph(diamond_targets, diamond_edges)
        assert bg.target_metadata.index.name == "cmake_target"
        assert "A" in bg.target_metadata.index

    @pytest.mark.skipif(not HAS_DATA, reason="requires data/processed/")
    def test_real_data_is_dag(self):
        tm = pd.read_parquet("data/processed/target_metrics.parquet")
        el = pd.read_parquet("data/processed/edge_list.parquet")
        bg = build_dependency_graph(tm, el)
        assert nx.is_directed_acyclic_graph(bg.graph)
        assert bg.n_targets > 10


# ---------------------------------------------------------------------------
# Tests: build_include_graph
# ---------------------------------------------------------------------------


class TestBuildIncludeGraph:
    def test_basic(self):
        header_edges = pd.DataFrame(
            {
                "includer": ["a.h", "a.h", "b.h"],
                "included": ["b.h", "c.h", "c.h"],
                "is_system": [False, True, True],
                "source_file": ["x.cpp", "x.cpp", "x.cpp"],
                "depth": [1, 2, 1],
            }
        )
        g = build_include_graph(header_edges)
        assert g.has_edge("a.h", "b.h")
        assert g.has_edge("a.h", "c.h")
        assert g.has_edge("b.h", "c.h")
        assert g.number_of_nodes() == 3

    def test_deduplication_weight(self):
        header_edges = pd.DataFrame(
            {
                "includer": ["a.h", "a.h"],
                "included": ["b.h", "b.h"],
                "is_system": [False, False],
                "source_file": ["x.cpp", "y.cpp"],
                "depth": [1, 1],
            }
        )
        g = build_include_graph(header_edges)
        assert g.number_of_edges() == 1
        assert g.edges["a.h", "b.h"]["weight"] == 2

    def test_system_header_attribute(self):
        header_edges = pd.DataFrame(
            {
                "includer": ["a.h"],
                "included": ["sys.h"],
                "is_system": [True],
                "source_file": ["x.cpp"],
                "depth": [1],
            }
        )
        g = build_include_graph(header_edges)
        assert g.nodes["sys.h"]["is_system"] is True


# ---------------------------------------------------------------------------
# Tests: compute_transitive_deps
# ---------------------------------------------------------------------------


class TestTransitiveDeps:
    def test_diamond(self, diamond_graph):
        result = compute_transitive_deps(diamond_graph)
        a_row = result[result["cmake_target"] == "A"].iloc[0]
        # A depends on B, C, D (all 3)
        assert a_row["n_transitive_deps"] == 3
        d_row = result[result["cmake_target"] == "D"].iloc[0]
        # D has no dependencies
        assert d_row["n_transitive_deps"] == 0

    def test_chain(self, chain_graph):
        result = compute_transitive_deps(chain_graph)
        a_row = result[result["cmake_target"] == "A"].iloc[0]
        # A -> B -> C -> D -> E: A has 4 transitive deps
        assert a_row["n_transitive_deps"] == 4

    def test_direct_counts(self, diamond_graph):
        result = compute_transitive_deps(diamond_graph)
        a_row = result[result["cmake_target"] == "A"].iloc[0]
        assert a_row["n_direct_deps"] == 2  # B and C

    @pytest.mark.skipif(not HAS_DATA, reason="requires data/processed/")
    def test_real_data_matches_precomputed(self):
        tm = pd.read_parquet("data/processed/target_metrics.parquet")
        el = pd.read_parquet("data/processed/edge_list.parquet")
        bg = build_dependency_graph(tm, el)
        result = compute_transitive_deps(bg)

        merged = result.merge(
            tm[["cmake_target", "direct_dependency_count", "total_dependency_count"]],
            on="cmake_target",
        )
        # Direct deps should match
        assert (merged["n_direct_deps"] == merged["direct_dependency_count"]).all()


# ---------------------------------------------------------------------------
# Tests: compute_centrality_metrics
# ---------------------------------------------------------------------------


class TestCentralityMetrics:
    def test_diamond(self, diamond_graph):
        result = compute_centrality_metrics(diamond_graph)
        assert "betweenness" in result.columns
        assert "pagerank" in result.columns
        assert len(result) == 4

    def test_in_out_degree(self, diamond_graph):
        result = compute_centrality_metrics(diamond_graph)
        # D is depended on by B and C -> in_degree = 2
        assert result.loc["D", "in_degree"] == 2
        # A depends on B and C -> out_degree = 2
        assert result.loc["A", "out_degree"] == 2


# ---------------------------------------------------------------------------
# Tests: compute_layer_assignments
# ---------------------------------------------------------------------------


class TestLayers:
    def test_diamond_layers(self, diamond_graph):
        layers = compute_layer_assignments(diamond_graph)
        layer_map = layers.set_index("cmake_target")["layer"].to_dict()
        # D is a leaf: layer 0
        assert layer_map["D"] == 0
        # B and C depend on D: layer 1
        assert layer_map["B"] == 1
        assert layer_map["C"] == 1
        # A depends on B and C: layer 2
        assert layer_map["A"] == 2

    def test_chain_layers(self, chain_graph):
        layers = compute_layer_assignments(chain_graph)
        layer_map = layers.set_index("cmake_target")["layer"].to_dict()
        assert layer_map["E"] == 0
        assert layer_map["A"] == 4

    @pytest.mark.skipif(not HAS_DATA, reason="requires data/processed/")
    def test_real_data_layer_consistency(self):
        """Every edge must go from a higher layer to a lower layer."""
        tm = pd.read_parquet("data/processed/target_metrics.parquet")
        el = pd.read_parquet("data/processed/edge_list.parquet")
        bg = build_dependency_graph(tm, el)
        layers = compute_layer_assignments(bg)
        layer_map = layers.set_index("cmake_target")["layer"].to_dict()

        for src, dst in bg.graph.edges():
            assert layer_map[src] > layer_map[dst], f"{src}(layer {layer_map[src]}) -> {dst}(layer {layer_map[dst]})"


# ---------------------------------------------------------------------------
# Tests: find_layer_violations
# ---------------------------------------------------------------------------


class TestLayerViolations:
    def test_no_violations_in_clean_graph(self, diamond_graph):
        layers = compute_layer_assignments(diamond_graph)
        violations = find_layer_violations(diamond_graph, layers)
        assert len(violations) == 0

    def test_no_violations_in_chain(self, chain_graph):
        layers = compute_layer_assignments(chain_graph)
        violations = find_layer_violations(chain_graph, layers)
        assert len(violations) == 0

    def test_detects_lateral_violation(self):
        # B and C are at the same layer, B depends on C creates a lateral dependency
        # But with proper layering, B->C means B gets a higher layer.
        # Force a violation by manually constructing layers.
        g = nx.DiGraph()
        g.add_edges_from([("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")])
        meta = pd.DataFrame(
            {
                "cmake_target": ["A", "B", "C", "D"],
                "target_type": ["executable", "static_library", "static_library", "static_library"],
            }
        ).set_index("cmake_target")
        bg = BuildGraph(graph=g, target_metadata=meta)

        # Manually create incorrect layers to test detection
        layers = pd.DataFrame(
            {
                "cmake_target": ["A", "B", "C", "D"],
                "layer": [2, 1, 1, 0],
            }
        )
        # No violations: A(2)->B(1), A(2)->C(1), B(1)->D(0), C(1)->D(0) — all downward
        violations = find_layer_violations(bg, layers)
        assert len(violations) == 0

        # Now introduce a lateral violation
        bad_layers = pd.DataFrame(
            {
                "cmake_target": ["A", "B", "C", "D"],
                "layer": [2, 1, 1, 1],  # D at same layer as B and C
            }
        )
        violations = find_layer_violations(bg, bad_layers)
        assert len(violations) == 2  # B->D and C->D are lateral
        assert all(violations["violation_type"] == "lateral")

    def test_detects_upward_violation(self):
        g = nx.DiGraph()
        g.add_edges_from([("A", "B")])
        meta = pd.DataFrame(
            {
                "cmake_target": ["A", "B"],
                "target_type": ["executable", "static_library"],
            }
        ).set_index("cmake_target")
        bg = BuildGraph(graph=g, target_metadata=meta)

        # A depends on B, but B is at a higher layer — upward violation
        bad_layers = pd.DataFrame(
            {
                "cmake_target": ["A", "B"],
                "layer": [0, 1],
            }
        )
        violations = find_layer_violations(bg, bad_layers)
        assert len(violations) == 1
        assert violations.iloc[0]["violation_type"] == "upward"


# ---------------------------------------------------------------------------
# Tests: compute_graph_summary
# ---------------------------------------------------------------------------


class TestGraphSummary:
    def test_diamond_summary(self, diamond_graph):
        summary = compute_graph_summary(diamond_graph)
        assert summary["n_targets"] == 4
        assert summary["n_edges"] == 4
        assert summary["is_dag"] is True
        assert summary["max_depth"] == 2
        assert summary["n_executables"] == 1
        assert summary["n_libraries"] == 3

    def test_chain_summary(self, chain_graph):
        summary = compute_graph_summary(chain_graph)
        assert summary["n_targets"] == 5
        assert summary["n_edges"] == 4
        assert summary["max_depth"] == 4
        assert summary["max_out_degree"] == 1
        assert summary["max_in_degree"] == 1
