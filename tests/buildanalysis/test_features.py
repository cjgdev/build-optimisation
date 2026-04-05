"""Tests for buildanalysis.features."""

import networkx as nx
import pandas as pd

from buildanalysis.features import (
    compute_exe_library_matrix,
    compute_jaccard_matrix,
    detect_thin_dependencies,
    expand_core,
    identify_core_libraries,
)


def make_graph_and_types():
    """Build a graph with 2 executables and 4 libraries.

    exe_1 -> lib_a -> lib_c (core)
    exe_1 -> lib_b
    exe_2 -> lib_b -> lib_c (core)
    exe_2 -> lib_d
    """
    G = nx.DiGraph()
    G.add_edge("exe_1", "lib_a", is_direct=True, dependency_type="link")
    G.add_edge("exe_1", "lib_b", is_direct=True, dependency_type="link")
    G.add_edge("exe_2", "lib_b", is_direct=True, dependency_type="link")
    G.add_edge("exe_2", "lib_d", is_direct=True, dependency_type="link")
    G.add_edge("lib_a", "lib_c", is_direct=True, dependency_type="link")
    G.add_edge("lib_b", "lib_c", is_direct=True, dependency_type="link")

    target_types = pd.DataFrame(
        {
            "cmake_target": ["exe_1", "exe_2", "lib_a", "lib_b", "lib_c", "lib_d"],
            "target_type": [
                "executable",
                "executable",
                "static_library",
                "static_library",
                "static_library",
                "static_library",
            ],
        }
    )
    return G, target_types


class TestComputeExeLibraryMatrix:
    def test_rows(self):
        G, types = make_graph_and_types()
        matrix = compute_exe_library_matrix(G, types)
        # Should have entries for both executables
        assert set(matrix["executable"].unique()) == {"exe_1", "exe_2"}

    def test_transitive_deps(self):
        G, types = make_graph_and_types()
        matrix = compute_exe_library_matrix(G, types)
        # exe_1 depends on lib_a, lib_b, and lib_c (transitive via lib_a and lib_b)
        exe1_libs = set(matrix[matrix["executable"] == "exe_1"]["library"])
        assert exe1_libs == {"lib_a", "lib_b", "lib_c"}

    def test_is_direct_flag(self):
        G, types = make_graph_and_types()
        matrix = compute_exe_library_matrix(G, types)
        # exe_1 -> lib_a is direct, exe_1 -> lib_c is transitive
        row_direct = matrix[(matrix["executable"] == "exe_1") & (matrix["library"] == "lib_a")]
        assert bool(row_direct.iloc[0]["is_direct"]) is True
        row_trans = matrix[(matrix["executable"] == "exe_1") & (matrix["library"] == "lib_c")]
        assert bool(row_trans.iloc[0]["is_direct"]) is False


class TestIdentifyCoreLibraries:
    def test_core_detection(self):
        G, types = make_graph_and_types()
        matrix = compute_exe_library_matrix(G, types)
        # lib_c and lib_b appear in both executables (threshold 0.8 < 1.0)
        core = identify_core_libraries(matrix, threshold=0.8)
        assert "lib_c" in core
        assert "lib_b" in core

    def test_non_core(self):
        G, types = make_graph_and_types()
        matrix = compute_exe_library_matrix(G, types)
        # lib_a only appears in exe_1 (50% frequency)
        core = identify_core_libraries(matrix, threshold=0.8)
        assert "lib_a" not in core
        assert "lib_d" not in core

    def test_empty_matrix(self):
        matrix = pd.DataFrame(columns=["executable", "library", "is_direct"])
        assert identify_core_libraries(matrix) == []


class TestExpandCore:
    def test_adds_transitive_deps(self):
        G, types = make_graph_and_types()
        # Start with just lib_b as core; lib_c is a dependency of lib_b
        expanded = expand_core(G, ["lib_b"])
        assert "lib_c" in expanded
        assert "lib_b" in expanded

    def test_respects_max_fraction(self):
        G, types = make_graph_and_types()
        # With very low max_fraction, core should be small
        expanded = expand_core(G, ["lib_c"], max_fraction=0.1)
        # 0.1 * 6 nodes = 0.6 -> max 0 additions allowed (only original core)
        assert len(expanded) <= 1


class TestComputeJaccardMatrix:
    def test_self_similarity(self):
        G, types = make_graph_and_types()
        matrix = compute_exe_library_matrix(G, types)
        jaccard = compute_jaccard_matrix(matrix)
        # Diagonal should be 1.0
        for exe in jaccard.index:
            assert jaccard.loc[exe, exe] == 1.0

    def test_symmetry(self):
        G, types = make_graph_and_types()
        matrix = compute_exe_library_matrix(G, types)
        jaccard = compute_jaccard_matrix(matrix)
        assert jaccard.loc["exe_1", "exe_2"] == jaccard.loc["exe_2", "exe_1"]

    def test_similarity_value(self):
        G, types = make_graph_and_types()
        matrix = compute_exe_library_matrix(G, types)
        jaccard = compute_jaccard_matrix(matrix)
        # exe_1: {lib_a, lib_b, lib_c}, exe_2: {lib_b, lib_c, lib_d}
        # intersection: {lib_b, lib_c} = 2
        # union: {lib_a, lib_b, lib_c, lib_d} = 4
        # Jaccard = 2/4 = 0.5
        assert abs(jaccard.loc["exe_1", "exe_2"] - 0.5) < 1e-10


class TestDetectThinDependencies:
    def test_detects_thin(self):
        G = nx.DiGraph()
        G.add_edge("A", "B", is_direct=True)

        header_data = pd.DataFrame(
            {
                "source_file": ["a.h", "b1.h", "b2.h", "b3.h"],
                "cmake_target": ["A", "B", "B", "B"],
                "header_tree": ['[[".", "b1.h"]]', "[]", "[]", "[]"],
            }
        )

        result = detect_thin_dependencies(G, header_data, thinness_threshold=0.5)
        assert len(result) == 1
        row = result.iloc[0]
        assert row["depending_target"] == "A"
        assert row["depended_target"] == "B"
        assert row["thinness_ratio"] <= 0.5
