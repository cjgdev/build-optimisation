"""Shared CLI helpers for ad-hoc analysis scripts.

All ad-hoc scripts load a ``BuildDataset`` from either a snapshot directory
(``--snapshot``) or a processed-data directory (``--data-dir``). They all
support the same output options: pretty table (default), CSV, or JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from buildanalysis.loading import BuildDataset


def add_dataset_args(parser: argparse.ArgumentParser) -> None:
    """Register ``--data-dir`` / ``--snapshot`` / ``--intermediate-dir``.

    The two location options are mutually exclusive; ``--data-dir`` points at
    a ``processed/`` directory directly, while ``--snapshot`` points at a
    snapshot directory that contains ``processed/``.
    """
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/processed"),
        help="Directory containing the processed parquet files (default: data/processed).",
    )
    group.add_argument(
        "--snapshot",
        type=Path,
        default=None,
        help="Snapshot directory containing processed/ (overrides --data-dir).",
    )
    parser.add_argument(
        "--intermediate-dir",
        type=Path,
        default=None,
        help="Directory for notebook-produced intermediate parquet files. Defaults to <data-dir>/intermediate.",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip Pandera schema validation when loading (faster, less safe).",
    )


def add_output_args(parser: argparse.ArgumentParser, default_limit: int = 20) -> None:
    """Register output options: ``--format``, ``--limit``, ``--output``."""
    parser.add_argument(
        "--format",
        choices=["table", "csv", "json"],
        default="table",
        help="Output format (default: table).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=default_limit,
        help=f"Maximum rows to show (default: {default_limit}; 0 = unlimited).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write output to (default: stdout).",
    )


def load_dataset(args: argparse.Namespace) -> BuildDataset:
    """Instantiate a ``BuildDataset`` from parsed CLI arguments."""
    validate = not getattr(args, "no_validate", False)
    if getattr(args, "snapshot", None) is not None:
        return BuildDataset.from_snapshot(
            args.snapshot,
            intermediate_dir=args.intermediate_dir,
            validate=validate,
        )
    return BuildDataset(
        data_dir=args.data_dir,
        intermediate_dir=args.intermediate_dir,
        validate=validate,
    )


def apply_limit(df: pd.DataFrame, limit: int) -> pd.DataFrame:
    """Return ``df`` truncated to ``limit`` rows (``0`` means no limit)."""
    if limit and limit > 0:
        return df.head(limit)
    return df


def emit(df: pd.DataFrame, args: argparse.Namespace, title: str | None = None) -> None:
    """Render ``df`` in the format requested by ``args`` to stdout or a file."""
    df = apply_limit(df, getattr(args, "limit", 0))

    fmt = getattr(args, "format", "table")
    if fmt == "csv":
        text = df.to_csv(index=False)
    elif fmt == "json":
        text = df.to_json(orient="records", date_format="iso", indent=2)
    else:
        lines: list[str] = []
        if title:
            lines.append(title)
            lines.append("=" * len(title))
        if df.empty:
            lines.append("(no rows)")
        else:
            with pd.option_context("display.max_rows", None, "display.width", 200, "display.max_colwidth", 80):
                lines.append(df.to_string(index=False))
        text = "\n".join(lines) + "\n"

    out = getattr(args, "output", None)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    else:
        sys.stdout.write(text)


def emit_kv(pairs: list[tuple[str, object]], args: argparse.Namespace, title: str | None = None) -> None:
    """Render an ordered list of key/value pairs (for summaries)."""
    fmt = getattr(args, "format", "table")
    if fmt == "json":
        text = json.dumps(dict(pairs), indent=2, default=str) + "\n"
    elif fmt == "csv":
        text = "key,value\n" + "\n".join(f"{k},{v}" for k, v in pairs) + "\n"
    else:
        width = max((len(str(k)) for k, _ in pairs), default=0)
        lines: list[str] = []
        if title:
            lines.append(title)
            lines.append("=" * len(title))
        for k, v in pairs:
            lines.append(f"{str(k).ljust(width)}  {v}")
        text = "\n".join(lines) + "\n"

    out = getattr(args, "output", None)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    else:
        sys.stdout.write(text)


def minmax_normalise(series: pd.Series) -> pd.Series:
    """Min-max normalise a numeric series to ``[0, 1]``.

    Constant series (including all-zero) produce zeros. Null values are
    treated as zero.
    """
    s = series.astype(float).fillna(0.0)
    lo, hi = s.min(), s.max()
    if hi <= lo:
        return pd.Series(0.0, index=s.index)
    return (s - lo) / (hi - lo)
