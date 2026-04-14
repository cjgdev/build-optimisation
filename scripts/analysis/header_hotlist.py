#!/usr/bin/env python3
"""Rank headers by their impact on build time.

Question answered
-----------------
"Which headers, if I trimmed, split, or forward-declared through, would
yield the biggest compile-time savings?"

Uses the standard impact score from :mod:`buildanalysis.headers`:

    impact_score = transitive_fan_in × source_size_bytes × (1 + n_commits)

Transitive fan-in captures how many translation units ultimately pull a
header in; size captures how much work the preprocessor does each time;
commits capture instability (changes invalidate everyone who includes it).

Attributes consumed:
    header_edges, header_metrics, file_metrics (for git churn via n_commits
    aggregated over includers).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from buildanalysis.graph import build_include_graph  # noqa: E402
from buildanalysis.headers import compute_header_impact_score, compute_include_fan_metrics  # noqa: E402
from scripts.analysis._common import add_dataset_args, add_output_args, emit, load_dataset  # noqa: E402


def _header_git_churn(file_metrics: pd.DataFrame, header_metrics: pd.DataFrame) -> pd.DataFrame:
    """Approximate ``n_commits`` per header from file-level git data.

    We do not have per-header git history in the primary tables, so we
    approximate stability with the maximum commit count of any TU that
    includes the header's owning target. This is conservative — it over-
    estimates churn for headers in busy targets — but correctly flags the
    high-risk cases as requiring care.
    """
    if "cmake_target" not in header_metrics.columns:
        return pd.DataFrame({"source_file": header_metrics["header_file"], "n_commits": 0})

    target_churn = file_metrics.groupby("cmake_target")["git_commit_count"].max().rename("n_commits").reset_index()
    merged = header_metrics.merge(target_churn, on="cmake_target", how="left")
    merged["n_commits"] = merged["n_commits"].fillna(0).astype(int)
    return merged[["header_file", "n_commits"]].rename(columns={"header_file": "source_file"})


def compute_hotlist(
    header_edges: pd.DataFrame,
    header_metrics: pd.DataFrame,
    file_metrics: pd.DataFrame,
    exclude_system: bool = True,
) -> pd.DataFrame:
    """Return the header hot-list DataFrame."""
    include_graph = build_include_graph(header_edges)
    fan = compute_include_fan_metrics(include_graph)

    hm = header_metrics
    if exclude_system and "is_system" in hm.columns:
        hm = hm[~hm["is_system"]]

    churn = _header_git_churn(file_metrics, hm)
    scored = compute_header_impact_score(fan, hm, churn)

    # Annotate with owning target if known
    if "cmake_target" in hm.columns:
        target_map = hm.set_index("header_file")["cmake_target"].to_dict()
        scored["cmake_target"] = scored["file"].map(target_map)
    return scored


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_dataset_args(parser)
    add_output_args(parser, default_limit=25)
    parser.add_argument(
        "--include-system",
        action="store_true",
        help="Include system/third-party headers (default: exclude).",
    )
    args = parser.parse_args(argv)

    ds = load_dataset(args)
    result = compute_hotlist(
        ds.header_edges,
        ds.header_metrics,
        ds.file_metrics,
        exclude_system=not args.include_system,
    )
    emit(result, args, title="Top headers by build impact (fan-in × size × churn)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
