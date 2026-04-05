import networkx as nx
import pandas as pd
import pytest

from buildanalysis.graph import build_include_graph
from buildanalysis.headers import (
    analyse_pch_opportunities,
    analyse_pch_overlap,
    compute_header_impact_score,
    compute_header_pagerank,
    compute_include_amplification,
    compute_include_fan_metrics,
    identify_pch_candidates,
    simulate_pch_impact,
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
        assert len(types_row) > 0
        assert types_row.iloc[0]["direct_fan_in"] >= 2

    def test_source_files_have_zero_fan_in(self, small_include_graph):
        result = compute_include_fan_metrics(small_include_graph)
        # main.cpp and utils.cpp should have 0 fan-in (nothing includes them)
        for src in ["/src/main.cpp", "/src/utils.cpp"]:
            row = result[result["file"] == src]
            assert len(row) > 0
            assert row.iloc[0]["direct_fan_in"] == 0

    def test_fan_out(self, small_include_graph):
        result = compute_include_fan_metrics(small_include_graph)
        # main.cpp includes foo.h and bar.h → fan_out = 2
        main_row = result[result["file"] == "/src/main.cpp"]
        assert len(main_row) > 0
        assert main_row.iloc[0]["direct_fan_out"] == 2

    def test_transitive_fan_in_not_computed_for_sources(self, small_include_graph):
        result = compute_include_fan_metrics(small_include_graph)
        for src in ["/src/main.cpp", "/src/utils.cpp"]:
            row = result[result["file"] == src]
            assert len(row) > 0
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
        assert (result["amplification_ratio"] >= 1.0).all()

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
        hm = pd.DataFrame(
            {
                "header_file": ["/src/foo.h", "/src/bar.h", "/src/types.h", "/src/utils.h"],
                "sloc": [100, 50, 200, 30],
                "source_size_bytes": [3000, 1500, 6000, 900],
                "is_system": [False, False, False, False],
            }
        )
        churn = pd.DataFrame(
            {
                "source_file": ["/src/foo.h", "/src/bar.h", "/src/types.h", "/src/utils.h"],
                "n_commits": [10, 5, 20, 2],
            }
        )
        result = compute_header_impact_score(fan, hm, churn)
        assert (result["impact_score"] >= 0).all()
        # types.h should rank highest: high fan-in × large × high churn
        top = result.head(1)["file"].iloc[0]
        assert top == "/src/types.h"


# ---------------------------------------------------------------------------
# PCH analysis tests (merged from test_pch.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def pch_test_data():
    """Create a small include graph and metrics for PCH testing."""
    g = nx.DiGraph()
    g.add_edges_from(
        [
            ("/src/main.cpp", "/src/common.h"),
            ("/src/main.cpp", "/src/types.h"),
            ("/src/utils.cpp", "/src/common.h"),
            ("/src/utils.cpp", "/src/types.h"),
            ("/src/utils.cpp", "/src/helpers.h"),
            ("/src/app.cpp", "/src/common.h"),
            ("/src/app.cpp", "/src/config.h"),
            ("/src/main.cpp", "/src/config.h"),
        ]
    )

    file_metrics = pd.DataFrame(
        {
            "source_file": ["/src/main.cpp", "/src/utils.cpp", "/src/app.cpp"],
            "cmake_target": ["my_app", "my_app", "my_app"],
            "compile_time_ms": [5000, 8000, 3000],
            "preprocessed_bytes": [500_000, 800_000, 300_000],
            "code_lines": [200, 400, 100],
            "is_generated": [False, False, False],
        }
    )

    header_metrics = pd.DataFrame(
        {
            "header_file": ["/src/common.h", "/src/types.h", "/src/helpers.h", "/src/config.h"],
            "sloc": [500, 300, 100, 50],
            "source_size_bytes": [15000, 9000, 3000, 1500],
            "is_system": [False, False, False, False],
        }
    )

    git_churn = pd.DataFrame(
        {
            "source_file": ["/src/common.h", "/src/types.h", "/src/helpers.h", "/src/config.h"],
            "n_commits": [2, 1, 15, 8],
        }
    )

    return g, file_metrics, header_metrics, git_churn


class TestPCHCandidateIdentification:
    def test_identifies_candidates(self, pch_test_data):
        g, fm, hm, gc = pch_test_data
        result = identify_pch_candidates(
            target="my_app",
            include_graph=g,
            file_metrics=fm,
            header_metrics=hm,
            git_churn=gc,
            n_candidates=10,
        )
        assert len(result) > 0
        assert "pch_score" in result.columns
        assert result["pch_score"].is_monotonic_decreasing

    def test_coverage_correctness(self, pch_test_data):
        g, fm, hm, gc = pch_test_data
        result = identify_pch_candidates(
            target="my_app",
            include_graph=g,
            file_metrics=fm,
            header_metrics=hm,
            git_churn=gc,
        )
        common = result[result["header_file"] == "/src/common.h"]
        assert len(common) == 1
        assert common.iloc[0]["coverage"] == 3
        assert common.iloc[0]["coverage_fraction"] == pytest.approx(1.0)

    def test_stable_headers_score_higher(self, pch_test_data):
        g, fm, hm, gc = pch_test_data
        result = identify_pch_candidates(
            target="my_app",
            include_graph=g,
            file_metrics=fm,
            header_metrics=hm,
            git_churn=gc,
        )
        common_score = result[result["header_file"] == "/src/common.h"]["pch_score"].iloc[0]
        config = result[result["header_file"] == "/src/config.h"]
        assert len(config) > 0
        config_score = config["pch_score"].iloc[0]
        assert common_score >= config_score

    def test_n_candidates_limit(self, pch_test_data):
        g, fm, hm, gc = pch_test_data
        result = identify_pch_candidates(
            target="my_app",
            include_graph=g,
            file_metrics=fm,
            header_metrics=hm,
            git_churn=gc,
            n_candidates=2,
        )
        assert len(result) <= 2


class TestPCHImpactSimulation:
    def test_positive_savings(self, pch_test_data):
        g, fm, hm, gc = pch_test_data
        result = simulate_pch_impact(
            target="my_app",
            pch_headers=["/src/common.h", "/src/types.h"],
            include_graph=g,
            file_metrics=fm,
            header_metrics=hm,
            git_churn=gc,
        )
        assert result["estimated_compile_time_saved_ms"] > 0
        assert result["total_preprocessed_bytes_saved"] > 0
        assert result["pch_header_count"] == 2
        assert result["source_file_count"] == 3

    def test_risk_headers_identified(self, pch_test_data):
        g, fm, hm, gc = pch_test_data
        result = simulate_pch_impact(
            target="my_app",
            pch_headers=["/src/common.h", "/src/helpers.h"],
            include_graph=g,
            file_metrics=fm,
            header_metrics=hm,
            git_churn=gc,
        )
        assert "/src/helpers.h" in result["risk_headers"]

    def test_recommendation_values(self, pch_test_data):
        g, fm, hm, gc = pch_test_data
        result = simulate_pch_impact(
            target="my_app",
            pch_headers=["/src/common.h", "/src/types.h"],
            include_graph=g,
            file_metrics=fm,
            header_metrics=hm,
            git_churn=gc,
        )
        assert result["recommendation"] in ("recommended", "marginal", "not_recommended")

    def test_empty_pch_returns_zero_savings(self, pch_test_data):
        g, fm, hm, gc = pch_test_data
        result = simulate_pch_impact(
            target="my_app",
            pch_headers=[],
            include_graph=g,
            file_metrics=fm,
            header_metrics=hm,
            git_churn=gc,
        )
        assert result["estimated_compile_time_saved_ms"] == 0


class TestBatchPCHAnalysis:
    def test_analyses_target(self, pch_test_data):
        g, fm, hm, gc = pch_test_data
        result = analyse_pch_opportunities(
            targets=["my_app"],
            include_graph=g,
            file_metrics=fm,
            header_metrics=hm,
            git_churn=gc,
        )
        assert len(result) == 1
        assert result.iloc[0]["cmake_target"] == "my_app"
        assert result.iloc[0]["estimated_savings_ms"] >= 0

    def test_sorted_by_savings(self, pch_test_data):
        g, fm, hm, gc = pch_test_data
        result = analyse_pch_opportunities(
            targets=["my_app"],
            include_graph=g,
            file_metrics=fm,
            header_metrics=hm,
            git_churn=gc,
        )
        assert result["estimated_savings_ms"].is_monotonic_decreasing


class TestPCHOverlap:
    def test_identifies_common_headers(self):
        candidates = {
            "target_a": ["/src/common.h", "/src/types.h"],
            "target_b": ["/src/common.h", "/src/config.h"],
            "target_c": ["/src/common.h", "/src/types.h", "/src/other.h"],
        }
        result = analyse_pch_overlap(candidates)
        common = result[result["header_file"] == "/src/common.h"].iloc[0]
        assert common["target_count"] == 3
        assert common["target_fraction"] == pytest.approx(1.0)

        types = result[result["header_file"] == "/src/types.h"].iloc[0]
        assert types["target_count"] == 2
