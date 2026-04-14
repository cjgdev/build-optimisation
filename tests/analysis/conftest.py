"""Shared fixtures for tests/analysis/.

Builds a minimal but realistic ``processed/`` directory that the ad-hoc
analysis scripts can load. Validation is skipped via ``--no-validate`` in
the script invocations, so we only need to provide the columns each script
actually reads.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Graph shape:
#
#     exe ─▶ libA ─▶ libCore
#       ╲
#        ╲─▶ libB ─▶ libCore
#
# Three library targets and one executable, forming a diamond on ``libCore``.
# ---------------------------------------------------------------------------


def _target_metrics() -> pd.DataFrame:
    rows = [
        {
            "cmake_target": "exe",
            "target_type": "executable",
            "output_artifact": "exe",
            "source_directory": "/src/exe",
            "file_count": 1,
            "authored_file_count": 1,
            "codegen_file_count": 0,
            "codegen_ratio": 0.0,
            "code_lines_total": 80,
            "compile_time_sum_ms": 300,
            "compile_time_max_ms": 300,
            "compile_time_mean_ms": 300.0,
            "compile_time_median_ms": 300.0,
            "compile_time_std_ms": 0.0,
            "compile_time_p90_ms": 300.0,
            "compile_time_p99_ms": 300.0,
            "authored_compile_time_sum_ms": 300,
            "authored_compile_time_max_ms": 300,
            "codegen_compile_time_sum_ms": 0,
            "codegen_compile_time_max_ms": 0,
            "compiler_parse_time_sum_ms": 100.0,
            "compiler_template_time_sum_ms": 80.0,
            "compiler_codegen_phase_sum_ms": 60.0,
            "compiler_optimization_time_sum_ms": 60.0,
            "compiler_total_usr_sum_ms": 280.0,
            "compiler_total_sys_sum_ms": 20.0,
            "header_depth_max": 5,
            "header_depth_mean": 3.0,
            "unique_headers_total": 20,
            "total_includes_sum": 40,
            "preprocessed_bytes_total": 100_000,
            "preprocessed_bytes_mean": 100_000.0,
            "expansion_ratio_mean": 50.0,
            "object_size_total_bytes": 5_000,
            "object_file_count": 1,
            "codegen_time_ms": 0,
            "archive_time_ms": 0,
            "link_time_ms": 200,
            "total_build_time_ms": 500,
            "git_commit_count_total": 12,
            "git_churn_total": 300,
            "git_distinct_authors": 3,
            "git_hotspot_file_count": 0,
            "direct_dependency_count": 2,
            "transitive_dependency_count": 1,
            "total_dependency_count": 3,
            "direct_dependant_count": 0,
            "transitive_dependant_count": 0,
            "topological_depth": 3,
            "critical_path_contribution_ms": 500,
            "fan_in": 0,
            "fan_out": 2,
            "betweenness_centrality": 0.0,
        },
        {
            "cmake_target": "libA",
            "target_type": "static_library",
            "output_artifact": "libA.a",
            "source_directory": "/src/libA",
            "file_count": 3,
            "authored_file_count": 3,
            "codegen_file_count": 0,
            "codegen_ratio": 0.0,
            "code_lines_total": 600,
            "compile_time_sum_ms": 2400,
            "compile_time_max_ms": 1500,
            "compile_time_mean_ms": 800.0,
            "compile_time_median_ms": 600.0,
            "compile_time_std_ms": 700.0,
            "compile_time_p90_ms": 1400.0,
            "compile_time_p99_ms": 1500.0,
            "authored_compile_time_sum_ms": 2400,
            "authored_compile_time_max_ms": 1500,
            "codegen_compile_time_sum_ms": 0,
            "codegen_compile_time_max_ms": 0,
            "compiler_parse_time_sum_ms": 800.0,
            "compiler_template_time_sum_ms": 900.0,
            "compiler_codegen_phase_sum_ms": 400.0,
            "compiler_optimization_time_sum_ms": 400.0,
            "compiler_total_usr_sum_ms": 2200.0,
            "compiler_total_sys_sum_ms": 200.0,
            "header_depth_max": 8,
            "header_depth_mean": 5.0,
            "unique_headers_total": 60,
            "total_includes_sum": 120,
            "preprocessed_bytes_total": 800_000,
            "preprocessed_bytes_mean": 266_666.6,
            "expansion_ratio_mean": 80.0,
            "object_size_total_bytes": 30_000,
            "object_file_count": 3,
            "codegen_time_ms": 0,
            "archive_time_ms": 100,
            "link_time_ms": 0,
            "total_build_time_ms": 2500,
            "git_commit_count_total": 48,
            "git_churn_total": 1500,
            "git_distinct_authors": 2,
            "git_hotspot_file_count": 1,
            "direct_dependency_count": 1,
            "transitive_dependency_count": 0,
            "total_dependency_count": 1,
            "direct_dependant_count": 1,
            "transitive_dependant_count": 1,
            "topological_depth": 2,
            "critical_path_contribution_ms": 2500,
            "fan_in": 1,
            "fan_out": 1,
            "betweenness_centrality": 0.25,
        },
        {
            "cmake_target": "libB",
            "target_type": "static_library",
            "output_artifact": "libB.a",
            "source_directory": "/src/libB",
            "file_count": 2,
            "authored_file_count": 1,
            "codegen_file_count": 1,
            "codegen_ratio": 0.5,
            "code_lines_total": 250,
            "compile_time_sum_ms": 900,
            "compile_time_max_ms": 700,
            "compile_time_mean_ms": 450.0,
            "compile_time_median_ms": 450.0,
            "compile_time_std_ms": 350.0,
            "compile_time_p90_ms": 680.0,
            "compile_time_p99_ms": 700.0,
            "authored_compile_time_sum_ms": 200,
            "authored_compile_time_max_ms": 200,
            "codegen_compile_time_sum_ms": 700,
            "codegen_compile_time_max_ms": 700,
            "compiler_parse_time_sum_ms": 300.0,
            "compiler_template_time_sum_ms": 150.0,
            "compiler_codegen_phase_sum_ms": 200.0,
            "compiler_optimization_time_sum_ms": 200.0,
            "compiler_total_usr_sum_ms": 820.0,
            "compiler_total_sys_sum_ms": 80.0,
            "header_depth_max": 4,
            "header_depth_mean": 2.5,
            "unique_headers_total": 25,
            "total_includes_sum": 40,
            "preprocessed_bytes_total": 200_000,
            "preprocessed_bytes_mean": 100_000.0,
            "expansion_ratio_mean": 40.0,
            "object_size_total_bytes": 12_000,
            "object_file_count": 2,
            "codegen_time_ms": 50,
            "archive_time_ms": 50,
            "link_time_ms": 0,
            "total_build_time_ms": 1000,
            "git_commit_count_total": 6,
            "git_churn_total": 90,
            "git_distinct_authors": 1,
            "git_hotspot_file_count": 0,
            "direct_dependency_count": 1,
            "transitive_dependency_count": 0,
            "total_dependency_count": 1,
            "direct_dependant_count": 1,
            "transitive_dependant_count": 1,
            "topological_depth": 2,
            "critical_path_contribution_ms": 0,
            "fan_in": 1,
            "fan_out": 1,
            "betweenness_centrality": 0.1,
        },
        {
            "cmake_target": "libCore",
            "target_type": "static_library",
            "output_artifact": "libCore.a",
            "source_directory": "/src/core",
            "file_count": 4,
            "authored_file_count": 4,
            "codegen_file_count": 0,
            "codegen_ratio": 0.0,
            "code_lines_total": 1200,
            "compile_time_sum_ms": 4000,
            "compile_time_max_ms": 2200,
            "compile_time_mean_ms": 1000.0,
            "compile_time_median_ms": 900.0,
            "compile_time_std_ms": 500.0,
            "compile_time_p90_ms": 2000.0,
            "compile_time_p99_ms": 2200.0,
            "authored_compile_time_sum_ms": 4000,
            "authored_compile_time_max_ms": 2200,
            "codegen_compile_time_sum_ms": 0,
            "codegen_compile_time_max_ms": 0,
            "compiler_parse_time_sum_ms": 1400.0,
            "compiler_template_time_sum_ms": 1200.0,
            "compiler_codegen_phase_sum_ms": 700.0,
            "compiler_optimization_time_sum_ms": 700.0,
            "compiler_total_usr_sum_ms": 3600.0,
            "compiler_total_sys_sum_ms": 400.0,
            "header_depth_max": 10,
            "header_depth_mean": 6.0,
            "unique_headers_total": 120,
            "total_includes_sum": 240,
            "preprocessed_bytes_total": 2_000_000,
            "preprocessed_bytes_mean": 500_000.0,
            "expansion_ratio_mean": 100.0,
            "object_size_total_bytes": 60_000,
            "object_file_count": 4,
            "codegen_time_ms": 0,
            "archive_time_ms": 150,
            "link_time_ms": 0,
            "total_build_time_ms": 4150,
            "git_commit_count_total": 90,
            "git_churn_total": 4000,
            "git_distinct_authors": 4,
            "git_hotspot_file_count": 2,
            "direct_dependency_count": 0,
            "transitive_dependency_count": 0,
            "total_dependency_count": 0,
            "direct_dependant_count": 2,
            "transitive_dependant_count": 3,
            "topological_depth": 1,
            "critical_path_contribution_ms": 4150,
            "fan_in": 2,
            "fan_out": 0,
            "betweenness_centrality": 0.5,
        },
    ]
    return pd.DataFrame(rows)


def _edge_list() -> pd.DataFrame:
    rows = [
        ("exe", "libA", True, "direct", "executable", "static_library"),
        ("exe", "libB", True, "direct", "executable", "static_library"),
        ("libA", "libCore", True, "direct", "static_library", "static_library"),
        ("libB", "libCore", True, "direct", "static_library", "static_library"),
        ("exe", "libCore", False, "transitive", "executable", "static_library"),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "source_target",
            "dest_target",
            "is_direct",
            "dependency_type",
            "source_target_type",
            "dest_target_type",
        ],
    )


def _file_metrics() -> pd.DataFrame:
    rows = [
        # exe
        ("/src/exe/main.cpp", "exe", False, 300, 80, 5_000, 100_000, 12, 300, 266.7),
        # libA — one slow templated file, two smaller ones
        ("/src/libA/a1.cpp", "libA", False, 1500, 300, 20_000, 600_000, 48, 1200, 200.0),
        ("/src/libA/a2.cpp", "libA", False, 500, 150, 8_000, 120_000, 0, 0, 300.0),
        ("/src/libA/a3.cpp", "libA", False, 400, 150, 7_000, 80_000, 0, 0, 375.0),
        # libB — one authored, one generated
        ("/src/libB/b1.cpp", "libB", False, 200, 150, 4_000, 80_000, 6, 90, 750.0),
        ("/build/libB/gen.pb.cc", "libB", True, 700, 100, 40_000, 120_000, 0, 0, 142.9),
        # libCore — one huge file
        ("/src/core/c1.cpp", "libCore", False, 2200, 500, 30_000, 900_000, 90, 4000, 227.3),
        ("/src/core/c2.cpp", "libCore", False, 700, 300, 12_000, 400_000, 0, 0, 428.6),
        ("/src/core/c3.cpp", "libCore", False, 600, 250, 10_000, 400_000, 0, 0, 416.7),
        ("/src/core/c4.cpp", "libCore", False, 500, 150, 8_000, 300_000, 0, 0, 300.0),
    ]
    df = pd.DataFrame(
        rows,
        columns=[
            "source_file",
            "cmake_target",
            "is_generated",
            "compile_time_ms",
            "code_lines",
            "source_size_bytes",
            "preprocessed_bytes",
            "git_commit_count",
            "git_churn",
            "compile_rate_lines_per_sec",
        ],
    )
    df["language"] = "CXX"
    # Fill extra columns read by various scripts
    df["compiler_parse_time_ms"] = df["compile_time_ms"] * 0.35
    df["compiler_template_instantiation_ms"] = df["compile_time_ms"] * 0.3
    df["compiler_codegen_time_ms"] = df["compile_time_ms"] * 0.2
    df["compiler_optimization_time_ms"] = df["compile_time_ms"] * 0.15
    df["compiler_total_time_ms"] = df["compile_time_ms"].astype(float)
    df["compiler_total_usr_ms"] = df["compile_time_ms"] * 0.9
    df["compiler_total_sys_ms"] = df["compile_time_ms"] * 0.1
    df["blank_lines"] = (df["code_lines"] * 0.1).round().astype(int)
    df["comment_lines"] = (df["code_lines"] * 0.1).round().astype(int)
    df["header_max_depth"] = 5
    df["unique_headers"] = 20
    df["total_includes"] = 40
    df["header_tree"] = ""
    df["object_size_bytes"] = (df["source_size_bytes"] * 0.6).astype(int)
    df["git_lines_added"] = (df["git_churn"] * 0.6).astype(int)
    df["git_lines_deleted"] = df["git_churn"] - df["git_lines_added"]
    df["git_distinct_authors"] = df["git_commit_count"].clip(upper=3)
    df["git_last_change_date"] = "2026-04-01"
    df["expansion_ratio"] = df["preprocessed_bytes"] / df["source_size_bytes"]
    df["object_efficiency"] = df["object_size_bytes"] / df["code_lines"]
    return df


def _git_commit_log() -> pd.DataFrame:
    records = []
    commit = 0
    ts = pd.Timestamp("2026-01-01")
    # libCore: dominated by alice, some bob, a tiny bit of carol/dan
    for i in range(60):
        records.append((f"h{commit}", ts, "alice@example.com", "/src/core/c1.cpp", 20, 5))
        commit += 1
    for i in range(20):
        records.append((f"h{commit}", ts, "bob@example.com", "/src/core/c2.cpp", 10, 2))
        commit += 1
    for i in range(5):
        records.append((f"h{commit}", ts, "carol@example.com", "/src/core/c3.cpp", 5, 1))
        commit += 1
    for i in range(5):
        records.append((f"h{commit}", ts, "dan@example.com", "/src/core/c4.cpp", 5, 1))
        commit += 1
    # libA: concentrated on bob (sole-owner risk)
    for i in range(48):
        records.append((f"h{commit}", ts, "bob@example.com", "/src/libA/a1.cpp", 10, 2))
        commit += 1
    # libB authored: carol only
    for i in range(6):
        records.append((f"h{commit}", ts, "carol@example.com", "/src/libB/b1.cpp", 3, 1))
        commit += 1
    # exe: mixed
    for i in range(12):
        records.append((f"h{commit}", ts + pd.Timedelta(days=i), "alice@example.com", "/src/exe/main.cpp", 4, 1))
        commit += 1
    return pd.DataFrame(
        records,
        columns=["commit_hash", "timestamp", "contributor", "source_file", "lines_added", "lines_deleted"],
    )


def _contributor_target_commits() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "contributor": [
                "alice@example.com",
                "bob@example.com",
                "carol@example.com",
                "dan@example.com",
                "bob@example.com",
                "carol@example.com",
                "alice@example.com",
            ],
            "cmake_target": ["libCore", "libCore", "libCore", "libCore", "libA", "libB", "exe"],
            "commit_count": [60, 20, 5, 5, 48, 6, 12],
        }
    )


def _header_edges() -> pd.DataFrame:
    rows = [
        ("/src/exe/main.cpp", "/src/core/types.h", 1, "/src/exe/main.cpp", False),
        ("/src/libA/a1.cpp", "/src/core/types.h", 1, "/src/libA/a1.cpp", False),
        ("/src/libA/a1.cpp", "/src/libA/a.h", 1, "/src/libA/a1.cpp", False),
        ("/src/libA/a.h", "/src/core/types.h", 2, "/src/libA/a1.cpp", False),
        ("/src/libA/a2.cpp", "/src/libA/a.h", 1, "/src/libA/a2.cpp", False),
        ("/src/libA/a3.cpp", "/src/libA/a.h", 1, "/src/libA/a3.cpp", False),
        ("/src/libB/b1.cpp", "/src/core/types.h", 1, "/src/libB/b1.cpp", False),
        ("/src/core/c1.cpp", "/src/core/types.h", 1, "/src/core/c1.cpp", False),
        ("/src/core/c2.cpp", "/src/core/types.h", 1, "/src/core/c2.cpp", False),
        ("/src/core/c3.cpp", "/src/core/types.h", 1, "/src/core/c3.cpp", False),
        ("/src/core/c4.cpp", "/src/core/types.h", 1, "/src/core/c4.cpp", False),
    ]
    return pd.DataFrame(rows, columns=["includer", "included", "depth", "source_file", "is_system"])


def _header_metrics() -> pd.DataFrame:
    rows = [
        ("/src/core/types.h", "libCore", 200, 8_000, False),
        ("/src/libA/a.h", "libA", 120, 4_000, False),
    ]
    return pd.DataFrame(rows, columns=["header_file", "cmake_target", "sloc", "source_size_bytes", "is_system"])


@pytest.fixture
def processed_dir(tmp_path: Path) -> Path:
    """Materialise a minimal processed/ directory with all required parquet files."""
    out = tmp_path / "processed"
    out.mkdir()
    _target_metrics().to_parquet(out / "target_metrics.parquet")
    _edge_list().to_parquet(out / "edge_list.parquet")
    _file_metrics().to_parquet(out / "file_metrics.parquet")
    _git_commit_log().to_parquet(out / "git_commit_log.parquet")
    _contributor_target_commits().to_parquet(out / "contributor_target_commits.parquet")
    _header_edges().to_parquet(out / "header_edges.parquet")
    _header_metrics().to_parquet(out / "header_metrics.parquet")
    return out
