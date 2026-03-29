"""Tests for buildanalysis.recommend module."""

from __future__ import annotations

import pandas as pd

from buildanalysis.build import CriticalPathResult
from buildanalysis.recommend import (
    Intervention,
    InterventionType,
    build_pareto_frontier,
    format_recommendation_summary,
    score_header_interventions,
    score_target_split_interventions,
)


def _make_intervention(
    description: str = "test",
    impact_ms: float = 1000,
    effort_days: float = 1,
    confidence: float = 0.5,
    itype: InterventionType = InterventionType.REFACTOR_HEADER,
    targets: list[str] | None = None,
    rationale: str = "",
) -> Intervention:
    return Intervention(
        intervention_type=itype,
        description=description,
        targets_affected=targets or ["a"],
        estimated_build_time_reduction_ms=impact_ms,
        estimated_effort_days=effort_days,
        confidence=confidence,
        rationale=rationale,
    )


class TestParetoFrontier:
    def test_single_intervention(self):
        interventions = [
            Intervention(
                intervention_type=InterventionType.REFACTOR_HEADER,
                description="test",
                targets_affected=["a"],
                estimated_build_time_reduction_ms=1000,
                estimated_effort_days=1,
                confidence=0.5,
            )
        ]
        result = build_pareto_frontier(interventions)
        assert len(result) == 1
        assert result.iloc[0]["pareto_optimal"]

    def test_dominated_intervention(self):
        interventions = [
            Intervention(
                intervention_type=InterventionType.REFACTOR_HEADER,
                description="good",
                targets_affected=["a"],
                estimated_build_time_reduction_ms=1000,
                estimated_effort_days=1,
                confidence=0.5,
            ),
            Intervention(
                intervention_type=InterventionType.REFACTOR_HEADER,
                description="dominated",
                targets_affected=["b"],
                estimated_build_time_reduction_ms=500,
                estimated_effort_days=2,
                confidence=0.5,
            ),
        ]
        result = build_pareto_frontier(interventions)
        good = result[result["description"] == "good"].iloc[0]
        dominated = result[result["description"] == "dominated"].iloc[0]
        assert good["pareto_optimal"]
        assert not dominated["pareto_optimal"]

    def test_pareto_front_with_tradeoffs(self):
        interventions = [
            Intervention(
                intervention_type=InterventionType.REFACTOR_HEADER,
                description="high_impact_high_effort",
                targets_affected=["a"],
                estimated_build_time_reduction_ms=5000,
                estimated_effort_days=10,
                confidence=0.5,
            ),
            Intervention(
                intervention_type=InterventionType.FORWARD_DECLARE,
                description="low_impact_low_effort",
                targets_affected=["b"],
                estimated_build_time_reduction_ms=500,
                estimated_effort_days=0.5,
                confidence=0.8,
            ),
        ]
        result = build_pareto_frontier(interventions)
        assert result["pareto_optimal"].all()

    def test_sorted_by_impact(self):
        interventions = [
            Intervention(
                intervention_type=InterventionType.REFACTOR_HEADER,
                description="small",
                targets_affected=[],
                estimated_build_time_reduction_ms=100,
                estimated_effort_days=1,
                confidence=0.5,
            ),
            Intervention(
                intervention_type=InterventionType.REFACTOR_HEADER,
                description="large",
                targets_affected=[],
                estimated_build_time_reduction_ms=5000,
                estimated_effort_days=5,
                confidence=0.5,
            ),
        ]
        result = build_pareto_frontier(interventions)
        assert result.iloc[0]["description"] == "large"

    def test_empty_interventions(self):
        result = build_pareto_frontier([])
        assert len(result) == 0

    def test_equal_interventions_both_pareto(self):
        interventions = [
            _make_intervention(description="a", impact_ms=1000, effort_days=1),
            _make_intervention(description="b", impact_ms=1000, effort_days=1),
        ]
        result = build_pareto_frontier(interventions)
        # Neither strictly dominates the other
        assert result["pareto_optimal"].all()


class TestScoreHeaderInterventions:
    def test_basic(self):
        header_impact = pd.DataFrame(
            {
                "file": ["a.h", "b.h"],
                "transitive_fan_in": [100, 50],
                "source_size_bytes": [5000, 3000],
                "direct_fan_in": [10, 5],
                "n_commits": [20, 5],
                "impact_score": [1000, 500],
            }
        )
        amplification = pd.DataFrame(
            {"file": ["x.cpp"], "direct_includes": [5], "transitive_includes": [50], "amplification_ratio": [10.0]}
        )
        result = score_header_interventions(header_impact, amplification, top_n=5)
        assert len(result) == 2
        assert all(iv.intervention_type == InterventionType.REFACTOR_HEADER for iv in result)
        # Higher fan-in header should have higher impact
        assert result[0].estimated_build_time_reduction_ms > result[1].estimated_build_time_reduction_ms

    def test_effort_clamped(self):
        header_impact = pd.DataFrame(
            {
                "file": ["huge.h"],
                "transitive_fan_in": [1000],
                "source_size_bytes": [100000],
                "direct_fan_in": [100],
                "n_commits": [50],
                "impact_score": [9999],
            }
        )
        amplification = pd.DataFrame(columns=["file", "direct_includes", "transitive_includes", "amplification_ratio"])
        result = score_header_interventions(header_impact, amplification, top_n=1)
        assert result[0].estimated_effort_days == 20.0  # clamped to max

    def test_top_n_limits_results(self):
        header_impact = pd.DataFrame(
            {
                "file": [f"h{i}.h" for i in range(10)],
                "transitive_fan_in": list(range(10, 0, -1)),
                "source_size_bytes": [1000] * 10,
                "direct_fan_in": [5] * 10,
                "n_commits": [10] * 10,
                "impact_score": list(range(10, 0, -1)),
            }
        )
        amplification = pd.DataFrame(columns=["file", "direct_includes", "transitive_includes", "amplification_ratio"])
        result = score_header_interventions(header_impact, amplification, top_n=3)
        assert len(result) == 3


class TestScoreTargetSplitInterventions:
    def _make_cp_result(self, path: list[str], total_time_s: float = 100.0) -> CriticalPathResult:
        return CriticalPathResult(
            path=path,
            total_time_s=total_time_s,
            target_slack=pd.DataFrame({"cmake_target": path, "slack_ms": [0.0] * len(path)}),
            parallelism_ratio=2.0,
            total_work_s=total_time_s * 2,
        )

    def test_basic(self):
        metrics = pd.DataFrame(
            {
                "cmake_target": ["lib_a", "lib_b", "app"],
                "total_build_time_ms": [10000, 5000, 8000],
                "n_source_files": [20, 5, 15],
            }
        )
        cp = self._make_cp_result(["app", "lib_a"])
        result = score_target_split_interventions(metrics, cp, top_n=5)
        assert len(result) >= 1
        assert all(iv.intervention_type == InterventionType.SPLIT_TARGET for iv in result)

    def test_skips_small_targets(self):
        metrics = pd.DataFrame(
            {
                "cmake_target": ["tiny"],
                "total_build_time_ms": [10000],
                "n_source_files": [2],
            }
        )
        cp = self._make_cp_result(["tiny"])
        result = score_target_split_interventions(metrics, cp)
        assert len(result) == 0

    def test_only_cp_targets(self):
        metrics = pd.DataFrame(
            {
                "cmake_target": ["on_cp", "off_cp"],
                "total_build_time_ms": [10000, 50000],
                "n_source_files": [20, 100],
            }
        )
        cp = self._make_cp_result(["on_cp"])
        result = score_target_split_interventions(metrics, cp)
        assert all("on_cp" in iv.targets_affected for iv in result)


class TestFormatRecommendationSummary:
    def test_output_format(self):
        interventions = [
            _make_intervention(
                description="Split /src/core/types.h",
                impact_ms=45000,
                effort_days=3,
                confidence=0.5,
                targets=["core_lib", "utils_lib", "app_main"],
                rationale="Header has transitive fan-in of 890.",
            ),
            _make_intervention(
                description="Remove dep X → Y",
                impact_ms=30000,
                effort_days=1,
                confidence=0.7,
                itype=InterventionType.REMOVE_DEPENDENCY,
                targets=["X", "Y"],
                rationale="Edge removal saves 30s.",
            ),
        ]
        df = build_pareto_frontier(interventions)
        text = format_recommendation_summary(df, top_n=5)
        assert "Top Build Optimisation Recommendations" in text
        assert "Split /src/core/types.h" in text
        assert "Rationale:" in text

    def test_many_targets_truncated(self):
        targets = [f"t{i}" for i in range(10)]
        interventions = [_make_intervention(targets=targets)]
        df = build_pareto_frontier(interventions)
        text = format_recommendation_summary(df)
        assert "+7 others" in text
