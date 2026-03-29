"""Tests for buildanalysis.loading — schema validation and BuildDataset."""

from pathlib import Path

import pandas as pd
import pytest

from buildanalysis.loading import BuildDataset

DATA_DIR = Path("data/processed")
HAS_DATA = DATA_DIR.exists() and (DATA_DIR / "file_metrics.parquet").exists()


@pytest.fixture
def ds():
    """Create BuildDataset pointing at the real data directory."""
    return BuildDataset(DATA_DIR)


@pytest.mark.skipif(not HAS_DATA, reason="Processed data not available")
class TestBuildDataset:
    def test_file_metrics_loads(self, ds):
        fm = ds.file_metrics
        assert isinstance(fm, pd.DataFrame)
        assert "source_file" in fm.columns
        assert "cmake_target" in fm.columns
        assert len(fm) > 0

    def test_target_metrics_loads(self, ds):
        tm = ds.target_metrics
        assert isinstance(tm, pd.DataFrame)
        assert "cmake_target" in tm.columns
        assert len(tm) > 0

    def test_edge_list_loads(self, ds):
        el = ds.edge_list
        assert isinstance(el, pd.DataFrame)
        assert "source_target" in el.columns
        assert "dest_target" in el.columns

    def test_contributor_commits_loads(self, ds):
        cc = ds.contributor_target_commits
        assert isinstance(cc, pd.DataFrame)
        assert "contributor" in cc.columns

    def test_header_edges_loads(self, ds):
        he = ds.header_edges
        assert isinstance(he, pd.DataFrame)
        assert "includer" in he.columns
        assert "included" in he.columns

    def test_header_metrics_loads(self, ds):
        hm = ds.header_metrics
        assert isinstance(hm, pd.DataFrame)
        assert "header_file" in hm.columns

    def test_build_schedule_loads(self, ds):
        bs = ds.build_schedule
        assert isinstance(bs, pd.DataFrame)
        assert "step_type" in bs.columns
        assert "duration_ms" in bs.columns

    def test_caching(self, ds):
        fm1 = ds.file_metrics
        fm2 = ds.file_metrics
        assert fm1 is fm2  # Same object, not re-loaded

    def test_has_file(self, ds):
        assert ds.has_file("file_metrics")
        assert not ds.has_file("nonexistent_table")

    def test_referential_integrity(self, ds):
        """Every cmake_target in file_metrics exists in target_metrics."""
        fm = ds.file_metrics
        tm = ds.target_metrics
        fm_targets = set(fm["cmake_target"].unique())
        tm_targets = set(tm["cmake_target"].unique())
        missing = fm_targets - tm_targets
        assert len(missing) == 0, f"Targets in file_metrics but not target_metrics: {missing}"

    def test_edge_list_integrity(self, ds):
        """Every edge endpoint exists in target_metrics."""
        el = ds.edge_list
        tm = ds.target_metrics
        tm_targets = set(tm["cmake_target"].unique())
        sources = set(el["source_target"].unique())
        dests = set(el["dest_target"].unique())
        missing_sources = sources - tm_targets
        missing_dests = dests - tm_targets
        assert len(missing_sources) == 0, f"Unknown source targets: {missing_sources}"
        assert len(missing_dests) == 0, f"Unknown dest targets: {missing_dests}"


class TestBuildDatasetMissing:
    def test_missing_file_raises(self, tmp_path):
        ds = BuildDataset(tmp_path)
        with pytest.raises(FileNotFoundError):
            _ = ds.file_metrics

    def test_missing_file_error_message(self, tmp_path):
        ds = BuildDataset(tmp_path)
        with pytest.raises(FileNotFoundError, match="file_metrics.parquet not found"):
            _ = ds.file_metrics


class TestIntermediate:
    def test_save_and_load_intermediate(self, tmp_path):
        ds = BuildDataset(tmp_path, intermediate_dir=tmp_path / "intermediate")
        test_df = pd.DataFrame({"x": [1, 2, 3]})
        path = ds.save_intermediate("test_output", test_df)
        assert path.exists()
        loaded = ds.load_intermediate("test_output")
        assert len(loaded) == 3

    def test_save_intermediate_caches(self, tmp_path):
        ds = BuildDataset(tmp_path, intermediate_dir=tmp_path / "intermediate")
        test_df = pd.DataFrame({"x": [1, 2, 3]})
        ds.save_intermediate("cached_test", test_df)
        loaded1 = ds.load_intermediate("cached_test")
        loaded2 = ds.load_intermediate("cached_test")
        assert loaded1 is loaded2

    def test_load_missing_intermediate_raises(self, tmp_path):
        ds = BuildDataset(tmp_path, intermediate_dir=tmp_path / "intermediate")
        with pytest.raises(FileNotFoundError):
            ds.load_intermediate("does_not_exist")


@pytest.mark.skipif(not HAS_DATA, reason="Processed data not available")
class TestNoValidation:
    def test_loads_without_validation(self):
        ds = BuildDataset(DATA_DIR, validate=False)
        fm = ds.file_metrics
        assert isinstance(fm, pd.DataFrame)
        assert len(fm) > 0
