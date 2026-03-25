#!/usr/bin/env python3
"""Join all per-file data into a single file-level DataFrame."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from build_optimiser.config import load_config
from build_optimiser.metrics import canonicalise_path, merge_codegen_into_file_metrics


def main() -> None:
    cfg = load_config()
    raw_dir = Path(cfg["raw_data_dir"])
    processed_dir = Path(cfg["processed_data_dir"])
    processed_dir.mkdir(parents=True, exist_ok=True)
    source_dir = cfg["source_dir"]

    # Load raw data files
    # 1. Ninja log (compile times)
    ninja_log_path = raw_dir / "ninja_log.tsv"
    if ninja_log_path.exists():
        ninja_df = pd.read_csv(ninja_log_path, sep="\t")
        # Only keep .o compile entries (not link steps)
        ninja_df = ninja_df[ninja_df["target_path"].str.endswith(".o")]
        ninja_df = ninja_df[["source_file", "cmake_target", "wall_clock_ms"]].rename(
            columns={"wall_clock_ms": "compile_time_ms"}
        )
    else:
        ninja_df = pd.DataFrame(columns=["source_file", "cmake_target", "compile_time_ms"])

    # 2. SLOC
    sloc_path = raw_dir / "sloc.csv"
    if sloc_path.exists():
        sloc_df = pd.read_csv(sloc_path)
        sloc_df = sloc_df[["source_file", "code_lines", "blank_lines", "comment_lines"]]
    else:
        sloc_df = pd.DataFrame(columns=["source_file", "code_lines", "blank_lines", "comment_lines"])

    # 3. Header depth
    header_path = raw_dir / "header_depth.csv"
    if header_path.exists():
        header_df = pd.read_csv(header_path)
        header_df = header_df[["source_file", "max_depth", "unique_headers", "total_includes"]].rename(
            columns={"max_depth": "header_max_depth"}
        )
    else:
        header_df = pd.DataFrame(columns=["source_file", "header_max_depth", "unique_headers", "total_includes"])

    # 4. Preprocessed size
    preproc_path = raw_dir / "preprocessed_size.csv"
    if preproc_path.exists():
        preproc_df = pd.read_csv(preproc_path)
        preproc_df = preproc_df[["source_file", "preprocessed_bytes"]]
    else:
        preproc_df = pd.DataFrame(columns=["source_file", "preprocessed_bytes"])

    # 5. Object files
    obj_path = raw_dir / "object_files.csv"
    if obj_path.exists():
        obj_df = pd.read_csv(obj_path)
        # We need to map object files back to source files
        # For now, aggregate by target (file-level mapping done via cmake_target)
        obj_by_target = obj_df.groupby("cmake_target").agg(
            object_size_bytes=("size_bytes", "sum")
        ).reset_index()
    else:
        obj_by_target = pd.DataFrame(columns=["cmake_target", "object_size_bytes"])

    # 6. Git history
    git_path = raw_dir / "git_history.csv"
    if git_path.exists():
        git_df = pd.read_csv(git_path)
        # Canonicalise git paths (relative to source_dir)
        git_df["source_file"] = git_df["source_file"].apply(
            lambda p: canonicalise_path(p, source_dir)
        )
        git_df = git_df.rename(columns={
            "commit_count": "git_commit_count",
            "lines_added": "git_lines_added",
            "lines_deleted": "git_lines_deleted",
        })
    else:
        git_df = pd.DataFrame(columns=["source_file", "git_commit_count", "git_lines_added", "git_lines_deleted"])

    # Canonicalise all source_file paths
    for df in [ninja_df, sloc_df, header_df, preproc_df]:
        if "source_file" in df.columns and not df.empty:
            df["source_file"] = df["source_file"].apply(
                lambda p: canonicalise_path(p, source_dir) if pd.notna(p) and p else p
            )

    # Start with ninja_df as the base (it has source_file and cmake_target)
    result = ninja_df.copy()

    # Left join all other file-level data
    for df in [sloc_df, header_df, preproc_df, git_df]:
        if not df.empty and "source_file" in df.columns:
            result = result.merge(df, on="source_file", how="left")

    # Join object size by target
    if not obj_by_target.empty and "cmake_target" in result.columns:
        result = result.merge(obj_by_target, on="cmake_target", how="left")

    # Join codegen inventory data
    codegen_path = raw_dir / "codegen_inventory.csv"
    if codegen_path.exists():
        codegen_df = pd.read_csv(codegen_path)
        result = merge_codegen_into_file_metrics(result, codegen_df, source_dir)
        gen_count = result["is_generated"].sum()
        print(f"Codegen: {gen_count} generated files out of {len(result)} total")
    else:
        result["is_generated"] = False
        result["generator"] = None
        result["generator_input"] = None
        result["gen_time_ms"] = None

    # Fill NaN with 0 for numeric columns (skip string/bool codegen columns)
    numeric_cols = result.select_dtypes(include="number").columns
    result[numeric_cols] = result[numeric_cols].fillna(0).astype(int)

    # Write output
    output_path = processed_dir / "file_metrics.parquet"
    result.to_parquet(output_path, index=False)
    print(f"Wrote {len(result)} rows to {output_path}")
    print(f"Columns: {list(result.columns)}")


if __name__ == "__main__":
    main()
