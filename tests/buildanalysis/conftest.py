"""Shared fixtures for tests/buildanalysis/."""

import pandas as pd
import pytest

from buildanalysis.snapshots import SnapshotMetadata


@pytest.fixture
def snapshots_dir(tmp_path):
    """Create a directory with two mock snapshots."""
    # Baseline
    base = tmp_path / "baseline_2026-01-15" / "processed"
    base.mkdir(parents=True)
    pd.DataFrame(
        {
            "cmake_target": ["a", "b"],
            "total_build_time_ms": [1000, 2000],
            "compile_time_sum_ms": [800, 1600],
            "link_time_ms": [200, 400],
            "code_lines_total": [100, 200],
            "file_count": [5, 10],
            "preprocessed_bytes_total": [50000, 100000],
            "total_dependency_count": [3, 5],
            "target_type": ["executable", "static_library"],
            "codegen_ratio": [0.0, 0.1],
            "expansion_ratio_mean": [10.0, 15.0],
        }
    ).to_parquet(base / "target_metrics.parquet")

    pd.DataFrame(
        {
            "source_target": ["a"],
            "dest_target": ["b"],
            "is_direct": [True],
        }
    ).to_parquet(base / "edge_list.parquet")

    meta = SnapshotMetadata(
        label="baseline_2026-01-15",
        date="2026-01-15",
        git_ref="abc123",
        git_branch="main",
        build_config="Release",
        compiler="gcc 12.3",
        compiler_flags="-O2",
        core_count=32,
        build_machine="ci-01",
        notes="Baseline",
        interventions_applied=[],
    )
    meta.to_yaml(tmp_path / "baseline_2026-01-15" / "metadata.yaml")

    # Snapshot 2
    snap = tmp_path / "snapshot_2026-02-01" / "processed"
    snap.mkdir(parents=True)
    pd.DataFrame(
        {
            "cmake_target": ["a", "b", "c"],
            "total_build_time_ms": [800, 1800, 500],
            "compile_time_sum_ms": [640, 1440, 400],
            "link_time_ms": [160, 360, 100],
            "code_lines_total": [100, 220, 50],
            "file_count": [5, 11, 3],
            "preprocessed_bytes_total": [40000, 95000, 20000],
            "total_dependency_count": [3, 4, 2],
            "target_type": ["executable", "static_library", "static_library"],
            "codegen_ratio": [0.0, 0.1, 0.0],
            "expansion_ratio_mean": [8.0, 14.0, 10.0],
        }
    ).to_parquet(snap / "target_metrics.parquet")

    pd.DataFrame(
        {
            "source_target": ["a", "c"],
            "dest_target": ["b", "b"],
            "is_direct": [True, True],
        }
    ).to_parquet(snap / "edge_list.parquet")

    meta2 = SnapshotMetadata(
        label="snapshot_2026-02-01",
        date="2026-02-01",
        git_ref="def456",
        git_branch="main",
        build_config="Release",
        compiler="gcc 12.3",
        compiler_flags="-O2",
        core_count=32,
        build_machine="ci-01",
        notes="After header refactoring",
        interventions_applied=["Split core/types.h"],
    )
    meta2.to_yaml(tmp_path / "snapshot_2026-02-01" / "metadata.yaml")

    return tmp_path
