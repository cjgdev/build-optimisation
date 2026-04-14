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


# ---------------------------------------------------------------------------
# Scope resolution helpers
# ---------------------------------------------------------------------------


class TestSplitMulti:
    def test_comma_and_repeat(self) -> None:
        assert common._split_multi(["a,b", "c", "d,e,a"]) == ["a", "b", "c", "d", "e"]

    def test_empty_and_whitespace(self) -> None:
        assert common._split_multi(None) == []
        assert common._split_multi([" , ", ""]) == []


def _make_args(processed_dir, **overrides):
    import argparse

    ns = argparse.Namespace(
        data_dir=processed_dir,
        snapshot=None,
        intermediate_dir=None,
        no_validate=True,
        target=None,
        target_glob=None,
        target_type=None,
        exclude_target=None,
        exclude_target_glob=None,
        source_dir=None,
        exclude_source_dir=None,
        module=None,
        module_category=None,
        team=None,
        teams_config=None,
        modules_config=None,
        build_set=None,
        impact_set=None,
        min_target_build_time_ms=0,
        min_target_compile_time_ms=0,
        min_target_code_lines=0,
        min_target_commits=0,
        min_target_dependants=0,
        verbose=False,
    )
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


class TestResolveScope:
    def test_empty_scope_is_global(self, processed_dir) -> None:
        args = _make_args(processed_dir)
        ds = common.load_dataset(args)
        scope = common.resolve_scope(args, ds)
        assert scope.is_global()
        assert scope.targets is None

    def test_target_identity(self, processed_dir) -> None:
        args = _make_args(processed_dir, target=["libA,libCore"])
        ds = common.load_dataset(args)
        scope = common.resolve_scope(args, ds)
        assert scope.targets == frozenset({"libA", "libCore"})

    def test_unknown_target_errors(self, processed_dir) -> None:
        args = _make_args(processed_dir, target=["nope"])
        ds = common.load_dataset(args)
        with pytest.raises(SystemExit, match="Unknown"):
            common.resolve_scope(args, ds)

    def test_target_glob(self, processed_dir) -> None:
        args = _make_args(processed_dir, target_glob=["lib*"])
        ds = common.load_dataset(args)
        scope = common.resolve_scope(args, ds)
        assert scope.targets == frozenset({"libA", "libB", "libCore"})

    def test_target_type(self, processed_dir) -> None:
        args = _make_args(processed_dir, target_type=["executable"])
        ds = common.load_dataset(args)
        scope = common.resolve_scope(args, ds)
        assert scope.targets == frozenset({"exe"})

    def test_exclude_target_glob(self, processed_dir) -> None:
        args = _make_args(processed_dir, target_glob=["lib*"], exclude_target=["libB"])
        ds = common.load_dataset(args)
        scope = common.resolve_scope(args, ds)
        assert scope.targets == frozenset({"libA", "libCore"})

    def test_source_dir(self, processed_dir) -> None:
        args = _make_args(processed_dir, source_dir=["/src/core"])
        ds = common.load_dataset(args)
        scope = common.resolve_scope(args, ds)
        assert scope.targets == frozenset({"libCore"})

    def test_build_set_includes_deps(self, processed_dir) -> None:
        # exe depends on libA, libB, (transitively) libCore.
        args = _make_args(processed_dir, build_set=["exe"])
        ds = common.load_dataset(args)
        scope = common.resolve_scope(args, ds)
        assert scope.targets == frozenset({"exe", "libA", "libB", "libCore"})

    def test_impact_set_includes_dependants(self, processed_dir) -> None:
        # Everything (transitively) depends on libCore.
        args = _make_args(processed_dir, impact_set=["libCore"])
        ds = common.load_dataset(args)
        scope = common.resolve_scope(args, ds)
        assert scope.targets == frozenset({"libCore", "libA", "libB", "exe"})

    def test_threshold_min_build_time(self, processed_dir) -> None:
        # libCore=4150, libA=2500, libB=1000, exe=500
        args = _make_args(processed_dir, min_target_build_time_ms=2000)
        ds = common.load_dataset(args)
        scope = common.resolve_scope(args, ds)
        assert scope.targets == frozenset({"libCore", "libA"})

    def test_composed_filters_intersect(self, processed_dir) -> None:
        # Everything in impact-set of libCore AND a static_library AND with commits ≥ 40
        args = _make_args(
            processed_dir,
            impact_set=["libCore"],
            target_type=["static_library"],
            min_target_commits=40,
        )
        ds = common.load_dataset(args)
        scope = common.resolve_scope(args, ds)
        # libCore(90) and libA(48) qualify; libB(6) and exe(12) drop out.
        assert scope.targets == frozenset({"libCore", "libA"})

    def test_empty_scope_raises(self, processed_dir) -> None:
        args = _make_args(processed_dir, target=["libA"], target_type=["executable"])
        ds = common.load_dataset(args)
        with pytest.raises(SystemExit, match="zero targets"):
            common.resolve_scope(args, ds)

    def test_build_set_unknown_errors(self, processed_dir) -> None:
        args = _make_args(processed_dir, build_set=["does_not_exist"])
        ds = common.load_dataset(args)
        with pytest.raises(SystemExit, match="not in the dependency graph"):
            common.resolve_scope(args, ds)

    def test_verbose_writes_to_stderr(self, processed_dir, capsys) -> None:
        rc = hotspots.main(["--data-dir", str(processed_dir), "--no-validate", "--target", "libCore", "--verbose"])
        assert rc == 0
        captured = capsys.readouterr()
        # Clean output channel unaffected, scope goes to stderr.
        assert "libCore" in captured.out
        assert "# scope:" in captured.err
        assert "libCore" in captured.err


# ---------------------------------------------------------------------------
# Scope integration — applied to actual analysis scripts
# ---------------------------------------------------------------------------


class TestScopeIntegration:
    def test_hotspots_scope_filters_to_impact_set(self, processed_dir, capsys) -> None:
        # Impact set of libA = {libA, exe}, so libCore and libB should drop.
        rc = hotspots.main(
            [
                "--data-dir",
                str(processed_dir),
                "--no-validate",
                "--impact-set",
                "libA",
                "--format",
                "csv",
                "--limit",
                "0",
            ]
        )
        assert rc == 0
        df = pd.read_csv(pd.io.common.StringIO(capsys.readouterr().out))
        assert set(df["cmake_target"]) == {"libA", "exe"}

    def test_slow_files_scope_filters_by_target(self, processed_dir, capsys) -> None:
        rc = slow_files.main(
            [
                "--data-dir",
                str(processed_dir),
                "--no-validate",
                "--target",
                "libCore",
                "--view",
                "slowest",
                "--format",
                "csv",
                "--limit",
                "0",
            ]
        )
        assert rc == 0
        df = pd.read_csv(pd.io.common.StringIO(capsys.readouterr().out))
        assert df["cmake_target"].eq("libCore").all()
        assert df.iloc[0]["source_file"] == "/src/core/c1.cpp"

    def test_slow_files_exclude_generated_is_file_filter(self, processed_dir, capsys) -> None:
        rc = slow_files.main(
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
        assert rc == 0
        df = pd.read_csv(pd.io.common.StringIO(capsys.readouterr().out))
        assert not df["source_file"].str.endswith(".pb.cc").any()

    def test_header_hotlist_scope_filters_to_target(self, processed_dir, capsys) -> None:
        rc = header_hotlist.main(
            [
                "--data-dir",
                str(processed_dir),
                "--no-validate",
                "--target",
                "libA",
                "--format",
                "csv",
                "--limit",
                "0",
            ]
        )
        assert rc == 0
        df = pd.read_csv(pd.io.common.StringIO(capsys.readouterr().out))
        # Only /src/libA/a.h belongs to libA; types.h belongs to libCore.
        assert set(df["cmake_target"]) <= {"libA"}
        assert "/src/libA/a.h" in set(df["file"])
        assert "/src/core/types.h" not in set(df["file"])

    def test_ownership_risk_scope(self, processed_dir, capsys) -> None:
        rc = ownership_risk.main(
            [
                "--data-dir",
                str(processed_dir),
                "--no-validate",
                "--target",
                "libA",
                "--format",
                "csv",
                "--limit",
                "0",
            ]
        )
        assert rc == 0
        df = pd.read_csv(pd.io.common.StringIO(capsys.readouterr().out))
        assert set(df["cmake_target"]) == {"libA"}

    def test_layer_violations_scope_subgraph(self, processed_dir, capsys) -> None:
        import re

        # Scoping to libA pulls libCore in as a transitive dep — subgraph is {libA, libCore}.
        rc = layer_violations.main(
            [
                "--data-dir",
                str(processed_dir),
                "--no-validate",
                "--target",
                "libA",
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        # Exactly two targets in the induced subgraph: libA + its transitive dep libCore.
        assert re.search(r"n_targets\s+2\b", out)

    def test_critical_path_scope_subgraph(self, processed_dir, capsys) -> None:
        rc = critical_path.main(
            [
                "--data-dir",
                str(processed_dir),
                "--no-validate",
                "--target",
                "libA",
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        # libA + libCore should form the critical path of the scoped subgraph.
        assert "libA" in out
        assert "libCore" in out
        # exe isn't a dep of libA so it should NOT appear in the scoped subgraph.
        assert "exe" not in out

    def test_empty_scope_exits(self, processed_dir) -> None:
        with pytest.raises(SystemExit, match="zero targets"):
            hotspots.main(
                [
                    "--data-dir",
                    str(processed_dir),
                    "--no-validate",
                    "--target-type",
                    "shared_library",
                ]
            )
