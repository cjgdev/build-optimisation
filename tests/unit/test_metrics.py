"""Tests for build_optimiser.metrics."""

import numpy as np
import pandas as pd
import pyarrow as pa

from build_optimiser.metrics import (
    EDGE_LIST_SCHEMA,
    FILE_METRICS_SCHEMA,
    TARGET_METRICS_SCHEMA,
    aggregate_file_metrics_for_target,
    canonicalise_path,
    distribution_stats,
)


class TestCanonicalisePath:
    def test_relative_path_resolved(self):
        result = canonicalise_path("src/main.cpp", "/project")
        assert result.startswith("/")
        assert result.endswith("src/main.cpp")

    def test_absolute_path_passthrough(self):
        result = canonicalise_path("/absolute/path.cpp", "/base")
        assert result == "/absolute/path.cpp"


class TestDistributionStats:
    def test_basic_stats(self):
        series = pd.Series([10, 20, 30, 40, 50])
        result = distribution_stats(series, "test")
        assert result["test_mean"] == 30.0
        assert result["test_median"] == 30.0
        assert result["test_p90"] >= 40.0
        assert result["test_p99"] >= 49.0

    def test_empty_series(self):
        series = pd.Series([], dtype=float)
        result = distribution_stats(series, "test")
        assert result["test_mean"] == 0.0
        assert result["test_std"] == 0.0

    def test_single_value(self):
        series = pd.Series([42.0])
        result = distribution_stats(series, "test")
        assert result["test_mean"] == 42.0
        assert result["test_std"] == 0.0


class TestAggregateFileMetrics:
    def test_basic_aggregation(self):
        df = pd.DataFrame({
            "source_file": ["a.cpp", "b.cpp", "gen.cpp", "gen2.cpp", "gen3.cpp"],
            "cmake_target": ["t"] * 5,
            "is_generated": [False, False, True, True, True],
            "compile_time_ms": [100, 200, 50, 60, 70],
            "code_lines": [500, 300, 100, 80, 120],
            "gcc_parse_time_ms": [10, 20, 5, 5, 5],
            "gcc_template_instantiation_ms": [5, 10, 2, 2, 2],
            "gcc_codegen_time_ms": [8, 15, 3, 3, 3],
            "gcc_optimization_time_ms": [12, 25, 4, 4, 4],
            "header_max_depth": [5, 8, 3, 3, 3],
            "unique_headers": [20, 30, 10, 10, 10],
            "total_includes": [50, 80, 20, 20, 20],
            "preprocessed_bytes": [10000, 20000, 5000, 5000, 5000],
            "source_size_bytes": [2000, 3000, 1000, 1000, 1000],
            "expansion_ratio": [5.0, 6.67, 5.0, 5.0, 5.0],
            "object_size_bytes": [4000, 6000, 2000, 2000, 2000],
            "git_commit_count": [10, 5, 0, 0, 0],
            "git_churn": [100, 50, 0, 0, 0],
            "git_distinct_authors": [3, 2, 0, 0, 0],
        })

        result = aggregate_file_metrics_for_target(df)

        assert result["file_count"] == 5
        assert result["codegen_file_count"] == 3
        assert result["authored_file_count"] == 2
        assert result["codegen_ratio"] == 3 / 5

        assert result["code_lines_total"] == 1100
        assert result["code_lines_authored"] == 800
        assert result["code_lines_generated"] == 300

        assert result["compile_time_sum_ms"] == 480
        assert result["compile_time_max_ms"] == 200

        assert result["authored_compile_time_sum_ms"] == 300
        assert result["codegen_compile_time_sum_ms"] == 180

        assert result["git_commit_count_total"] == 15
        assert result["git_churn_total"] == 150
        assert result["git_distinct_authors"] == 3

    def test_empty_dataframe(self):
        df = pd.DataFrame({
            "source_file": pd.Series([], dtype=str),
            "cmake_target": pd.Series([], dtype=str),
            "is_generated": pd.Series([], dtype=bool),
            "compile_time_ms": pd.Series([], dtype=float),
            "code_lines": pd.Series([], dtype=float),
            "gcc_parse_time_ms": pd.Series([], dtype=float),
            "gcc_template_instantiation_ms": pd.Series([], dtype=float),
            "gcc_codegen_time_ms": pd.Series([], dtype=float),
            "gcc_optimization_time_ms": pd.Series([], dtype=float),
            "header_max_depth": pd.Series([], dtype=float),
            "unique_headers": pd.Series([], dtype=float),
            "total_includes": pd.Series([], dtype=float),
            "preprocessed_bytes": pd.Series([], dtype=float),
            "source_size_bytes": pd.Series([], dtype=float),
            "expansion_ratio": pd.Series([], dtype=float),
            "object_size_bytes": pd.Series([], dtype=float),
            "git_commit_count": pd.Series([], dtype=float),
            "git_churn": pd.Series([], dtype=float),
            "git_distinct_authors": pd.Series([], dtype=float),
        })
        result = aggregate_file_metrics_for_target(df)
        assert result["file_count"] == 0
        assert result["codegen_ratio"] == 0.0


class TestSchemas:
    def test_file_metrics_schema_valid(self):
        assert isinstance(FILE_METRICS_SCHEMA, pa.Schema)
        assert len(FILE_METRICS_SCHEMA) >= 28

    def test_target_metrics_schema_valid(self):
        assert isinstance(TARGET_METRICS_SCHEMA, pa.Schema)
        assert len(TARGET_METRICS_SCHEMA) >= 50

    def test_edge_list_schema_valid(self):
        assert isinstance(EDGE_LIST_SCHEMA, pa.Schema)
        assert len(EDGE_LIST_SCHEMA) == 7

    def test_schemas_have_no_duplicate_fields(self):
        for schema in [FILE_METRICS_SCHEMA, TARGET_METRICS_SCHEMA, EDGE_LIST_SCHEMA]:
            names = [f.name for f in schema]
            assert len(names) == len(set(names)), f"Duplicate fields in schema: {names}"
