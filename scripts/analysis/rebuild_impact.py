#!/usr/bin/env python3
"""Estimate the blast radius of a change to a target or file.

Question answered
-----------------
"If I modify target X (or the file at path P), what else gets rebuilt, how
long will that rebuild take, and how often does this happen?"

The script supports three modes:

* ``--target NAME`` — show the transitive dependants of a specific CMake
  target and the cumulative rebuild cost.
* ``--file PATH`` — resolve the file to its owning target, then show the
  same report.
* (default) — rank every target in the codebase by expected daily rebuild
  cost, i.e. ``change_probability × transitive_rebuild_cost``.

Attributes consumed:
    target_metrics: cmake_target, total_build_time_ms,
        compile_time_sum_ms, git_commit_count_total, target_type.
    edge_list: source_target, dest_target, is_direct.
    file_metrics (if --file): source_file, cmake_target.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import networkx as nx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from buildanalysis.graph import build_dependency_graph  # noqa: E402
from buildanalysis.simulation import rebuild_cost  # noqa: E402
from scripts.analysis._common import (  # noqa: E402
    add_dataset_args,
    add_output_args,
    emit,
    emit_kv,
    load_dataset,
)

WORKING_DAYS_PER_MONTH = 20


def resolve_target_for_file(file_metrics: pd.DataFrame, path: str) -> str:
    """Return the owning cmake_target for a source file path."""
    match = file_metrics.loc[file_metrics["source_file"] == path, "cmake_target"]
    if match.empty:
        # Try basename fallback
        basename = Path(path).name
        match = file_metrics.loc[file_metrics["source_file"].str.endswith("/" + basename), "cmake_target"]
    if match.empty:
        raise SystemExit(f"No target owns source file: {path}")
    return match.iloc[0]


def _dependants_table(
    graph: nx.DiGraph,
    target: str,
    target_metrics: pd.DataFrame,
) -> pd.DataFrame:
    """List the direct and transitive dependants of ``target`` with timings."""
    if target not in graph:
        raise SystemExit(f"Target '{target}' not in dependency graph.")
    # A -> B means A depends on B, so dependants are ancestors of target.
    direct = set(graph.predecessors(target))
    transitive = set(nx.ancestors(graph, target)) - direct

    rows = []
    tm = target_metrics.set_index("cmake_target")
    for t in sorted(direct | transitive):
        if t not in tm.index:
            continue
        rows.append(
            {
                "cmake_target": t,
                "relation": "direct" if t in direct else "transitive",
                "target_type": tm.at[t, "target_type"],
                "total_build_time_ms": tm.at[t, "total_build_time_ms"],
                "topological_depth": tm.at[t, "topological_depth"] if "topological_depth" in tm.columns else None,
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(["relation", "total_build_time_ms"], ascending=[True, False]).reset_index(drop=True)


def _expected_daily_cost_table(
    graph: nx.DiGraph,
    target_metrics: pd.DataFrame,
    history_months: int,
) -> pd.DataFrame:
    """Rank every target by expected daily rebuild cost.

    ``expected_daily_cost_ms = (commits / (months × 20)) × rebuild_cost_ms``.
    """
    tm = target_metrics.set_index("cmake_target")
    working_days = max(history_months * WORKING_DAYS_PER_MONTH, 1)

    rows = []
    for t in graph.nodes():
        if t not in tm.index:
            continue
        cost = rebuild_cost(graph, t, target_metrics)
        commits = tm.at[t, "git_commit_count_total"] if "git_commit_count_total" in tm.columns else 0
        if pd.isna(commits):
            commits = 0
        change_prob = commits / working_days
        rows.append(
            {
                "cmake_target": t,
                "target_type": tm.at[t, "target_type"],
                "rebuild_cost_ms": cost,
                "git_commit_count": int(commits),
                "change_prob_per_day": round(change_prob, 4),
                "expected_daily_cost_ms": int(round(change_prob * cost)),
                "transitive_dependant_count": int(tm.at[t, "transitive_dependant_count"])
                if "transitive_dependant_count" in tm.columns
                else 0,
            }
        )
    return pd.DataFrame(rows).sort_values("expected_daily_cost_ms", ascending=False).reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_dataset_args(parser)
    add_output_args(parser, default_limit=25)
    parser.add_argument("--target", help="Show the blast radius for this CMake target.")
    parser.add_argument("--file", help="Show the blast radius for the target that owns this source file.")
    parser.add_argument(
        "--history-months",
        type=int,
        default=12,
        help="Months of git history represented in the data (default: 12).",
    )
    args = parser.parse_args(argv)

    ds = load_dataset(args)
    bg = build_dependency_graph(ds.target_metrics, ds.edge_list)

    target = args.target
    if args.file is not None:
        target = resolve_target_for_file(ds.file_metrics, args.file)

    if target is not None:
        cost = rebuild_cost(bg.graph, target, ds.target_metrics)
        tm_indexed = ds.target_metrics.set_index("cmake_target")
        commits = int(tm_indexed.at[target, "git_commit_count_total"]) if target in tm_indexed.index else 0
        working_days = max(args.history_months * WORKING_DAYS_PER_MONTH, 1)
        prob = commits / working_days

        summary = [
            ("target", target),
            ("rebuild_cost_ms", cost),
            ("rebuild_cost_s", f"{cost / 1000:.2f}"),
            ("git_commit_count", commits),
            (
                "change_prob_per_day",
                f"{prob:.4f}  ({commits} commits / {args.history_months} months × {WORKING_DAYS_PER_MONTH} days)",
            ),
            ("expected_daily_cost_ms", int(round(prob * cost))),
        ]
        emit_kv(summary, args, title=f"Rebuild impact for '{target}'")
        table = _dependants_table(bg.graph, target, ds.target_metrics)
        emit(table, args, title=f"Dependants of '{target}' (direct and transitive)")
        return 0

    ranked = _expected_daily_cost_table(bg.graph, ds.target_metrics, args.history_months)
    emit(ranked, args, title="Top targets by expected daily rebuild cost")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
