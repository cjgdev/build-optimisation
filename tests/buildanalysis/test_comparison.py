"""Tests for buildanalysis.comparison (snapshot comparison and trend analysis)."""

import math

import pandas as pd

from buildanalysis.snapshots import SnapshotManager


class TestComparison:
    def test_global_deltas(self, snapshots_dir):
        from buildanalysis.comparison import compute_global_deltas

        sm = SnapshotManager(snapshots_dir)
        ds_a, ds_b = sm.load_pair("baseline_2026-01-15", "snapshot_2026-02-01")
        result = compute_global_deltas(ds_a, ds_b)

        assert "metric" in result.columns
        assert "delta_pct" in result.columns

        build_time = result[result["metric"] == "total_build_time_ms"].iloc[0]
        # Before: 1000+2000=3000, After: 800+1800+500=3100
        assert build_time["before"] == 3000
        assert build_time["after"] == 3100

    def test_target_deltas(self, snapshots_dir):
        from buildanalysis.comparison import compute_target_deltas

        sm = SnapshotManager(snapshots_dir)
        ds_a, ds_b = sm.load_pair("baseline_2026-01-15", "snapshot_2026-02-01")
        result = compute_target_deltas(ds_a, ds_b)

        # Target 'a' exists in both (improved)
        a_row = result[result["cmake_target"] == "a"].iloc[0]
        assert a_row["build_time_delta_ms"] == -200  # 800 - 1000
        assert a_row["status"] in ("improved", "unchanged")

        # Target 'c' is new
        c_row = result[result["cmake_target"] == "c"].iloc[0]
        assert c_row["status"] == "new"

    def test_edge_deltas(self, snapshots_dir):
        from buildanalysis.comparison import compute_edge_deltas

        sm = SnapshotManager(snapshots_dir)
        ds_a, ds_b = sm.load_pair("baseline_2026-01-15", "snapshot_2026-02-01")
        result = compute_edge_deltas(ds_a, ds_b)

        assert result["edges_unchanged"] == 1  # (a, b) in both
        assert result["added_count"] == 1  # (c, b) is new

    def test_global_deltas_improved_flag(self, snapshots_dir):
        from buildanalysis.comparison import compute_global_deltas

        sm = SnapshotManager(snapshots_dir)
        ds_a, ds_b = sm.load_pair("baseline_2026-01-15", "snapshot_2026-02-01")
        result = compute_global_deltas(ds_a, ds_b)

        # total_build_time_ms went UP (3000 → 3100), so improved should be False
        bt_row = result[result["metric"] == "total_build_time_ms"].iloc[0]
        assert bt_row["improved"] == False  # noqa: E712

    def test_target_deltas_removed(self, snapshots_dir):
        """Reversing the pair should show target 'c' as removed."""
        from buildanalysis.comparison import compute_target_deltas

        sm = SnapshotManager(snapshots_dir)
        ds_b, ds_a = sm.load_pair("snapshot_2026-02-01", "baseline_2026-01-15")
        result = compute_target_deltas(ds_b, ds_a)

        c_row = result[result["cmake_target"] == "c"].iloc[0]
        assert c_row["status"] == "removed"

    def test_new_target_delta_pct_is_nan(self, snapshots_dir):
        from buildanalysis.comparison import compute_target_deltas

        sm = SnapshotManager(snapshots_dir)
        ds_a, ds_b = sm.load_pair("baseline_2026-01-15", "snapshot_2026-02-01")
        result = compute_target_deltas(ds_a, ds_b)

        c_row = result[result["cmake_target"] == "c"].iloc[0]
        assert c_row["status"] == "new"
        assert math.isnan(c_row["build_time_delta_pct"])

    def test_removed_target_delta_pct_is_nan(self, snapshots_dir):
        from buildanalysis.comparison import compute_target_deltas

        sm = SnapshotManager(snapshots_dir)
        ds_b, ds_a = sm.load_pair("snapshot_2026-02-01", "baseline_2026-01-15")
        result = compute_target_deltas(ds_b, ds_a)

        c_row = result[result["cmake_target"] == "c"].iloc[0]
        assert c_row["status"] == "removed"
        assert math.isnan(c_row["build_time_delta_pct"])


class TestTrend:
    def test_trend_data(self, snapshots_dir):
        from buildanalysis.comparison import compute_trend_data

        sm = SnapshotManager(snapshots_dir)
        all_snapshots = sm.load_all()
        result = compute_trend_data(all_snapshots)

        assert len(result) == 2
        assert result["date"].is_monotonic_increasing
        assert "total_build_time_ms" in result.columns

    def test_regression_detection(self, snapshots_dir):
        from buildanalysis.comparison import compute_trend_data, detect_regressions

        sm = SnapshotManager(snapshots_dir)
        all_snapshots = sm.load_all()
        trend = compute_trend_data(all_snapshots)
        regressions = detect_regressions(trend, threshold_pct=1.0)

        # total_build_time went from 3000 to 3100 (+3.3%), should be flagged at 1%
        assert len(regressions) > 0

    def test_regression_severity(self, snapshots_dir):
        from buildanalysis.comparison import compute_trend_data, detect_regressions

        sm = SnapshotManager(snapshots_dir)
        all_snapshots = sm.load_all()
        trend = compute_trend_data(all_snapshots)

        # At threshold 1%, a 3.3% regression is > 2x threshold -> critical
        regressions = detect_regressions(trend, threshold_pct=1.0)
        bt_reg = regressions[regressions["metric"] == "total_build_time_ms"]
        assert len(bt_reg) > 0
        assert bt_reg.iloc[0]["severity"] == "critical"

    def test_no_regressions_at_high_threshold(self, snapshots_dir):
        from buildanalysis.comparison import compute_trend_data, detect_regressions

        sm = SnapshotManager(snapshots_dir)
        all_snapshots = sm.load_all()
        trend = compute_trend_data(all_snapshots)

        # edge_count doubles (1->2, +100%) so it will be flagged even at high thresholds.
        # At 200% threshold, nothing should be flagged.
        regressions = detect_regressions(trend, threshold_pct=200.0)
        assert len(regressions) == 0

    def test_single_snapshot_no_regressions(self, snapshots_dir):
        from buildanalysis.comparison import detect_regressions

        # With only one row, no regressions can be detected
        trend = pd.DataFrame(
            {
                "total_build_time_ms": [3000],
                "total_compile_time_ms": [2400],
            }
        )
        regressions = detect_regressions(trend, threshold_pct=10.0)
        assert len(regressions) == 0
