"""Tests for buildanalysis.export module."""

import tempfile
from pathlib import Path

import networkx as nx
import pandas as pd
import pytest

from buildanalysis.export import (
    export_cochange_graph,
    export_dependency_graph,
    export_include_graph,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_dep_dataframes():
    """Return minimal DataFrames needed for export_dependency_graph."""
    targets = list("ABCD")
    centrality = pd.DataFrame({
        "cmake_target": targets,
        "betweenness": [0.0, 0.5, 0.3, 0.0],
        "pagerank": [0.25, 0.25, 0.25, 0.25],
        "in_degree": [0, 1, 1, 2],
        "out_degree": [2, 1, 1, 0],
    })
    layers = pd.DataFrame({"cmake_target": targets, "layer": [2, 1, 1, 0]})
    communities = pd.DataFrame({"cmake_target": targets, "community": [0, 0, 1, 1]})
    teams = pd.DataFrame({"cmake_target": targets, "primary_team": ["team1", "team1", "team2", "team2"]})
    return centrality, layers, communities, teams


class TestDependencyGraphExport:
    def test_produces_valid_gexf(self, diamond_graph, diamond_timing):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.gexf"
            centrality, layers, communities, teams = _minimal_dep_dataframes()

            path = export_dependency_graph(
                bg=diamond_graph,
                centrality=centrality,
                layers=layers,
                communities=communities,
                timing=diamond_timing,
                team_assignments=teams,
                output_path=output,
            )
            assert path.exists()

            # Verify it can be read back
            g = nx.read_gexf(str(path))
            assert g.number_of_nodes() == 4
            assert g.number_of_edges() == 4

            # Verify node attributes are present
            node_data = dict(g.nodes(data=True))
            assert "compile_time_s" in node_data["A"]
            assert "community" in node_data["A"]
            assert "layer" in node_data["A"]
            assert "team" in node_data["A"]

    def test_node_attribute_values(self, diamond_graph, diamond_timing):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.gexf"
            centrality, layers, communities, teams = _minimal_dep_dataframes()

            export_dependency_graph(
                diamond_graph, centrality, layers, communities,
                diamond_timing, teams, output_path=output,
            )
            g = nx.read_gexf(str(output))
            node_a = g.nodes["A"]

            # A has total_build_time_ms=10000 → compile_time_s=10.0
            assert node_a["compile_time_s"] == pytest.approx(10.0)
            assert node_a["layer"] == 2
            assert node_a["community"] == 0
            assert node_a["team"] == "team1"
            assert node_a["betweenness"] == pytest.approx(0.0)
            assert node_a["pagerank"] == pytest.approx(0.25)

    def test_edge_attributes(self, diamond_graph, diamond_timing):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.gexf"
            centrality, layers, communities, teams = _minimal_dep_dataframes()

            export_dependency_graph(
                diamond_graph, centrality, layers, communities,
                diamond_timing, teams, output_path=output,
            )
            g = nx.read_gexf(str(output))
            for u, v, data in g.edges(data=True):
                assert "is_cross_community" in data
                assert "is_layer_violation" in data
                assert "dep_type" in data

    def test_cross_community_edges(self, diamond_graph, diamond_timing):
        """A(comm=0)→C(comm=1) should be cross-community."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.gexf"
            centrality, layers, communities, teams = _minimal_dep_dataframes()

            export_dependency_graph(
                diamond_graph, centrality, layers, communities,
                diamond_timing, teams, output_path=output,
            )
            g = nx.read_gexf(str(output))
            # A→C crosses community 0→1
            edge_ac = g.edges["A", "C"]
            assert edge_ac["is_cross_community"] == "true" or edge_ac["is_cross_community"] is True

    def test_critical_path_attribute(self, diamond_graph, diamond_timing):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.gexf"
            centrality, layers, communities, teams = _minimal_dep_dataframes()

            export_dependency_graph(
                diamond_graph, centrality, layers, communities,
                diamond_timing, teams,
                critical_path_targets={"A", "B", "D"},
                output_path=output,
            )
            g = nx.read_gexf(str(output))
            # A is on critical path
            assert g.nodes["A"]["on_critical_path"] in (True, "true")
            # C is not
            assert g.nodes["C"]["on_critical_path"] in (False, "false")

    def test_missing_target_in_lookups(self, diamond_graph, diamond_timing):
        """Targets not in lookup DataFrames should get defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.gexf"
            # Only provide data for A and B
            centrality = pd.DataFrame({
                "cmake_target": ["A", "B"],
                "betweenness": [0.0, 0.5],
                "pagerank": [0.25, 0.25],
                "in_degree": [0, 1],
                "out_degree": [2, 1],
            })
            layers = pd.DataFrame({"cmake_target": ["A", "B"], "layer": [2, 1]})
            communities = pd.DataFrame({"cmake_target": ["A", "B"], "community": [0, 0]})
            teams = pd.DataFrame({"cmake_target": ["A", "B"], "primary_team": ["team1", "team1"]})

            path = export_dependency_graph(
                diamond_graph, centrality, layers, communities,
                diamond_timing, teams, output_path=output,
            )
            assert path.exists()
            g = nx.read_gexf(str(path))
            # C and D should have defaults
            assert g.nodes["C"]["team"] == "unknown"
            assert g.nodes["C"]["betweenness"] == pytest.approx(0.0)


class TestIncludeGraphExport:
    @pytest.fixture
    def include_data(self):
        """Minimal include graph and associated DataFrames."""
        g = nx.DiGraph()
        g.add_edge("src/main.cpp", "src/foo.h", is_system=False, weight=3)
        g.add_edge("src/main.cpp", "src/bar.h", is_system=False, weight=2)
        g.add_edge("src/foo.h", "src/common.h", is_system=False, weight=5)
        g.add_edge("src/main.cpp", "vector", is_system=True, weight=1)

        header_metrics = pd.DataFrame({
            "header_file": ["src/foo.h", "src/bar.h", "src/common.h"],
            "cmake_target": ["libfoo", "libbar", "libcommon"],
            "sloc": [100, 50, 200],
            "source_size_bytes": [3000, 1500, 6000],
            "is_system": [False, False, False],
        })
        header_impact = pd.DataFrame({
            "file": ["src/foo.h", "src/bar.h", "src/common.h"],
            "impact_score": [1500.0, 300.0, 12000.0],
            "direct_fan_in": [1, 1, 1],
            "transitive_fan_in": [1, 1, 2],
        })
        header_pagerank = pd.DataFrame({
            "file": ["src/main.cpp", "src/foo.h", "src/bar.h", "src/common.h", "vector"],
            "pagerank": [0.1, 0.3, 0.15, 0.4, 0.05],
        })
        git_churn = pd.DataFrame({
            "source_file": ["src/main.cpp", "src/foo.h", "src/bar.h", "src/common.h"],
            "n_commits": [20, 15, 5, 30],
        })
        return g, header_metrics, header_impact, header_pagerank, git_churn

    def test_produces_valid_gexf(self, include_data):
        g, hm, hi, hp, gc = include_data
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "include.gexf"
            path = export_include_graph(g, hm, hi, hp, gc, output_path=output)
            assert path.exists()
            loaded = nx.read_gexf(str(path))
            assert loaded.number_of_nodes() > 0

    def test_exclude_system_removes_system_edges(self, include_data):
        g, hm, hi, hp, gc = include_data
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "include.gexf"
            export_include_graph(g, hm, hi, hp, gc, exclude_system=True, output_path=output)
            loaded = nx.read_gexf(str(output))
            # "vector" system header should be removed
            assert "vector" not in loaded.nodes()

    def test_include_system_keeps_system_edges(self, include_data):
        g, hm, hi, hp, gc = include_data
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "include.gexf"
            export_include_graph(g, hm, hi, hp, gc, exclude_system=False, output_path=output)
            loaded = nx.read_gexf(str(output))
            assert "vector" in loaded.nodes()

    def test_node_attributes(self, include_data):
        g, hm, hi, hp, gc = include_data
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "include.gexf"
            export_include_graph(g, hm, hi, hp, gc, exclude_system=True, output_path=output)
            loaded = nx.read_gexf(str(output))
            foo = loaded.nodes["src/foo.h"]
            assert "pagerank" in foo
            assert "impact_score" in foo
            assert "sloc" in foo
            assert "is_header" in foo
            assert foo["is_header"] in (True, "true")


class TestCochangeGraphExport:
    @pytest.fixture
    def cochange_data(self):
        cochange = pd.DataFrame({
            "item_a": ["A", "A", "B"],
            "item_b": ["B", "C", "C"],
            "cochange_count": [10, 5, 3],
            "pmi": [2.5, 1.0, 0.5],
            "jaccard": [0.4, 0.2, 0.1],
        })
        target_metrics = pd.DataFrame({
            "cmake_target": ["A", "B", "C"],
            "target_type": ["executable", "static_library", "static_library"],
            "total_build_time_ms": [10000, 20000, 5000],
        })
        git_churn = pd.DataFrame({
            "cmake_target": ["A", "B", "C"],
            "n_commits": [50, 30, 10],
            "total_churn": [1000, 500, 200],
        })
        communities = pd.DataFrame({
            "cmake_target": ["A", "B", "C"],
            "community": [0, 0, 1],
        })
        return cochange, target_metrics, git_churn, communities

    def test_produces_valid_undirected_gexf(self, cochange_data):
        cochange, tm, gc, comms = cochange_data
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "cochange.gexf"
            path = export_cochange_graph(cochange, tm, gc, comms, output_path=output)
            assert path.exists()
            loaded = nx.read_gexf(str(path))
            assert not loaded.is_directed()
            assert loaded.number_of_nodes() == 3
            assert loaded.number_of_edges() == 3

    def test_min_pmi_filtering(self, cochange_data):
        cochange, tm, gc, comms = cochange_data
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "cochange.gexf"
            export_cochange_graph(cochange, tm, gc, comms, min_pmi=1.5, output_path=output)
            loaded = nx.read_gexf(str(output))
            # Only A-B edge has pmi=2.5 >= 1.5
            assert loaded.number_of_edges() == 1

    def test_edge_attributes(self, cochange_data):
        cochange, tm, gc, comms = cochange_data
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "cochange.gexf"
            export_cochange_graph(cochange, tm, gc, comms, output_path=output)
            loaded = nx.read_gexf(str(output))
            for u, v, data in loaded.edges(data=True):
                assert "cochange_count" in data
                assert "pmi" in data
                assert "jaccard" in data

    def test_node_attributes(self, cochange_data):
        cochange, tm, gc, comms = cochange_data
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "cochange.gexf"
            export_cochange_graph(cochange, tm, gc, comms, output_path=output)
            loaded = nx.read_gexf(str(output))
            node_a = loaded.nodes["A"]
            assert "n_commits" in node_a
            assert "structural_community" in node_a
            assert "compile_time_s" in node_a
