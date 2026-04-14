"""Tests for the ad-hoc analysis scripts under scripts/analysis/."""

from __future__ import annotations

import importlib
import json

import pandas as pd
import pytest

critical_path = importlib.import_module("scripts.analysis.critical_path")
header_hotlist = importlib.import_module("scripts.analysis.header_hotlist")
hotspots = importlib.import_module("scripts.analysis.hotspots")
layer_violations = importlib.import_module("scripts.analysis.layer_violations")
ownership_risk = importlib.import_module("scripts.analysis.ownership_risk")
rebuild_impact = importlib.import_module("scripts.analysis.rebuild_impact")
slow_files = importlib.import_module("scripts.analysis.slow_files")
target_summary = importlib.import_module("scripts.analysis.target_summary")
common = importlib.import_module("scripts.analysis._common")


# ---------------------------------------------------------------------------
# _common helpers
# ---------------------------------------------------------------------------


class TestCommon:
    def test_minmax_normalise_range(self) -> None:
        s = common.minmax_normalise(pd.Series([1.0, 3.0, 5.0]))
        assert s.min() == pytest.approx(0.0)
        assert s.max() == pytest.approx(1.0)

    def test_minmax_normalise_constant(self) -> None:
        s = common.minmax_normalise(pd.Series([2.0, 2.0, 2.0]))
        assert (s == 0.0).all()

    def test_apply_limit_zero_means_all(self) -> None:
        df = pd.DataFrame({"x": range(10)})
        assert len(common.apply_limit(df, 0)) == 10
        assert len(common.apply_limit(df, 3)) == 3


# ---------------------------------------------------------------------------
# hotspots
# ---------------------------------------------------------------------------


class TestHotspots:
    def test_ranks_libcore_at_top(self, processed_dir, capsys) -> None:
        rc = hotspots.main(["--data-dir", str(processed_dir), "--no-validate", "--format", "csv"])
        assert rc == 0
        out = capsys.readouterr().out
        rows = list(pd.read_csv(pd.io.common.StringIO(out))["cmake_target"])
        # libCore has highest build time, highest churn, and 3 dependants — should lead.
        assert rows[0] == "libCore"

    def test_exclude_codegen_drops_libB(self, processed_dir, capsys) -> None:
        hotspots.main(
            ["--data-dir", str(processed_dir), "--no-validate", "--exclude-codegen", "--format", "csv", "--limit", "0"]
        )
        out = capsys.readouterr().out
        df = pd.read_csv(pd.io.common.StringIO(out))
        assert "libB" not in set(df["cmake_target"])

    def test_json_output_parses(self, processed_dir, capsys) -> None:
        hotspots.main(["--data-dir", str(processed_dir), "--no-validate", "--format", "json"])
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)
        assert data[0]["cmake_target"] == "libCore"


# ---------------------------------------------------------------------------
# rebuild_impact
# ---------------------------------------------------------------------------


class TestRebuildImpact:
    def test_libcore_rebuild_sums_all_dependants(self, processed_dir, capsys) -> None:
        rc = rebuild_impact.main(
            ["--data-dir", str(processed_dir), "--no-validate", "--target", "libCore", "--format", "csv"]
        )
        assert rc == 0
        out = capsys.readouterr().out
        # Expect the dependants table to mention every other target by name.
        assert "exe" in out
        assert "libA" in out
        assert "libB" in out

    def test_target_by_source_file(self, processed_dir, capsys) -> None:
        rc = rebuild_impact.main(["--data-dir", str(processed_dir), "--no-validate", "--file", "/src/core/c1.cpp"])
        assert rc == 0
        assert "libCore" in capsys.readouterr().out

    def test_ranks_by_expected_daily_cost(self, processed_dir, capsys) -> None:
        rc = rebuild_impact.main(["--data-dir", str(processed_dir), "--no-validate", "--format", "csv", "--limit", "0"])
        assert rc == 0
        out = capsys.readouterr().out
        df = pd.read_csv(pd.io.common.StringIO(out))
        assert {"cmake_target", "rebuild_cost_ms", "expected_daily_cost_ms"} <= set(df.columns)
        # libCore changes often AND everything depends on it → highest daily cost.
        assert df.sort_values("expected_daily_cost_ms", ascending=False).iloc[0]["cmake_target"] == "libCore"


# ---------------------------------------------------------------------------
# critical_path
# ---------------------------------------------------------------------------


class TestCriticalPath:
    def test_critical_path_includes_core_chain(self, processed_dir, capsys) -> None:
        rc = critical_path.main(["--data-dir", str(processed_dir), "--no-validate"])
        assert rc == 0
        out = capsys.readouterr().out
        # exe → libA → libCore is the longest chain.
        for name in ("exe", "libA", "libCore"):
            assert name in out
        assert "parallelism_ratio" in out


# ---------------------------------------------------------------------------
# target_summary
# ---------------------------------------------------------------------------


class TestTargetSummary:
    def test_reports_core_summary(self, processed_dir, capsys) -> None:
        rc = target_summary.main(["--data-dir", str(processed_dir), "--no-validate", "--target", "libCore"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "libCore" in out
        # Slow files section should surface c1.cpp (slowest in libCore).
        assert "c1.cpp" in out
        # Contributors section should include alice (top committer to libCore).
        assert "alice@example.com" in out

    def test_unknown_target_errors(self, processed_dir) -> None:
        with pytest.raises(SystemExit):
            target_summary.main(["--data-dir", str(processed_dir), "--no-validate", "--target", "does_not_exist"])


# ---------------------------------------------------------------------------
# slow_files
# ---------------------------------------------------------------------------


class TestSlowFiles:
    def test_slowest_view_orders_by_compile_time(self, processed_dir, capsys) -> None:
        rc = slow_files.main(
            ["--data-dir", str(processed_dir), "--no-validate", "--view", "slowest", "--format", "csv"]
        )
        assert rc == 0
        df = pd.read_csv(pd.io.common.StringIO(capsys.readouterr().out))
        assert df.iloc[0]["source_file"] == "/src/core/c1.cpp"

    def test_exclude_generated_drops_pb_cc(self, processed_dir, capsys) -> None:
        slow_files.main(
            [
                "--data-dir",
                str(processed_dir),
                "--no-validate",
                "--view",
                "slowest",
                "--exclude-generated",
                "--format",
                "csv",
                "--limit",
                "0",
            ]
        )
        df = pd.read_csv(pd.io.common.StringIO(capsys.readouterr().out))
        assert not df["source_file"].str.endswith(".pb.cc").any()

    def test_all_view_prints_all_sections(self, processed_dir, capsys) -> None:
        rc = slow_files.main(["--data-dir", str(processed_dir), "--no-validate", "--view", "all"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Slowest files" in out
        assert "Template-instantiation heavy" in out
        assert "Preprocessor-bloat" in out
        assert "Low compile throughput" in out


# ---------------------------------------------------------------------------
# header_hotlist
# ---------------------------------------------------------------------------


class TestHeaderHotlist:
    def test_types_h_is_top_header(self, processed_dir, capsys) -> None:
        rc = header_hotlist.main(["--data-dir", str(processed_dir), "--no-validate", "--format", "csv"])
        assert rc == 0
        df = pd.read_csv(pd.io.common.StringIO(capsys.readouterr().out))
        # /src/core/types.h is included by every TU transitively → highest impact.
        assert df.iloc[0]["file"] == "/src/core/types.h"
        assert df.iloc[0]["transitive_fan_in"] >= 6


# ---------------------------------------------------------------------------
# ownership_risk
# ---------------------------------------------------------------------------


class TestOwnershipRisk:
    def test_libA_is_sole_owner_risk(self, processed_dir, capsys) -> None:
        rc = ownership_risk.main(["--data-dir", str(processed_dir), "--no-validate", "--format", "csv", "--limit", "0"])
        assert rc == 0
        df = pd.read_csv(pd.io.common.StringIO(capsys.readouterr().out))
        libA = df[df["cmake_target"] == "libA"].iloc[0]
        assert libA["n_contributors"] == 1
        assert libA["top_contributor_share"] == pytest.approx(1.0)

    def test_max_contributors_filter(self, processed_dir, capsys) -> None:
        ownership_risk.main(
            [
                "--data-dir",
                str(processed_dir),
                "--no-validate",
                "--format",
                "csv",
                "--max-contributors",
                "1",
                "--limit",
                "0",
            ]
        )
        df = pd.read_csv(pd.io.common.StringIO(capsys.readouterr().out))
        assert (df["n_contributors"] == 1).all()


# ---------------------------------------------------------------------------
# layer_violations
# ---------------------------------------------------------------------------


class TestLayerViolations:
    def test_clean_graph_has_no_violations(self, processed_dir, capsys) -> None:
        rc = layer_violations.main(["--data-dir", str(processed_dir), "--no-validate"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "n_violations" in out
        # The test graph is strictly layered — expect zero violations.
        assert "n_violations  0" in out or "n_violations 0" in out
