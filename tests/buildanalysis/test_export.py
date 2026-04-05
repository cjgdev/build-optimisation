"""Tests for enhanced Gephi exports (REQ-05)."""

import tempfile
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import pytest

from buildanalysis.export import (
    export_cochange_graph,
    export_dependency_graph,
    export_include_graph,
    export_module_graph,
)
from buildanalysis.types import BuildGraph


@pytest.fixture
def minimal_diamond():
    """Minimal diamond graph with all required data for export."""
    g = nx.DiGraph()
    g.add_edges_from([("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")])
    meta = pd.DataFrame(
        {
            "cmake_target": ["A", "B", "C", "D"],
            "target_type": ["executable", "static_library", "static_library", "static_library"],
            "source_directory": ["/src/app", "/src/base", "/src/core", "/src/base/common"],
            "total_build_time_ms": [10000, 30000, 20000, 5000],
            "compile_time_sum_ms": [8000, 24000, 16000, 4000],
            "link_time_ms": [2000, 6000, 4000, 1000],
            "codegen_time_ms": [0, 0, 0, 0],
            "file_count": [5, 10, 8, 3],
            "code_lines_total": [500, 1000, 800, 300],
            "preprocessed_bytes_total": [50000, 100000, 80000, 30000],
            "codegen_ratio": [0.0, 0.0, 0.0, 0.0],
            "git_commit_count_total": [20, 10, 15, 5],
            "git_churn_total": [200, 100, 150, 50],
        }
    ).set_index("cmake_target")
    return BuildGraph(graph=g, target_metadata=meta)


class TestDependencyGraphExport:
    def test_produces_valid_gexf(self, minimal_diamond):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "dep.gexf"
            centrality = pd.DataFrame(
                {
                    "cmake_target": list("ABCD"),
                    "betweenness": [0.0, 0.33, 0.33, 0.0],
                    "pagerank": [0.1, 0.3, 0.3, 0.3],
                    "in_degree": [0, 1, 1, 2],
                    "out_degree": [2, 1, 1, 0],
                }
            )
            layers = pd.DataFrame({"cmake_target": list("ABCD"), "layer": [2, 1, 1, 0]})
            comms = pd.DataFrame({"cmake_target": list("ABCD"), "community": [0, 0, 1, 1]})
            timing = pd.DataFrame(
                {
                    "cmake_target": list("ABCD"),
                    "total_build_time_ms": [10000, 30000, 20000, 5000],
                }
            )

            path = export_dependency_graph(
                bg=minimal_diamond,
                centrality=centrality,
                layers=layers,
                communities=comms,
                timing=timing,
                output_path=output,
            )

            assert path.exists()
            g = nx.read_gexf(str(path))
            assert g.number_of_nodes() == 4

            node = dict(g.nodes(data=True))["A"]
            assert "module" in node
            assert "team" in node
            assert "compile_time_s" in node
            assert isinstance(node["compile_time_s"], float)

    def test_graceful_without_optional_data(self, minimal_diamond):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "dep.gexf"
            centrality = pd.DataFrame(
                {
                    "cmake_target": list("ABCD"),
                    "betweenness": [0.0] * 4,
                    "pagerank": [0.25] * 4,
                    "in_degree": [0] * 4,
                    "out_degree": [0] * 4,
                }
            )
            layers = pd.DataFrame({"cmake_target": list("ABCD"), "layer": [2, 1, 1, 0]})
            comms = pd.DataFrame({"cmake_target": list("ABCD"), "community": [0, 0, 1, 1]})
            timing = pd.DataFrame(
                {
                    "cmake_target": list("ABCD"),
                    "total_build_time_ms": [10000, 30000, 20000, 5000],
                }
            )

            path = export_dependency_graph(
                bg=minimal_diamond,
                centrality=centrality,
                layers=layers,
                communities=comms,
                timing=timing,
                team_config=None,
                module_config=None,
                output_path=output,
            )
            g = nx.read_gexf(str(path))
            node = dict(g.nodes(data=True))["A"]
            assert node["team"] == "unknown"
            assert node["module"] == "unassigned"

    def test_cross_community_edges(self, minimal_diamond):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "dep.gexf"
            centrality = pd.DataFrame(
                {
                    "cmake_target": list("ABCD"),
                    "betweenness": [0.0] * 4,
                    "pagerank": [0.25] * 4,
                    "in_degree": [0] * 4,
                    "out_degree": [0] * 4,
                }
            )
            layers = pd.DataFrame({"cmake_target": list("ABCD"), "layer": [2, 1, 1, 0]})
            comms = pd.DataFrame({"cmake_target": list("ABCD"), "community": [0, 0, 1, 1]})
            timing = pd.DataFrame(
                {
                    "cmake_target": list("ABCD"),
                    "total_build_time_ms": [10000, 30000, 20000, 5000],
                }
            )

            path = export_dependency_graph(
                bg=minimal_diamond,
                centrality=centrality,
                layers=layers,
                communities=comms,
                timing=timing,
                output_path=output,
            )
            g = nx.read_gexf(str(path))

            # A(comm 0) → C(comm 1): cross-community
            edge_ac = g.edges["A", "C"]
            assert edge_ac["is_cross_community"] in (True, "true", "True")

            # A(comm 0) → B(comm 0): same community
            edge_ab = g.edges["A", "B"]
            assert edge_ab["is_cross_community"] in (False, "false", "False")

    def test_no_numpy_types_in_gexf(self, minimal_diamond):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "dep.gexf"
            centrality = pd.DataFrame(
                {
                    "cmake_target": list("ABCD"),
                    "betweenness": np.array([0.0, 0.33, 0.33, 0.0]),
                    "pagerank": np.array([0.1, 0.3, 0.3, 0.3]),
                    "in_degree": np.array([0, 1, 1, 2]),
                    "out_degree": np.array([2, 1, 1, 0]),
                }
            )
            layers = pd.DataFrame({"cmake_target": list("ABCD"), "layer": np.array([2, 1, 1, 0])})
            comms = pd.DataFrame({"cmake_target": list("ABCD"), "community": np.array([0, 0, 1, 1])})
            timing = pd.DataFrame(
                {
                    "cmake_target": list("ABCD"),
                    "total_build_time_ms": np.array([10000, 30000, 20000, 5000]),
                }
            )

            path = export_dependency_graph(
                bg=minimal_diamond,
                centrality=centrality,
                layers=layers,
                communities=comms,
                timing=timing,
                output_path=output,
            )

            g = nx.read_gexf(str(path))
            assert g.number_of_nodes() == 4


class TestModuleGraphExport:
    def test_produces_valid_gexf(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "module.gexf"
            g = nx.DiGraph()
            g.add_edges_from(
                [
                    ("Accounting", "Base"),
                    ("Trading", "Base"),
                ]
            )

            metrics = pd.DataFrame(
                {
                    "module": ["Accounting", "Trading", "Base"],
                    "category": ["domain", "domain", "shared"],
                    "target_count": [10, 15, 20],
                    "total_build_time_ms": [60000, 90000, 120000],
                    "total_sloc": [5000, 7500, 10000],
                    "file_count": [50, 75, 100],
                    "codegen_ratio": [0.1, 0.0, 0.0],
                    "self_containment": [0.7, 0.6, 0.9],
                    "internal_dep_count": [8, 12, 18],
                    "external_dep_count": [5, 8, 2],
                    "critical_path_target_count": [2, 3, 5],
                }
            )

            path = export_module_graph(
                module_graph=g,
                module_config=None,
                module_metrics=metrics,
                output_path=output,
            )
            assert path.exists()
            loaded = nx.read_gexf(str(path))
            assert loaded.number_of_nodes() == 3
            assert loaded.number_of_edges() == 2


class TestCochangeGraphExport:
    def test_undirected_graph(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "cochange.gexf"
            cochange = pd.DataFrame(
                {
                    "item_a": ["t1", "t1"],
                    "item_b": ["t2", "t3"],
                    "cochange_count": [5, 3],
                    "pmi": [2.5, 1.8],
                    "jaccard": [0.4, 0.3],
                }
            )
            tm = pd.DataFrame(
                {
                    "cmake_target": ["t1", "t2", "t3"],
                    "total_build_time_ms": [1000, 2000, 3000],
                    "target_type": ["static_library"] * 3,
                    "codegen_ratio": [0.0, 0.0, 0.0],
                    "code_lines_total": [100, 200, 300],
                }
            )
            churn = pd.DataFrame(
                {
                    "cmake_target": ["t1", "t2", "t3"],
                    "n_commits": [10, 20, 15],
                    "total_churn": [100, 200, 150],
                }
            )
            comms = pd.DataFrame(
                {
                    "cmake_target": ["t1", "t2", "t3"],
                    "community": [0, 0, 1],
                }
            )

            path = export_cochange_graph(
                cochange=cochange,
                target_metrics=tm,
                git_churn=churn,
                structural_communities=comms,
                output_path=output,
            )
            g = nx.read_gexf(str(path))
            assert not g.is_directed()
            assert g.number_of_nodes() == 3
            assert g.number_of_edges() == 2

            for u, v, data in g.edges(data=True):
                assert "pmi" in data
                assert "cochange_count" in data

    def test_min_pmi_filtering(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "cochange.gexf"
            cochange = pd.DataFrame(
                {
                    "item_a": ["t1", "t1"],
                    "item_b": ["t2", "t3"],
                    "cochange_count": [5, 3],
                    "pmi": [2.5, 0.5],
                    "jaccard": [0.4, 0.3],
                }
            )
            tm = pd.DataFrame(
                {
                    "cmake_target": ["t1", "t2", "t3"],
                    "total_build_time_ms": [1000, 2000, 3000],
                    "target_type": ["static_library"] * 3,
                    "codegen_ratio": [0.0, 0.0, 0.0],
                    "code_lines_total": [100, 200, 300],
                }
            )
            churn = pd.DataFrame(
                {
                    "cmake_target": ["t1", "t2", "t3"],
                    "n_commits": [10, 20, 15],
                    "total_churn": [100, 200, 150],
                }
            )
            comms = pd.DataFrame(
                {
                    "cmake_target": ["t1", "t2", "t3"],
                    "community": [0, 0, 1],
                }
            )

            path = export_cochange_graph(
                cochange=cochange,
                target_metrics=tm,
                git_churn=churn,
                structural_communities=comms,
                min_pmi=1.0,
                output_path=output,
            )
            g = nx.read_gexf(str(path))
            # Only t1-t2 edge has pmi >= 1.0
            assert g.number_of_edges() == 1

    def test_node_attributes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "cochange.gexf"
            cochange = pd.DataFrame(
                {
                    "item_a": ["t1"],
                    "item_b": ["t2"],
                    "cochange_count": [5],
                    "pmi": [2.5],
                    "jaccard": [0.4],
                }
            )
            tm = pd.DataFrame(
                {
                    "cmake_target": ["t1", "t2"],
                    "total_build_time_ms": [1000, 2000],
                    "target_type": ["static_library", "executable"],
                    "codegen_ratio": [0.0, 0.1],
                    "code_lines_total": [100, 200],
                }
            )
            churn = pd.DataFrame(
                {
                    "cmake_target": ["t1", "t2"],
                    "n_commits": [10, 20],
                    "total_churn": [100, 200],
                }
            )
            comms = pd.DataFrame(
                {
                    "cmake_target": ["t1", "t2"],
                    "community": [0, 1],
                }
            )

            path = export_cochange_graph(
                cochange=cochange,
                target_metrics=tm,
                git_churn=churn,
                structural_communities=comms,
                output_path=output,
            )
            g = nx.read_gexf(str(path))
            node = dict(g.nodes(data=True))["t1"]
            assert "target_type" in node
            assert "total_build_time_s" in node
            assert "n_commits" in node
            assert "structural_community" in node


class TestDependencyGraphExportExtended:
    def test_node_attributes(self, minimal_diamond):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "dep.gexf"
            centrality = pd.DataFrame(
                {
                    "cmake_target": list("ABCD"),
                    "betweenness": [0.0, 0.33, 0.33, 0.0],
                    "pagerank": [0.1, 0.3, 0.3, 0.3],
                    "in_degree": [0, 1, 1, 2],
                    "out_degree": [2, 1, 1, 0],
                }
            )
            layers = pd.DataFrame({"cmake_target": list("ABCD"), "layer": [2, 1, 1, 0]})
            comms = pd.DataFrame({"cmake_target": list("ABCD"), "community": [0, 0, 1, 1]})
            timing = pd.DataFrame(
                {
                    "cmake_target": list("ABCD"),
                    "total_build_time_ms": [10000, 30000, 20000, 5000],
                }
            )

            path = export_dependency_graph(
                bg=minimal_diamond,
                centrality=centrality,
                layers=layers,
                communities=comms,
                timing=timing,
                output_path=output,
            )
            g = nx.read_gexf(str(path))
            node = dict(g.nodes(data=True))["B"]
            assert "betweenness" in node
            assert "pagerank" in node
            assert "layer" in node
            assert "community" in node
            assert "target_type" in node
            assert "source_directory" in node

    def test_edge_attributes(self, minimal_diamond):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "dep.gexf"
            centrality = pd.DataFrame(
                {
                    "cmake_target": list("ABCD"),
                    "betweenness": [0.0] * 4,
                    "pagerank": [0.25] * 4,
                    "in_degree": [0] * 4,
                    "out_degree": [0] * 4,
                }
            )
            layers = pd.DataFrame({"cmake_target": list("ABCD"), "layer": [2, 1, 1, 0]})
            comms = pd.DataFrame({"cmake_target": list("ABCD"), "community": [0, 0, 1, 1]})
            timing = pd.DataFrame(
                {
                    "cmake_target": list("ABCD"),
                    "total_build_time_ms": [10000, 30000, 20000, 5000],
                }
            )

            path = export_dependency_graph(
                bg=minimal_diamond,
                centrality=centrality,
                layers=layers,
                communities=comms,
                timing=timing,
                output_path=output,
            )
            g = nx.read_gexf(str(path))
            edge = g.edges["A", "B"]
            assert "is_cross_community" in edge
            assert "is_layer_violation" in edge
            assert "cmake_visibility" in edge

    def test_transitive_dep_count_fallback(self, minimal_diamond):
        """Without n_transitive_deps in centrality, falls back to graph computation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "dep.gexf"
            centrality = pd.DataFrame(
                {
                    "cmake_target": list("ABCD"),
                    "betweenness": [0.0] * 4,
                    "pagerank": [0.25] * 4,
                    "in_degree": [0] * 4,
                    "out_degree": [0] * 4,
                }
            )
            layers = pd.DataFrame({"cmake_target": list("ABCD"), "layer": [2, 1, 1, 0]})
            comms = pd.DataFrame({"cmake_target": list("ABCD"), "community": [0, 0, 1, 1]})
            timing = pd.DataFrame(
                {
                    "cmake_target": list("ABCD"),
                    "total_build_time_ms": [10000, 30000, 20000, 5000],
                }
            )

            path = export_dependency_graph(
                bg=minimal_diamond,
                centrality=centrality,
                layers=layers,
                communities=comms,
                timing=timing,
                output_path=output,
            )
            g = nx.read_gexf(str(path))
            nodes = dict(g.nodes(data=True))
            # Diamond: A→B→D, A→C→D
            # A has transitive deps {B, C, D} = 3
            assert nodes["A"]["transitive_dep_count"] == 3
            # D has no deps
            assert nodes["D"]["transitive_dep_count"] == 0
            # B has {D} = 1
            assert nodes["B"]["transitive_dep_count"] == 1

    def test_transitive_dep_count_from_centrality(self, minimal_diamond):
        """When centrality has n_transitive_deps, uses that column."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "dep.gexf"
            centrality = pd.DataFrame(
                {
                    "cmake_target": list("ABCD"),
                    "betweenness": [0.0] * 4,
                    "pagerank": [0.25] * 4,
                    "in_degree": [0] * 4,
                    "out_degree": [0] * 4,
                    "n_transitive_deps": [99, 50, 50, 0],
                }
            )
            layers = pd.DataFrame({"cmake_target": list("ABCD"), "layer": [2, 1, 1, 0]})
            comms = pd.DataFrame({"cmake_target": list("ABCD"), "community": [0, 0, 1, 1]})
            timing = pd.DataFrame(
                {
                    "cmake_target": list("ABCD"),
                    "total_build_time_ms": [10000, 30000, 20000, 5000],
                }
            )

            path = export_dependency_graph(
                bg=minimal_diamond,
                centrality=centrality,
                layers=layers,
                communities=comms,
                timing=timing,
                output_path=output,
            )
            g = nx.read_gexf(str(path))
            nodes = dict(g.nodes(data=True))
            # Uses column value, not graph-computed
            assert nodes["A"]["transitive_dep_count"] == 99

    def test_transitive_dep_fraction(self, minimal_diamond):
        """transitive_dep_fraction = count / total_nodes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "dep.gexf"
            centrality = pd.DataFrame(
                {
                    "cmake_target": list("ABCD"),
                    "betweenness": [0.0] * 4,
                    "pagerank": [0.25] * 4,
                    "in_degree": [0] * 4,
                    "out_degree": [0] * 4,
                }
            )
            layers = pd.DataFrame({"cmake_target": list("ABCD"), "layer": [2, 1, 1, 0]})
            comms = pd.DataFrame({"cmake_target": list("ABCD"), "community": [0, 0, 1, 1]})
            timing = pd.DataFrame(
                {
                    "cmake_target": list("ABCD"),
                    "total_build_time_ms": [10000, 30000, 20000, 5000],
                }
            )

            path = export_dependency_graph(
                bg=minimal_diamond,
                centrality=centrality,
                layers=layers,
                communities=comms,
                timing=timing,
                output_path=output,
            )
            g = nx.read_gexf(str(path))
            nodes = dict(g.nodes(data=True))
            # A has 3 transitive deps out of 4 nodes
            assert nodes["A"]["transitive_dep_fraction"] == pytest.approx(3 / 4)
            assert nodes["D"]["transitive_dep_fraction"] == pytest.approx(0.0)


class TestIncludeGraphExport:
    @pytest.fixture
    def include_graph(self):
        g = nx.DiGraph()
        g.add_edges_from(
            [
                ("src/main.cpp", "src/foo.h"),
                ("src/main.cpp", "src/bar.h"),
                ("src/foo.h", "src/types.h"),
                ("src/bar.h", "src/types.h"),
                ("src/main.cpp", "/usr/include/stdio.h"),
            ]
        )
        g.edges["src/main.cpp", "/usr/include/stdio.h"]["is_system"] = True
        return g

    @pytest.fixture
    def include_export_data(self):
        header_metrics = pd.DataFrame(
            {
                "header_file": ["src/foo.h", "src/bar.h", "src/types.h", "/usr/include/stdio.h"],
                "cmake_target": ["lib_a", "lib_a", "lib_b", None],
                "sloc": [100, 50, 200, 0],
                "source_size_bytes": [2000, 1000, 4000, 0],
                "is_system": [False, False, False, True],
            }
        )
        header_impact = pd.DataFrame(
            {
                "file": ["src/foo.h", "src/bar.h", "src/types.h"],
                "impact_score": [5.0, 3.0, 8.0],
                "direct_fan_in": [1, 1, 2],
                "transitive_fan_in": [1, 1, 3],
            }
        )
        header_pagerank = pd.DataFrame(
            {
                "file": ["src/foo.h", "src/bar.h", "src/types.h", "src/main.cpp", "/usr/include/stdio.h"],
                "pagerank": [0.2, 0.15, 0.4, 0.1, 0.15],
            }
        )
        git_churn = pd.DataFrame(
            {
                "source_file": ["src/foo.h", "src/bar.h"],
                "n_commits": [10, 5],
                "total_churn": [100, 50],
            }
        )
        return header_metrics, header_impact, header_pagerank, git_churn

    def test_produces_valid_gexf(self, include_graph, include_export_data):
        header_metrics, header_impact, header_pagerank, git_churn = include_export_data
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "include.gexf"
            path = export_include_graph(
                include_graph=include_graph,
                header_metrics=header_metrics,
                header_impact=header_impact,
                header_pagerank=header_pagerank,
                git_churn=git_churn,
                exclude_system=True,
                output_path=output,
            )
            assert path.exists()
            g = nx.read_gexf(str(path))
            # System header removed when exclude_system=True
            assert "/usr/include/stdio.h" not in g.nodes()
            assert g.number_of_nodes() >= 3

    def test_exclude_system_removes_system_nodes(self, include_graph, include_export_data):
        header_metrics, header_impact, header_pagerank, git_churn = include_export_data
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "include.gexf"
            export_include_graph(
                include_graph=include_graph,
                header_metrics=header_metrics,
                header_impact=header_impact,
                header_pagerank=header_pagerank,
                git_churn=git_churn,
                exclude_system=True,
                output_path=output,
            )
            g = nx.read_gexf(str(output))
            for node in g.nodes():
                assert not node.startswith("/usr/include")

    def test_include_system_keeps_system_nodes(self, include_graph, include_export_data):
        header_metrics, header_impact, header_pagerank, git_churn = include_export_data
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "include.gexf"
            export_include_graph(
                include_graph=include_graph,
                header_metrics=header_metrics,
                header_impact=header_impact,
                header_pagerank=header_pagerank,
                git_churn=git_churn,
                exclude_system=False,
                output_path=output,
            )
            g = nx.read_gexf(str(output))
            assert "/usr/include/stdio.h" in g.nodes()

    def test_node_attributes(self, include_graph, include_export_data):
        header_metrics, header_impact, header_pagerank, git_churn = include_export_data
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "include.gexf"
            export_include_graph(
                include_graph=include_graph,
                header_metrics=header_metrics,
                header_impact=header_impact,
                header_pagerank=header_pagerank,
                git_churn=git_churn,
                exclude_system=True,
                output_path=output,
            )
            g = nx.read_gexf(str(output))
            node = dict(g.nodes(data=True))["src/types.h"]
            assert "pagerank" in node
            assert "impact_score" in node
            assert "sloc" in node
            assert "is_header" in node
            assert "direct_fan_out" in node

    def test_amplification_ratio_from_parameter(self, include_graph, include_export_data):
        header_metrics, header_impact, header_pagerank, git_churn = include_export_data
        amplification = pd.DataFrame(
            {
                "file": ["src/main.cpp"],
                "amplification_ratio": [2.5],
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "include.gexf"
            export_include_graph(
                include_graph=include_graph,
                header_metrics=header_metrics,
                header_impact=header_impact,
                header_pagerank=header_pagerank,
                git_churn=git_churn,
                amplification=amplification,
                exclude_system=True,
                output_path=output,
            )
            g = nx.read_gexf(str(output))
            node = dict(g.nodes(data=True))["src/main.cpp"]
            assert node["amplification_ratio"] == pytest.approx(2.5)

    def test_amplification_ratio_defaults_without_parameter(self, include_graph, include_export_data):
        header_metrics, header_impact, header_pagerank, git_churn = include_export_data
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "include.gexf"
            export_include_graph(
                include_graph=include_graph,
                header_metrics=header_metrics,
                header_impact=header_impact,
                header_pagerank=header_pagerank,
                git_churn=git_churn,
                exclude_system=True,
                output_path=output,
            )
            g = nx.read_gexf(str(output))
            node = dict(g.nodes(data=True))["src/foo.h"]
            assert node["amplification_ratio"] == pytest.approx(0.0)

    def test_pch_candidate_score_propagated(self, include_graph, include_export_data):
        header_metrics, header_impact, header_pagerank, git_churn = include_export_data
        pch_candidates = {
            "lib_a": pd.DataFrame(
                {
                    "header_file": ["src/types.h"],
                    "pch_score": [0.85],
                }
            ),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "include.gexf"
            export_include_graph(
                include_graph=include_graph,
                header_metrics=header_metrics,
                header_impact=header_impact,
                header_pagerank=header_pagerank,
                git_churn=git_churn,
                pch_candidates=pch_candidates,
                exclude_system=True,
                output_path=output,
            )
            g = nx.read_gexf(str(output))
            node = dict(g.nodes(data=True))["src/types.h"]
            assert node["pch_candidate_score"] == pytest.approx(0.85)
