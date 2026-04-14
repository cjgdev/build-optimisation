#!/usr/bin/env python3
"""Rank CMake targets by refactor value.

Question answered
-----------------
"Where should I invest engineering effort for the biggest build-time wins?"

A target is a hotspot when it is expensive to build AND changes often AND
has many dependants (so every change cascades). The composite
``hotspot_score`` multiplies normalised values of each axis so targets must
score highly on all three to rank near the top.

Attributes consumed (target_metrics.parquet):
    total_build_time_ms, compile_time_sum_ms,
    git_commit_count_total, git_churn_total,
    direct_dependant_count, transitive_dependant_count,
    code_lines_total, codegen_ratio.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Support direct script invocation (python scripts/analysis/hotspots.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.analysis._common import (  # noqa: E402
    add_dataset_args,
    add_output_args,
    add_scope_args,
    emit,
    emit_scope_header,
    load_dataset,
    minmax_normalise,
    resolve_scope,
)


def compute_hotspots(target_metrics: pd.DataFrame) -> pd.DataFrame:
    """Compute a composite refactor-value score per target.

    The score combines build cost, churn, and blast radius; each axis is
    min-max normalised so targets are ranked on their joint standing rather
    than a single dominant attribute.
    """
    tm = target_metrics.copy()
    if tm.empty:
        return tm.assign(hotspot_score=[])

    cost = minmax_normalise(tm["total_build_time_ms"])
    churn = minmax_normalise(np.log1p(tm["git_commit_count_total"].fillna(0)))
    blast = minmax_normalise(np.log1p(tm["transitive_dependant_count"].fillna(0)))

    tm = tm.assign(
        cost_norm=cost,
        churn_norm=churn,
        blast_norm=blast,
        hotspot_score=cost * churn * blast,
    )

    cols = [
        "cmake_target",
        "target_type",
        "total_build_time_ms",
        "compile_time_sum_ms",
        "git_commit_count_total",
        "git_churn_total",
        "direct_dependant_count",
        "transitive_dependant_count",
        "code_lines_total",
        "codegen_ratio",
        "cost_norm",
        "churn_norm",
        "blast_norm",
        "hotspot_score",
    ]
    return tm[cols].sort_values("hotspot_score", ascending=False).reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_dataset_args(parser)
    add_scope_args(parser)
    add_output_args(parser, default_limit=20)
    args = parser.parse_args(argv)

    ds = load_dataset(args)
    scope = resolve_scope(args, ds)
    emit_scope_header(scope, args)

    tm = scope.filter_targets(ds.target_metrics)
    ranked = compute_hotspots(tm)
    emit(ranked, args, title="Refactor hotspots (cost × churn × blast radius)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
