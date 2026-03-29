"""Data loading and validation layer for build analysis.

Provides Pandera schemas for each parquet file and a lazy-loading
``BuildDataset`` container that validates data on first access.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pandera as pa
from pandera.typing import Series

# ---------------------------------------------------------------------------
# Pandera Schemas — match actual parquet column names and types exactly
# ---------------------------------------------------------------------------


class FileMetricsSchema(pa.DataFrameModel):
    """Validates ``file_metrics.parquet``."""

    source_file: Series[str] = pa.Field(nullable=False)
    cmake_target: Series[str] = pa.Field(nullable=False)
    is_generated: Series[bool] = pa.Field()
    language: Series[str] = pa.Field(nullable=True)
    compile_time_ms: Series[float] = pa.Field(nullable=True, ge=0)
    gcc_parse_time_ms: Series[float] = pa.Field(nullable=True, ge=0)
    gcc_template_instantiation_ms: Series[float] = pa.Field(nullable=True, ge=0)
    gcc_codegen_time_ms: Series[float] = pa.Field(nullable=True, ge=0)
    gcc_optimization_time_ms: Series[float] = pa.Field(nullable=True, ge=0)
    gcc_total_time_ms: Series[float] = pa.Field(nullable=True, ge=0)
    code_lines: Series[int] = pa.Field(nullable=True, ge=0)
    blank_lines: Series[int] = pa.Field(nullable=True, ge=0)
    comment_lines: Series[int] = pa.Field(nullable=True, ge=0)
    source_size_bytes: Series[float] = pa.Field(nullable=True, ge=0)
    header_max_depth: Series[float] = pa.Field(nullable=True, ge=0)
    unique_headers: Series[float] = pa.Field(nullable=True, ge=0)
    total_includes: Series[float] = pa.Field(nullable=True, ge=0)
    header_tree: Series[str] = pa.Field(nullable=True)
    preprocessed_bytes: Series[float] = pa.Field(nullable=True, ge=0)
    object_size_bytes: Series[float] = pa.Field(nullable=True, ge=0)
    git_commit_count: Series[int] = pa.Field(nullable=True, ge=0)
    git_lines_added: Series[int] = pa.Field(nullable=True, ge=0)
    git_lines_deleted: Series[int] = pa.Field(nullable=True, ge=0)
    git_churn: Series[int] = pa.Field(nullable=True, ge=0)
    git_distinct_authors: Series[int] = pa.Field(nullable=True, ge=0)
    git_last_change_date: Series[str] = pa.Field(nullable=True)
    expansion_ratio: Series[float] = pa.Field(nullable=True, ge=0)
    compile_rate_lines_per_sec: Series[float] = pa.Field(nullable=True, ge=0)
    object_efficiency: Series[float] = pa.Field(nullable=True, ge=0)

    class Config:
        coerce = True
        strict = False  # Allow extra columns (e.g. compile_time_ms_clipped)


class TargetMetricsSchema(pa.DataFrameModel):
    """Validates ``target_metrics.parquet``."""

    cmake_target: Series[str] = pa.Field(nullable=False)
    target_type: Series[str] = pa.Field(nullable=False)
    output_artifact: Series[str] = pa.Field(nullable=True)
    file_count: Series[int] = pa.Field(ge=0)
    codegen_file_count: Series[int] = pa.Field(ge=0)
    authored_file_count: Series[int] = pa.Field(ge=0)
    codegen_ratio: Series[float] = pa.Field(ge=0, le=1)
    code_lines_total: Series[int] = pa.Field(ge=0)
    code_lines_authored: Series[int] = pa.Field(ge=0)
    code_lines_generated: Series[int] = pa.Field(ge=0)
    compile_time_sum_ms: Series[float] = pa.Field(nullable=True, ge=0)
    compile_time_max_ms: Series[float] = pa.Field(nullable=True, ge=0)
    compile_time_mean_ms: Series[float] = pa.Field(nullable=True, ge=0)
    compile_time_median_ms: Series[float] = pa.Field(nullable=True, ge=0)
    compile_time_std_ms: Series[float] = pa.Field(nullable=True, ge=0)
    compile_time_p90_ms: Series[float] = pa.Field(nullable=True, ge=0)
    compile_time_p99_ms: Series[float] = pa.Field(nullable=True, ge=0)
    authored_compile_time_sum_ms: Series[int] = pa.Field(ge=0)
    authored_compile_time_max_ms: Series[int] = pa.Field(ge=0)
    codegen_compile_time_sum_ms: Series[int] = pa.Field(ge=0)
    codegen_compile_time_max_ms: Series[int] = pa.Field(ge=0)
    gcc_parse_time_sum_ms: Series[float] = pa.Field(ge=0)
    gcc_template_time_sum_ms: Series[float] = pa.Field(ge=0)
    gcc_codegen_phase_sum_ms: Series[float] = pa.Field(ge=0)
    gcc_optimization_time_sum_ms: Series[float] = pa.Field(ge=0)
    header_depth_max: Series[int] = pa.Field(ge=0)
    header_depth_mean: Series[float] = pa.Field(ge=0)
    unique_headers_total: Series[int] = pa.Field(ge=0)
    total_includes_sum: Series[int] = pa.Field(ge=0)
    preprocessed_bytes_total: Series[int] = pa.Field(ge=0)
    preprocessed_bytes_mean: Series[float] = pa.Field(ge=0)
    expansion_ratio_mean: Series[float] = pa.Field(ge=0)
    object_size_total_bytes: Series[int] = pa.Field(ge=0)
    object_file_count: Series[int] = pa.Field(ge=0)
    codegen_time_ms: Series[float] = pa.Field(nullable=True, ge=0)
    archive_time_ms: Series[float] = pa.Field(nullable=True, ge=0)
    link_time_ms: Series[float] = pa.Field(nullable=True, ge=0)
    total_build_time_ms: Series[float] = pa.Field(nullable=True, ge=0)
    git_commit_count_total: Series[int] = pa.Field(ge=0)
    git_churn_total: Series[int] = pa.Field(ge=0)
    git_distinct_authors: Series[int] = pa.Field(ge=0)
    git_hotspot_file_count: Series[int] = pa.Field(ge=0)
    direct_dependency_count: Series[int] = pa.Field(ge=0)
    transitive_dependency_count: Series[int] = pa.Field(ge=0)
    total_dependency_count: Series[int] = pa.Field(ge=0)
    direct_dependant_count: Series[int] = pa.Field(ge=0)
    transitive_dependant_count: Series[int] = pa.Field(ge=0)
    topological_depth: Series[int] = pa.Field(ge=0)
    critical_path_contribution_ms: Series[int] = pa.Field(ge=0)
    fan_in: Series[int] = pa.Field(ge=0)
    fan_out: Series[int] = pa.Field(ge=0)
    betweenness_centrality: Series[float] = pa.Field(ge=0)
    source_files: Series[str] = pa.Field(nullable=True)
    generated_files: Series[str] = pa.Field(nullable=True)
    output_files: Series[str] = pa.Field(nullable=True)

    class Config:
        coerce = True
        strict = False


class EdgeListSchema(pa.DataFrameModel):
    """Validates ``edge_list.parquet``."""

    source_target: Series[str] = pa.Field(nullable=False)
    dest_target: Series[str] = pa.Field(nullable=False)
    is_direct: Series[bool] = pa.Field()
    dependency_type: Series[str] = pa.Field(nullable=True)
    source_target_type: Series[str] = pa.Field(nullable=True)
    dest_target_type: Series[str] = pa.Field(nullable=True)
    from_dependency: Series[str] = pa.Field(nullable=True)

    class Config:
        coerce = True
        strict = False


class ContributorTargetCommitsSchema(pa.DataFrameModel):
    """Validates ``contributor_target_commits.parquet``."""

    contributor: Series[str] = pa.Field(nullable=False)
    cmake_target: Series[str] = pa.Field(nullable=False)
    commit_count: Series[int] = pa.Field(ge=1)

    class Config:
        coerce = True
        strict = False


class GitCommitLogSchema(pa.DataFrameModel):
    """Validates ``git_commit_log.parquet``."""

    commit_hash: Series[str] = pa.Field(nullable=False)
    timestamp: Series[pd.Timestamp] = pa.Field(nullable=False)  # type: ignore[type-arg]
    contributor: Series[str] = pa.Field(nullable=False)
    source_file: Series[str] = pa.Field(nullable=False)
    lines_added: Series[int] = pa.Field(ge=0)
    lines_deleted: Series[int] = pa.Field(ge=0)

    class Config:
        coerce = True
        strict = False


class HeaderEdgesSchema(pa.DataFrameModel):
    """Validates ``header_edges.parquet``."""

    includer: Series[str] = pa.Field(nullable=False)
    included: Series[str] = pa.Field(nullable=False)
    depth: Series[int] = pa.Field(ge=0)
    source_file: Series[str] = pa.Field(nullable=False)
    is_system: Series[bool] = pa.Field()

    class Config:
        coerce = True
        strict = False


class HeaderMetricsSchema(pa.DataFrameModel):
    """Validates ``header_metrics.parquet``."""

    header_file: Series[str] = pa.Field(nullable=False)
    cmake_target: Series[str] = pa.Field(nullable=True)
    sloc: Series[int] = pa.Field(ge=0)
    source_size_bytes: Series[int] = pa.Field(ge=0)
    is_system: Series[bool] = pa.Field()

    class Config:
        coerce = True
        strict = False


class BuildScheduleSchema(pa.DataFrameModel):
    """Validates ``build_schedule.parquet``."""

    output_file: Series[str] = pa.Field(nullable=False)
    source_file: Series[str] = pa.Field(nullable=True)
    cmake_target: Series[str] = pa.Field(nullable=True)
    step_type: Series[str] = pa.Field(nullable=False)
    start_time_ms: Series[int] = pa.Field(ge=0)
    end_time_ms: Series[int] = pa.Field(ge=0)
    duration_ms: Series[int] = pa.Field(ge=0)

    class Config:
        coerce = True
        strict = False


# ---------------------------------------------------------------------------
# File provenance — maps parquet names to schemas and helpful error messages
# ---------------------------------------------------------------------------

_SCHEMA_MAP: dict[str, type[pa.DataFrameModel]] = {
    "file_metrics": FileMetricsSchema,
    "target_metrics": TargetMetricsSchema,
    "edge_list": EdgeListSchema,
    "contributor_target_commits": ContributorTargetCommitsSchema,
    "git_commit_log": GitCommitLogSchema,
    "header_edges": HeaderEdgesSchema,
    "header_metrics": HeaderMetricsSchema,
    "build_schedule": BuildScheduleSchema,
}

_PROVENANCE: dict[str, str] = {
    "file_metrics": "scripts/consolidate/build_file_metrics.py",
    "target_metrics": "scripts/consolidate/build_target_metrics.py",
    "edge_list": "scripts/consolidate/build_edge_list.py",
    "contributor_target_commits": "scripts/consolidate/build_contributor_metrics.py",
    "git_commit_log": "scripts/collect/02_git_history.py",
    "header_edges": "scripts/consolidate/build_header_edges.py",
    "header_metrics": "scripts/consolidate/build_header_edges.py",
    "build_schedule": "scripts/consolidate/build_schedule.py",
}


# ---------------------------------------------------------------------------
# BuildDataset
# ---------------------------------------------------------------------------


class BuildDataset:
    """Lazily loads and validates analysis data from parquet files.

    Usage::

        ds = BuildDataset(Path("data/processed"))
        fm = ds.file_metrics          # Loaded and validated on first access
        tm = ds.target_metrics

    Missing files raise a clear error message on access, not on construction.
    """

    def __init__(
        self,
        data_dir: Path,
        intermediate_dir: Path | None = None,
        validate: bool = True,
    ):
        """
        Parameters
        ----------
        data_dir:
            Directory containing the processed parquet files.
        intermediate_dir:
            Directory for notebook-produced intermediate files.
            Defaults to ``data_dir / "intermediate"``.
        validate:
            If True, validate against Pandera schemas on load.
            Set to False for faster loading when debugging.
        """
        self._data_dir = Path(data_dir)
        self._intermediate_dir = Path(intermediate_dir) if intermediate_dir else self._data_dir / "intermediate"
        self._validate = validate
        self._cache: dict[str, pd.DataFrame] = {}

    # -- Private helpers ----------------------------------------------------

    def _load(self, name: str) -> pd.DataFrame:
        """Load a parquet file, optionally validating against its schema."""
        if name in self._cache:
            return self._cache[name]

        path = self._data_dir / f"{name}.parquet"
        if not path.exists():
            provenance = _PROVENANCE.get(name, "the data collection pipeline")
            raise FileNotFoundError(
                f"{path} not found. "
                f"This file is produced by {provenance}. "
                f"Run the data collection pipeline first."
            )

        df = pd.read_parquet(path)

        if self._validate and name in _SCHEMA_MAP:
            df = _SCHEMA_MAP[name].validate(df)

        self._cache[name] = df
        return df

    def _load_intermediate(self, name: str) -> pd.DataFrame:
        """Load from the intermediate directory (no schema validation)."""
        if name in self._cache:
            return self._cache[name]

        path = self._intermediate_dir / f"{name}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"{path} not found. Run the notebook that produces this file first.")

        df = pd.read_parquet(path)
        self._cache[name] = df
        return df

    # -- Core dataset properties --------------------------------------------

    @property
    def file_metrics(self) -> pd.DataFrame:
        return self._load("file_metrics")

    @property
    def target_metrics(self) -> pd.DataFrame:
        return self._load("target_metrics")

    @property
    def edge_list(self) -> pd.DataFrame:
        return self._load("edge_list")

    @property
    def contributor_target_commits(self) -> pd.DataFrame:
        return self._load("contributor_target_commits")

    @property
    def git_commit_log(self) -> pd.DataFrame:
        return self._load("git_commit_log")

    @property
    def header_edges(self) -> pd.DataFrame:
        return self._load("header_edges")

    @property
    def header_metrics(self) -> pd.DataFrame:
        return self._load("header_metrics")

    @property
    def build_schedule(self) -> pd.DataFrame:
        return self._load("build_schedule")

    # -- Notebook-produced intermediate properties --------------------------

    @property
    def contributor_groups(self) -> pd.DataFrame:
        return self._load_intermediate("contributor_groups")

    @property
    def target_ownership(self) -> pd.DataFrame:
        return self._load_intermediate("target_ownership")

    @property
    def coupling_metrics(self) -> pd.DataFrame:
        return self._load_intermediate("coupling_metrics")

    # -- Public methods -----------------------------------------------------

    def save_intermediate(self, name: str, df: pd.DataFrame) -> Path:
        """Persist a derived dataset for use by downstream notebooks.

        Saves to ``intermediate_dir/{name}.parquet`` and returns the path.
        """
        self._intermediate_dir.mkdir(parents=True, exist_ok=True)
        path = self._intermediate_dir / f"{name}.parquet"
        df.to_parquet(path, index=False)
        # Update cache so subsequent access returns the same data
        self._cache[name] = df
        return path

    def load_intermediate(self, name: str) -> pd.DataFrame:
        """Load a previously saved intermediate dataset."""
        return self._load_intermediate(name)

    def has_file(self, name: str) -> bool:
        """Check whether a parquet file exists without loading it."""
        return (self._data_dir / f"{name}.parquet").exists()
