"""Path canonicalisation, PyArrow schema constants, and aggregation helpers."""

from __future__ import annotations

import os

import pandas as pd
import pyarrow as pa


def canonicalise_path(path: str, base_dir: str) -> str:
    """Canonicalise a path relative to a base directory."""
    return os.path.realpath(os.path.join(base_dir, path))


def map_file_to_target(file_path: str, file_index: dict[str, str]) -> str | None:
    """Look up the canonical file path in the File API file index."""
    return file_index.get(file_path)


# ---------------------------------------------------------------------------
# PyArrow Schema Constants
# ---------------------------------------------------------------------------

FILE_METRICS_SCHEMA = pa.schema(
    [
        ("source_file", pa.string()),
        ("cmake_target", pa.string()),
        ("is_generated", pa.bool_()),
        ("language", pa.string()),
        ("compile_time_ms", pa.int64()),
        ("compiler_parse_time_ms", pa.float64()),
        ("compiler_template_instantiation_ms", pa.float64()),
        ("compiler_codegen_time_ms", pa.float64()),
        ("compiler_optimization_time_ms", pa.float64()),
        ("compiler_total_time_ms", pa.float64()),
        ("compiler_total_usr_ms", pa.float64()),
        ("compiler_total_sys_ms", pa.float64()),
        ("code_lines", pa.int64()),
        ("blank_lines", pa.int64()),
        ("comment_lines", pa.int64()),
        ("source_size_bytes", pa.int64()),
        ("header_max_depth", pa.int64()),
        ("unique_headers", pa.int64()),
        ("total_includes", pa.int64()),
        ("header_tree", pa.large_utf8()),  # JSON-serialised list
        ("preprocessed_bytes", pa.int64()),
        ("object_size_bytes", pa.int64()),
        ("git_commit_count", pa.int64()),
        ("git_lines_added", pa.int64()),
        ("git_lines_deleted", pa.int64()),
        ("git_churn", pa.int64()),
        ("git_distinct_authors", pa.int64()),
        ("git_first_change_date", pa.string()),
        ("git_last_change_date", pa.string()),
        ("expansion_ratio", pa.float64()),
        ("compile_rate_lines_per_sec", pa.float64()),
        ("object_efficiency", pa.float64()),
    ]
)

TARGET_METRICS_SCHEMA = pa.schema(
    [
        ("cmake_target", pa.string()),
        ("target_type", pa.string()),
        ("output_artifact", pa.string()),
        ("source_directory", pa.string()),
        ("directory_depth", pa.int64()),
        # Source file counts
        ("file_count", pa.int64()),
        ("codegen_file_count", pa.int64()),
        ("authored_file_count", pa.int64()),
        ("codegen_ratio", pa.float64()),
        # SLOC metrics
        ("code_lines_total", pa.int64()),
        ("code_lines_authored", pa.int64()),
        ("code_lines_generated", pa.int64()),
        # Compile time metrics (all files)
        ("compile_time_sum_ms", pa.int64()),
        ("compile_time_max_ms", pa.int64()),
        ("compile_time_mean_ms", pa.float64()),
        ("compile_time_median_ms", pa.float64()),
        ("compile_time_std_ms", pa.float64()),
        ("compile_time_p90_ms", pa.float64()),
        ("compile_time_p99_ms", pa.float64()),
        # Compile time metrics (authored files)
        ("authored_compile_time_sum_ms", pa.int64()),
        ("authored_compile_time_max_ms", pa.int64()),
        # Compile time metrics (generated files)
        ("codegen_compile_time_sum_ms", pa.int64()),
        ("codegen_compile_time_max_ms", pa.int64()),
        # Compiler phase breakdown
        ("compiler_parse_time_sum_ms", pa.float64()),
        ("compiler_template_time_sum_ms", pa.float64()),
        ("compiler_codegen_phase_sum_ms", pa.float64()),
        ("compiler_optimization_time_sum_ms", pa.float64()),
        ("compiler_total_usr_sum_ms", pa.float64()),
        ("compiler_total_sys_sum_ms", pa.float64()),
        # Header metrics
        ("header_depth_max", pa.int64()),
        ("header_depth_mean", pa.float64()),
        ("unique_headers_total", pa.int64()),
        ("total_includes_sum", pa.int64()),
        # Preprocessed size
        ("preprocessed_bytes_total", pa.int64()),
        ("preprocessed_bytes_mean", pa.float64()),
        ("expansion_ratio_mean", pa.float64()),
        # Object file metrics
        ("object_size_total_bytes", pa.int64()),
        ("object_file_count", pa.int64()),
        # Build step timing
        ("codegen_time_ms", pa.int64()),
        ("archive_time_ms", pa.int64()),
        ("link_time_ms", pa.int64()),
        ("total_build_time_ms", pa.int64()),
        # Git activity
        ("git_commit_count_total", pa.int64()),
        ("git_churn_total", pa.int64()),
        ("git_distinct_authors", pa.int64()),
        ("git_hotspot_file_count", pa.int64()),
        # Dependency graph metrics
        ("direct_dependency_count", pa.int64()),
        ("transitive_dependency_count", pa.int64()),
        ("total_dependency_count", pa.int64()),
        ("direct_dependant_count", pa.int64()),
        ("transitive_dependant_count", pa.int64()),
        ("topological_depth", pa.int64()),
        ("critical_path_contribution_ms", pa.int64()),
        ("fan_in", pa.int64()),
        ("fan_out", pa.int64()),
        ("betweenness_centrality", pa.float64()),
        # File lists
        ("source_files", pa.large_utf8()),
        ("generated_files", pa.large_utf8()),
        ("output_files", pa.large_utf8()),
    ]
)

EDGE_LIST_SCHEMA = pa.schema(
    [
        ("source_target", pa.string()),
        ("dest_target", pa.string()),
        ("is_direct", pa.bool_()),
        ("dependency_type", pa.string()),
        ("source_target_type", pa.string()),
        ("dest_target_type", pa.string()),
        ("from_dependency", pa.string()),
        ("cmake_visibility", pa.string()),
    ]
)

HEADER_EDGES_SCHEMA = pa.schema(
    [
        ("includer", pa.string()),
        ("included", pa.string()),
        ("depth", pa.int64()),
        ("source_file", pa.string()),
        ("is_system", pa.bool_()),
    ]
)

HEADER_METRICS_SCHEMA = pa.schema(
    [
        ("header_file", pa.string()),
        ("cmake_target", pa.string()),
        ("sloc", pa.int64()),
        ("source_size_bytes", pa.int64()),
        ("is_system", pa.bool_()),
    ]
)


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def distribution_stats(series: pd.Series, prefix: str) -> dict[str, float]:
    """Compute mean, median, std, p90, p99 for a numeric series."""
    if series.empty or series.isna().all():
        return {
            f"{prefix}_mean": 0.0,
            f"{prefix}_median": 0.0,
            f"{prefix}_std": 0.0,
            f"{prefix}_p90": 0.0,
            f"{prefix}_p99": 0.0,
        }
    return {
        f"{prefix}_mean": float(series.mean()),
        f"{prefix}_median": float(series.median()),
        f"{prefix}_std": float(series.std()) if len(series) > 1 else 0.0,
        f"{prefix}_p90": float(series.quantile(0.9)),
        f"{prefix}_p99": float(series.quantile(0.99)),
    }


def safe_sum(series: pd.Series) -> int:
    """Sum a series, returning 0 for empty/all-NA."""
    result = series.sum()
    return int(result) if pd.notna(result) else 0


def safe_max(series: pd.Series) -> int:
    """Max of a series, returning 0 for empty/all-NA."""
    if series.empty or series.isna().all():
        return 0
    return int(series.max())


def aggregate_file_metrics_for_target(df: pd.DataFrame) -> dict:
    """Aggregate file-level metrics for a single target.

    Takes a file_metrics DataFrame filtered to one target.
    Returns a flat dict matching TARGET_METRICS_SCHEMA field subset.
    """
    authored = df[~df["is_generated"]]
    generated = df[df["is_generated"]]

    compile_times = df["compile_time_ms"].dropna()
    dist = distribution_stats(compile_times, "compile_time")

    result = {
        # Source file counts
        "file_count": len(df),
        "codegen_file_count": len(generated),
        "authored_file_count": len(authored),
        "codegen_ratio": len(generated) / len(df) if len(df) > 0 else 0.0,
        # SLOC
        "code_lines_total": safe_sum(df["code_lines"]),
        "code_lines_authored": safe_sum(authored["code_lines"]),
        "code_lines_generated": safe_sum(generated["code_lines"]),
        # Compile time (all)
        "compile_time_sum_ms": safe_sum(compile_times),
        "compile_time_max_ms": safe_max(compile_times),
        "compile_time_mean_ms": dist["compile_time_mean"],
        "compile_time_median_ms": dist["compile_time_median"],
        "compile_time_std_ms": dist["compile_time_std"],
        "compile_time_p90_ms": dist["compile_time_p90"],
        "compile_time_p99_ms": dist["compile_time_p99"],
        # Compile time (authored)
        "authored_compile_time_sum_ms": safe_sum(authored["compile_time_ms"]),
        "authored_compile_time_max_ms": safe_max(authored["compile_time_ms"]),
        # Compile time (generated)
        "codegen_compile_time_sum_ms": safe_sum(generated["compile_time_ms"]),
        "codegen_compile_time_max_ms": safe_max(generated["compile_time_ms"]),
        # Compiler phase breakdown
        "compiler_parse_time_sum_ms": float(df["compiler_parse_time_ms"].sum()),
        "compiler_template_time_sum_ms": float(df["compiler_template_instantiation_ms"].sum()),
        "compiler_codegen_phase_sum_ms": float(df["compiler_codegen_time_ms"].sum()),
        "compiler_optimization_time_sum_ms": float(df["compiler_optimization_time_ms"].sum()),
        "compiler_total_usr_sum_ms": float(df["compiler_total_usr_ms"].sum()),
        "compiler_total_sys_sum_ms": float(df["compiler_total_sys_ms"].sum()),
        # Header metrics
        "header_depth_max": safe_max(df["header_max_depth"]),
        "header_depth_mean": float(df["header_max_depth"].mean()) if not df["header_max_depth"].isna().all() else 0.0,
        "unique_headers_total": safe_sum(df["unique_headers"]),  # approximation — true count requires set union
        "total_includes_sum": safe_sum(df["total_includes"]),
        # Preprocessed size
        "preprocessed_bytes_total": safe_sum(df["preprocessed_bytes"]),
        "preprocessed_bytes_mean": (
            float(df["preprocessed_bytes"].mean()) if not df["preprocessed_bytes"].isna().all() else 0.0
        ),
        "expansion_ratio_mean": (
            float(df["expansion_ratio"].mean()) if not df["expansion_ratio"].isna().all() else 0.0
        ),
        # Object file metrics
        "object_size_total_bytes": safe_sum(df["object_size_bytes"]),
        "object_file_count": int(df["object_size_bytes"].notna().sum()),
        # Git activity (authored files only)
        "git_commit_count_total": safe_sum(authored["git_commit_count"]),
        "git_churn_total": safe_sum(authored["git_churn"]),
        "git_distinct_authors": safe_max(authored["git_distinct_authors"]),
    }

    # Git hotspot: files with commit count > mean + 1 std
    if not authored.empty and not authored["git_commit_count"].isna().all():
        mean_commits = authored["git_commit_count"].mean()
        std_commits = authored["git_commit_count"].std() if len(authored) > 1 else 0
        threshold = mean_commits + std_commits
        result["git_hotspot_file_count"] = int((authored["git_commit_count"] > threshold).sum())
    else:
        result["git_hotspot_file_count"] = 0

    return result
