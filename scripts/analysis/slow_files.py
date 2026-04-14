#!/usr/bin/env python3
"""Surface slow / pathological source files.

Question answered
-----------------
"Which individual translation units are disproportionately expensive to
compile, and is it parsing, template instantiation, codegen, or
preprocessor blowup that's responsible?"

Ranks files four ways:

* ``slowest`` — highest raw ``compile_time_ms``.
* ``template_heavy`` — highest template instantiation fraction.
* ``preprocessor_bloat`` — largest preprocessed output per line of source.
* ``low_throughput`` — lowest compile rate (lines/sec) above a size floor.

Attributes consumed (file_metrics.parquet):
    source_file, cmake_target, is_generated, compile_time_ms,
    compiler_parse_time_ms, compiler_template_instantiation_ms,
    compiler_codegen_time_ms, code_lines, preprocessed_bytes,
    expansion_ratio, compile_rate_lines_per_sec.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.analysis._common import add_dataset_args, add_output_args, emit, load_dataset  # noqa: E402


def _slowest(fm: pd.DataFrame) -> pd.DataFrame:
    cols = ["source_file", "cmake_target", "is_generated", "compile_time_ms", "code_lines", "expansion_ratio"]
    return fm.sort_values("compile_time_ms", ascending=False)[[c for c in cols if c in fm.columns]].reset_index(
        drop=True
    )


def _template_heavy(fm: pd.DataFrame) -> pd.DataFrame:
    df = fm.copy()
    tpl = df["compiler_template_instantiation_ms"].fillna(0)
    tot = df["compiler_total_time_ms"].fillna(0).replace(0, pd.NA)
    df["template_fraction"] = (tpl / tot).astype(float).fillna(0.0)
    df = df[df["compile_time_ms"].fillna(0) > 0]
    cols = [
        "source_file",
        "cmake_target",
        "compile_time_ms",
        "compiler_template_instantiation_ms",
        "compiler_parse_time_ms",
        "compiler_codegen_time_ms",
        "template_fraction",
    ]
    return df.sort_values(["template_fraction", "compiler_template_instantiation_ms"], ascending=[False, False])[
        [c for c in cols if c in df.columns]
    ].reset_index(drop=True)


def _preprocessor_bloat(fm: pd.DataFrame, min_source_bytes: int) -> pd.DataFrame:
    df = fm[fm["source_size_bytes"].fillna(0) >= min_source_bytes].copy()
    cols = [
        "source_file",
        "cmake_target",
        "code_lines",
        "source_size_bytes",
        "preprocessed_bytes",
        "expansion_ratio",
        "compile_time_ms",
    ]
    return df.sort_values("expansion_ratio", ascending=False)[[c for c in cols if c in df.columns]].reset_index(
        drop=True
    )


def _low_throughput(fm: pd.DataFrame, min_code_lines: int) -> pd.DataFrame:
    df = fm[fm["code_lines"].fillna(0) >= min_code_lines].copy()
    df = df[df["compile_time_ms"].fillna(0) > 0]
    cols = [
        "source_file",
        "cmake_target",
        "code_lines",
        "compile_time_ms",
        "compile_rate_lines_per_sec",
        "compiler_template_instantiation_ms",
    ]
    return df.sort_values("compile_rate_lines_per_sec", ascending=True)[
        [c for c in cols if c in df.columns]
    ].reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_dataset_args(parser)
    add_output_args(parser, default_limit=20)
    parser.add_argument(
        "--view",
        choices=["slowest", "template_heavy", "preprocessor_bloat", "low_throughput", "all"],
        default="all",
        help="Which ranking to show (default: all).",
    )
    parser.add_argument(
        "--min-source-bytes",
        type=int,
        default=512,
        help="Minimum source size in bytes for preprocessor_bloat view (avoids trivial files).",
    )
    parser.add_argument(
        "--min-code-lines",
        type=int,
        default=50,
        help="Minimum code lines for low_throughput view (avoids trivial files).",
    )
    parser.add_argument(
        "--exclude-generated",
        action="store_true",
        help="Exclude generated source files from all rankings.",
    )
    args = parser.parse_args(argv)

    ds = load_dataset(args)
    fm = ds.file_metrics
    if args.exclude_generated and "is_generated" in fm.columns:
        fm = fm[~fm["is_generated"]]

    views = {
        "slowest": (_slowest(fm), "Slowest files (raw compile_time_ms)"),
        "template_heavy": (_template_heavy(fm), "Template-instantiation heavy files"),
        "preprocessor_bloat": (
            _preprocessor_bloat(fm, args.min_source_bytes),
            f"Preprocessor-bloat files (source ≥ {args.min_source_bytes} bytes)",
        ),
        "low_throughput": (
            _low_throughput(fm, args.min_code_lines),
            f"Low compile throughput (lines/sec; code_lines ≥ {args.min_code_lines})",
        ),
    }

    if args.view != "all":
        df, title = views[args.view]
        emit(df, args, title=title)
    else:
        for df, title in views.values():
            emit(df, args, title=title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
