#!/usr/bin/env python3
"""Consolidate all per-file raw data into file_metrics.parquet.

Joins File API file list (spine) with ninja log, ftime report, header data,
SLOC, object file sizes, preprocessed sizes, and git history.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from build_optimiser.config import Config
from build_optimiser.metrics import FILE_METRICS_SCHEMA

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def load_json(path: Path) -> dict | list:
    if not path.exists():
        logger.warning("Missing: %s", path)
        return {}
    with open(path) as f:
        return json.load(f)


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        logger.warning("Missing: %s", path)
        return pd.DataFrame()
    return pd.read_csv(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidate file-level metrics")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    cfg = Config.from_yaml(args.config)
    raw = cfg.raw_data_dir

    # Spine: files.json from File API
    files_data = load_json(raw / "cmake_file_api" / "files.json")
    if not files_data:
        logger.error("files.json is empty or missing — cannot proceed")
        sys.exit(1)

    spine = pd.DataFrame(files_data)
    spine = spine.rename(columns={"path": "source_file", "cmake_target": "cmake_target"})
    # Ensure required columns
    if "is_generated" not in spine.columns:
        spine["is_generated"] = False
    if "language" not in spine.columns:
        spine["language"] = ""
    spine = spine[["source_file", "cmake_target", "is_generated", "language"]].copy()
    logger.info("Spine: %d files", len(spine))

    # Ninja log compile times
    ninja_df = load_csv(raw / "ninja_log.csv")
    if not ninja_df.empty:
        compile_times = ninja_df[ninja_df["step_type"] == "compile"][["source_file", "duration_ms"]].copy()
        compile_times = compile_times.rename(columns={"duration_ms": "compile_time_ms"})
        # Deduplicate — keep the last entry per source file
        compile_times = compile_times.drop_duplicates(subset="source_file", keep="last")
        spine = spine.merge(compile_times, on="source_file", how="left")
    else:
        spine["compile_time_ms"] = pd.NA

    # ftime report
    ftime_data = load_json(raw / "ftime_report.json")
    ftime_rows = []
    for source_file, data in ftime_data.items():
        phases = data.get("phases", {})
        ftime_rows.append({
            "source_file": source_file,
            "gcc_parse_time_ms": phases.get("phase parsing", 0) * 1000,
            "gcc_template_instantiation_ms": phases.get("phase lang. deferred", 0) * 1000,
            "gcc_codegen_time_ms": phases.get("phase opt and generate", 0) * 1000,
            "gcc_optimization_time_ms": phases.get("phase opt and generate", 0) * 1000,
            "gcc_total_time_ms": data.get("wall_total_ms", 0),
        })
    if ftime_rows:
        ftime_df = pd.DataFrame(ftime_rows)
        spine = spine.merge(ftime_df, on="source_file", how="left")
    else:
        for col in ["gcc_parse_time_ms", "gcc_template_instantiation_ms",
                     "gcc_codegen_time_ms", "gcc_optimization_time_ms", "gcc_total_time_ms"]:
            spine[col] = pd.NA

    # Header data
    header_data = load_json(raw / "header_data.json")
    header_rows = []
    for source_file, data in header_data.items():
        header_rows.append({
            "source_file": source_file,
            "header_max_depth": data.get("max_include_depth", 0),
            "unique_headers": data.get("unique_headers", 0),
            "total_includes": data.get("total_includes", 0),
            "header_tree": json.dumps(data.get("header_tree", [])),
        })
    if header_rows:
        header_df = pd.DataFrame(header_rows)
        spine = spine.merge(header_df, on="source_file", how="left")
    else:
        for col in ["header_max_depth", "unique_headers", "total_includes"]:
            spine[col] = pd.NA
        spine["header_tree"] = "[]"

    # SLOC
    sloc_df = load_csv(raw / "sloc.csv")
    if not sloc_df.empty:
        sloc_cols = sloc_df[["source_file", "code_lines", "blank_lines", "comment_lines", "source_size_bytes"]].copy()
        sloc_cols = sloc_cols.drop_duplicates(subset="source_file", keep="last")
        spine = spine.merge(sloc_cols, on="source_file", how="left")
    else:
        for col in ["code_lines", "blank_lines", "comment_lines", "source_size_bytes"]:
            spine[col] = pd.NA

    # Object file sizes
    obj_df = load_csv(raw / "object_files.csv")
    if not obj_df.empty:
        obj_sizes = obj_df[["source_file", "object_size_bytes"]].copy()
        obj_sizes = obj_sizes[obj_sizes["source_file"] != ""]
        obj_sizes = obj_sizes.drop_duplicates(subset="source_file", keep="last")
        spine = spine.merge(obj_sizes, on="source_file", how="left")
    else:
        spine["object_size_bytes"] = pd.NA

    # Preprocessed size
    preproc_df = load_csv(raw / "preprocessed_size.csv")
    if not preproc_df.empty:
        preproc_cols = preproc_df[["source_file", "preprocessed_bytes"]].copy()
        preproc_cols = preproc_cols.drop_duplicates(subset="source_file", keep="last")
        spine = spine.merge(preproc_cols, on="source_file", how="left")
    else:
        spine["preprocessed_bytes"] = pd.NA

    # Git history summary
    git_df = load_csv(raw / "git_history_summary.csv")
    if not git_df.empty:
        git_cols = git_df.rename(columns={
            "commit_count": "git_commit_count",
            "total_lines_added": "git_lines_added",
            "total_lines_deleted": "git_lines_deleted",
            "total_churn": "git_churn",
            "distinct_authors": "git_distinct_authors",
            "first_change_date": "git_first_change_date",
            "last_change_date": "git_last_change_date",
        })
        git_cols = git_cols[["source_file", "git_commit_count", "git_lines_added",
                             "git_lines_deleted", "git_churn", "git_distinct_authors",
                             "git_first_change_date", "git_last_change_date"]].copy()
        git_cols = git_cols.drop_duplicates(subset="source_file", keep="last")
        spine = spine.merge(git_cols, on="source_file", how="left")
    else:
        for col in ["git_commit_count", "git_lines_added", "git_lines_deleted",
                     "git_churn", "git_distinct_authors", "git_first_change_date",
                     "git_last_change_date"]:
            spine[col] = pd.NA

    # Fill NA for generated files' git fields with 0
    gen_mask = spine["is_generated"] == True  # noqa: E712
    for col in ["git_commit_count", "git_lines_added", "git_lines_deleted",
                "git_churn", "git_distinct_authors"]:
        if col in spine.columns:
            spine.loc[gen_mask, col] = spine.loc[gen_mask, col].fillna(0)

    # Ensure git_first_change_date is null for generated files
    if "git_first_change_date" in spine.columns:
        spine.loc[gen_mask, "git_first_change_date"] = None

    # Derived columns
    spine["expansion_ratio"] = spine["preprocessed_bytes"] / spine["source_size_bytes"].replace(0, pd.NA)
    spine["compile_rate_lines_per_sec"] = spine["code_lines"] / (spine["compile_time_ms"] / 1000).replace(0, pd.NA)
    spine["object_efficiency"] = spine["object_size_bytes"] / spine["code_lines"].replace(0, pd.NA)

    # Fill header_tree NA
    if "header_tree" in spine.columns:
        spine["header_tree"] = spine["header_tree"].fillna("[]")

    # Write parquet
    cfg.processed_data_dir.mkdir(parents=True, exist_ok=True)
    output_path = cfg.processed_data_dir / "file_metrics.parquet"

    # Ensure all schema columns exist
    for field in FILE_METRICS_SCHEMA:
        if field.name not in spine.columns:
            spine[field.name] = pd.NA

    # Reorder to match schema
    spine = spine[[f.name for f in FILE_METRICS_SCHEMA]]

    table = pa.Table.from_pandas(spine, schema=FILE_METRICS_SCHEMA, preserve_index=False)
    pq.write_table(table, output_path)
    logger.info("Wrote %s (%d rows, %d columns)", output_path, len(spine), len(spine.columns))


if __name__ == "__main__":
    main()
