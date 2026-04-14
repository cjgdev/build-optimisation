#!/usr/bin/env python3
"""Identify bus-factor and knowledge-concentration risks.

Question answered
-----------------
"Which targets are fragile because they're owned by one or two people, and
which of those are also expensive to rebuild?"

Computes per-target contributor concentration using the Gini coefficient
(from :mod:`buildanalysis.git`) plus the top-contributor commit share. A
target is flagged as high-risk when:

* it has a small number of distinct contributors, AND
* the top contributor owns a large share of commits, AND
* the target has non-trivial build time (so the risk actually matters).

Attributes consumed:
    git_commit_log, file_metrics, target_metrics.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from buildanalysis.git import compute_file_to_target_map, compute_ownership_concentration  # noqa: E402
from scripts.analysis._common import add_dataset_args, add_output_args, emit, load_dataset  # noqa: E402


def compute_risk(
    git_commit_log: pd.DataFrame,
    file_metrics: pd.DataFrame,
    target_metrics: pd.DataFrame,
    min_build_time_ms: int = 0,
    max_contributors: int | None = None,
    min_top_share: float = 0.0,
) -> pd.DataFrame:
    """Return a per-target ownership-risk table sorted by severity."""
    file_to_target = compute_file_to_target_map(file_metrics)
    concentration = compute_ownership_concentration(git_commit_log, file_to_target)

    tm = target_metrics[["cmake_target", "target_type", "total_build_time_ms", "git_commit_count_total"]]
    merged = concentration.merge(tm, on="cmake_target", how="left")

    # Risk severity ≈ top_share × gini × sqrt(build_time) — concentrated, skewed,
    # and expensive targets float to the top. Using sqrt keeps very large
    # outliers from dominating the ranking.
    bt = merged["total_build_time_ms"].fillna(0).astype(float)
    merged["risk_score"] = merged["top_contributor_share"] * merged["gini"] * (bt.pow(0.5))

    if min_build_time_ms > 0:
        merged = merged[bt >= min_build_time_ms]
    if max_contributors is not None:
        merged = merged[merged["n_contributors"] <= max_contributors]
    if min_top_share > 0:
        merged = merged[merged["top_contributor_share"] >= min_top_share]

    cols = [
        "cmake_target",
        "target_type",
        "n_contributors",
        "top_contributor",
        "top_contributor_share",
        "gini",
        "total_commits",
        "total_build_time_ms",
        "risk_score",
    ]
    return merged.sort_values("risk_score", ascending=False)[cols].reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_dataset_args(parser)
    add_output_args(parser, default_limit=25)
    parser.add_argument(
        "--min-build-time-ms",
        type=int,
        default=0,
        help="Ignore targets that build in less than this many ms (default: 0).",
    )
    parser.add_argument(
        "--max-contributors",
        type=int,
        default=None,
        help="Optional ceiling on number of contributors (flag sole/duo-owned targets).",
    )
    parser.add_argument(
        "--min-top-share",
        type=float,
        default=0.0,
        help="Minimum top-contributor commit share (0.0-1.0) to include (default: 0).",
    )
    args = parser.parse_args(argv)

    ds = load_dataset(args)
    result = compute_risk(
        ds.git_commit_log,
        ds.file_metrics,
        ds.target_metrics,
        min_build_time_ms=args.min_build_time_ms,
        max_contributors=args.max_contributors,
        min_top_share=args.min_top_share,
    )
    emit(result, args, title="Ownership concentration risk (Gini × top share × √build time)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
