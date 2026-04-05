"""Tests for buildanalysis.snapshots (snapshot management)."""

import pandas as pd
import pytest

from buildanalysis.snapshots import SnapshotManager, SnapshotMetadata


class TestSnapshotManager:
    def test_list_snapshots(self, snapshots_dir):
        sm = SnapshotManager(snapshots_dir)
        snapshots = sm.list_snapshots()
        assert len(snapshots) == 2
        assert snapshots[0].date <= snapshots[1].date  # Chronological

    def test_get_baseline(self, snapshots_dir):
        sm = SnapshotManager(snapshots_dir)
        baseline = sm.get_baseline()
        assert baseline is not None
        assert "baseline" in baseline.name

    def test_get_latest(self, snapshots_dir):
        sm = SnapshotManager(snapshots_dir)
        latest = sm.get_latest()
        assert latest is not None
        assert "snapshot_2026-02-01" in latest.name

    def test_load_dataset(self, snapshots_dir):
        sm = SnapshotManager(snapshots_dir)
        ds = sm.load_dataset("baseline_2026-01-15")
        tm = ds.target_metrics
        assert len(tm) == 2

    def test_load_pair(self, snapshots_dir):
        sm = SnapshotManager(snapshots_dir)
        ds_a, ds_b = sm.load_pair("baseline_2026-01-15", "snapshot_2026-02-01")
        assert len(ds_a.target_metrics) == 2
        assert len(ds_b.target_metrics) == 3

    def test_create_snapshot(self, snapshots_dir, tmp_path):
        sm = SnapshotManager(snapshots_dir)
        source = tmp_path / "new_data"
        source.mkdir()
        pd.DataFrame({"x": [1]}).to_parquet(source / "target_metrics.parquet")

        meta = SnapshotMetadata(
            label="snapshot_2026-03-01",
            date="2026-03-01",
            git_ref="ghi789",
            git_branch="main",
            build_config="Release",
            compiler="gcc 12.3",
            compiler_flags="-O2",
            core_count=32,
            build_machine=None,
            notes="New snapshot",
            interventions_applied=[],
        )
        path = sm.create_snapshot(source, "snapshot_2026-03-01", meta)
        assert path.exists()
        assert (path / "processed" / "target_metrics.parquet").exists()
        assert (path / "metadata.yaml").exists()
        assert len(sm.list_snapshots()) == 3

    def test_duplicate_label_raises(self, snapshots_dir, tmp_path):
        sm = SnapshotManager(snapshots_dir)
        source = tmp_path / "data"
        source.mkdir()
        meta = SnapshotMetadata(
            label="baseline_2026-01-15",
            date="2026-01-15",
            git_ref="x",
            git_branch="main",
            build_config="Release",
            compiler="gcc",
            compiler_flags="",
            core_count=1,
            build_machine=None,
            notes="",
            interventions_applied=[],
        )
        with pytest.raises(ValueError, match="[Aa]lready exists"):
            sm.create_snapshot(source, "baseline_2026-01-15", meta)

    def test_invalid_label_raises(self, snapshots_dir, tmp_path):
        sm = SnapshotManager(snapshots_dir)
        source = tmp_path / "data2"
        source.mkdir()
        meta = SnapshotMetadata(
            label="123invalid",
            date="2026-03-01",
            git_ref="x",
            git_branch="main",
            build_config="Release",
            compiler="gcc",
            compiler_flags="",
            core_count=1,
            build_machine=None,
            notes="",
            interventions_applied=[],
        )
        with pytest.raises(ValueError, match="[Ii]nvalid"):
            sm.create_snapshot(source, "123invalid", meta)

    def test_empty_label_raises(self, snapshots_dir, tmp_path):
        sm = SnapshotManager(snapshots_dir)
        source = tmp_path / "data3"
        source.mkdir()
        meta = SnapshotMetadata(
            label="",
            date="2026-03-01",
            git_ref="x",
            git_branch="main",
            build_config="Release",
            compiler="gcc",
            compiler_flags="",
            core_count=1,
            build_machine=None,
            notes="",
            interventions_applied=[],
        )
        with pytest.raises(ValueError):
            sm.create_snapshot(source, "", meta)

    def test_metadata_roundtrip(self, tmp_path):
        meta = SnapshotMetadata(
            label="test",
            date="2026-04-01",
            git_ref="abc",
            git_branch="dev",
            build_config="Debug",
            compiler="clang 17",
            compiler_flags="-g",
            core_count=16,
            build_machine="local",
            notes="Test roundtrip",
            interventions_applied=["PCH for base", "Split utils.h"],
        )
        path = tmp_path / "metadata.yaml"
        meta.to_yaml(path)
        loaded = SnapshotMetadata.from_yaml(path)
        assert loaded.label == meta.label
        assert loaded.date == meta.date
        assert loaded.interventions_applied == meta.interventions_applied
        assert loaded.build_machine == meta.build_machine


class TestBuildDatasetSnapshotIntegration:
    def test_from_snapshot(self, snapshots_dir):
        from buildanalysis.loading import BuildDataset

        snapshot_dir = snapshots_dir / "baseline_2026-01-15"
        ds = BuildDataset.from_snapshot(snapshot_dir, validate=False)
        assert len(ds.target_metrics) == 2

    def test_from_latest(self, snapshots_dir):
        from buildanalysis.loading import BuildDataset

        # Create the latest symlink
        latest_link = snapshots_dir / "latest"
        if not latest_link.exists():
            latest_link.symlink_to("snapshot_2026-02-01")

        ds = BuildDataset.from_latest(snapshots_dir, validate=False)
        assert len(ds.target_metrics) == 3  # The second snapshot has 3 targets

    def test_from_baseline(self, snapshots_dir):
        from buildanalysis.loading import BuildDataset

        ds = BuildDataset.from_baseline(snapshots_dir, validate=False)
        assert len(ds.target_metrics) == 2
