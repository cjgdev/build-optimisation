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
from scripts.analysis._common import (  # noqa: E402
    add_dataset_args,
    add_output_args,
    add_scope_args,
    emit,
    emit_scope_header,
    load_dataset,
    resolve_scope,
)


def compute_risk(
    git_commit_log: pd.DataFrame,
    file_metrics: pd.DataFrame,
    target_metrics: pd.DataFrame,
    max_contributors: int | None = None,
    min_top_share: float = 0.0,
) -> pd.DataFrame:
    """Return a per-target ownership-risk table sorted by severity.

    The ``max_contributors`` / ``min_top_share`` parameters are severity
    filters applied AFTER scope resolution — they narrow the output to
    genuinely concentrated targets rather than scoping the analysis.
    """
    file_to_target = compute_file_to_target_map(file_metrics)
    concentration = compute_ownership_concentration(git_commit_log, file_to_target)

    tm = target_metrics[["cmake_target", "target_type", "total_build_time_ms", "git_commit_count_total"]]
    merged = concentration.merge(tm, on="cmake_target", how="left")

    # Risk severity ≈ top_share × gini × sqrt(build_time) — concentrated, skewed,
    # and expensive targets float to the top. Using sqrt keeps very large
    # outliers from dominating the ranking.
    bt = merged["total_build_time_ms"].fillna(0).astype(float)
    merged["risk_score"] = merged["top_contributor_share"] * merged["gini"] * (bt.pow(0.5))

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
    add_scope_args(parser)
    add_output_args(parser, default_limit=25)
    parser.add_argument(
        "--max-contributors",
        type=int,
        default=None,
        help="Severity filter: only flag targets with at most this many contributors (sole/duo-owned).",
    )
    parser.add_argument(
        "--min-top-share",
        type=float,
        default=0.0,
        help="Severity filter: require top-contributor commit share ≥ this (0.0-1.0).",
    )
    args = parser.parse_args(argv)

    ds = load_dataset(args)
    scope = resolve_scope(args, ds)
    emit_scope_header(scope, args)

    tm_scoped = scope.filter_targets(ds.target_metrics)
    # Git log lives at file granularity, so scope via file_metrics too.
    fm_scoped = scope.filter_targets(ds.file_metrics)
    scoped_files = set(fm_scoped["source_file"])
    git_scoped = (
        ds.git_commit_log[ds.git_commit_log["source_file"].isin(scoped_files)]
        if scope.targets is not None
        else ds.git_commit_log
    )

    result = compute_risk(
        git_scoped,
        fm_scoped,
        tm_scoped,
        max_contributors=args.max_contributors,
        min_top_share=args.min_top_share,
    )
    emit(result, args, title="Ownership concentration risk (Gini × top share × √build time)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
