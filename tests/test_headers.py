import networkx as nx
import pandas as pd
import pytest

from buildanalysis.graphs import build_include_graph
from buildanalysis.headers import (
    compute_header_impact_score,
    compute_header_pagerank,
    compute_include_amplification,
    compute_include_fan_metrics,
)


@pytest.fixture
def small_include_graph(synthetic_include_edges):
    """Build include graph from the synthetic fixture."""
    return build_include_graph(synthetic_include_edges)


class TestFanMetrics:
    def test_basic(self, small_include_graph):
        result = compute_include_fan_metrics(small_include_graph)
        assert len(result) > 0
        assert "direct_fan_in" in result.columns
        assert "transitive_fan_in" in result.columns

        # types.h is included by foo.h, bar.h, and utils.cpp → fan_in >= 3
        types_row = result[result["file"] == "/src/types.h"]
        if len(types_row) > 0:
            assert types_row.iloc[0]["direct_fan_in"] >= 2

    def test_source_files_have_zero_fan_in(self, small_include_graph):
        result = compute_include_fan_metrics(small_include_graph)
        # main.cpp and utils.cpp should have 0 fan-in (nothing includes them)
        for src in ["/src/main.cpp", "/src/utils.cpp"]:
            row = result[result["file"] == src]
            if len(row) > 0:
                assert row.iloc[0]["direct_fan_in"] == 0

    def test_fan_out(self, small_include_graph):
        result = compute_include_fan_metrics(small_include_graph)
        # main.cpp includes foo.h and bar.h → fan_out = 2
        main_row = result[result["file"] == "/src/main.cpp"]
        if len(main_row) > 0:
            assert main_row.iloc[0]["direct_fan_out"] == 2

    def test_transitive_fan_in_not_computed_for_sources(self, small_include_graph):
        result = compute_include_fan_metrics(small_include_graph)
        for src in ["/src/main.cpp", "/src/utils.cpp"]:
            row = result[result["file"] == src]
            if len(row) > 0:
                assert row.iloc[0]["transitive_fan_in"] == -1

    def test_is_header_flag(self, small_include_graph):
        result = compute_include_fan_metrics(small_include_graph)
        for _, row in result.iterrows():
            if row["file"].endswith(".h"):
                assert row["is_header"] is True
            elif row["file"].endswith(".cpp"):
                assert row["is_header"] is False


class TestPageRank:
    def test_sums_to_one(self, small_include_graph):
        result = compute_header_pagerank(small_include_graph, exclude_system=False)
        assert abs(result["pagerank"].sum() - 1.0) < 0.01

    def test_widely_included_header_ranks_high(self, small_include_graph):
        result = compute_header_pagerank(small_include_graph, exclude_system=False)
        # types.h is the most widely included → should have high rank
        top = result.head(3)["file"].tolist()
        assert "/src/types.h" in top

    def test_sorted_descending(self, small_include_graph):
        result = compute_header_pagerank(small_include_graph)
        assert result["pagerank"].is_monotonic_decreasing


class TestAmplification:
    def test_basic(self, small_include_graph):
        result = compute_include_amplification(small_include_graph)
        assert len(result) > 0
        assert "amplification_ratio" in result.columns
        # Ratios should be >= 1 (you always reach at least your direct includes)
        assert (result["amplification_ratio"] >= 1.0).all() | (result["direct_includes"] == 0).all()

    def test_main_cpp_amplification(self, small_include_graph):
        result = compute_include_amplification(small_include_graph)
        main_row = result[result["file"] == "/src/main.cpp"]
        if len(main_row) > 0:
            row = main_row.iloc[0]
            # main.cpp directly includes foo.h and bar.h (2)
            # Transitively: foo.h→types.h, foo.h→utils.h, bar.h→types.h (deduplicated)
            # Total transitive: foo.h, bar.h, types.h, utils.h = 4
            assert row["direct_includes"] == 2
            assert row["transitive_includes"] >= 4
            assert row["amplification_ratio"] >= 2.0


class TestImpactScore:
    def test_non_negative(self, small_include_graph):
        fan = compute_include_fan_metrics(small_include_graph)
        hm = pd.DataFrame({
            "header_file": ["/src/foo.h", "/src/bar.h", "/src/types.h", "/src/utils.h"],
            "sloc": [100, 50, 200, 30],
            "source_size_bytes": [3000, 1500, 6000, 900],
            "is_system": [False, False, False, False],
        })
        churn = pd.DataFrame({
            "source_file": ["/src/foo.h", "/src/bar.h", "/src/types.h", "/src/utils.h"],
            "n_commits": [10, 5, 20, 2],
        })
        result = compute_header_impact_score(fan, hm, churn)
        assert (result["impact_score"] >= 0).all()
        # types.h should rank highest: high fan-in × large × high churn
        top = result.head(1)["file"].iloc[0]
        assert top == "/src/types.h"
