"""Tests for buildanalysis.features."""

import networkx as nx
import pandas as pd

from buildanalysis.features import detect_thin_dependencies


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
