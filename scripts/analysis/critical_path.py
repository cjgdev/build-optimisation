#!/usr/bin/env python3
"""Report the build critical path and near-critical targets.

Question answered
-----------------
"What is the shortest possible wall-clock time for a full build on infinite
cores, which targets bound it, and where is the slack concentrated?"

Output sections:

* Summary — critical path length, total work, parallelism ratio.
* Critical path — ordered targets on the path, with durations.
* Near-critical — top targets with low but non-zero slack that could become
  critical after a small change.
* Slack leaders — targets with the largest slack (safest to delay or to
  split link dependencies from).

When a scope is supplied the analysis is restricted to the induced subgraph
(scoped targets PLUS their transitive dependencies, so the subgraph is
closed under the build relation).

Attributes consumed:
    target_metrics: cmake_target, total_build_time_ms, target_type.
    edge_list: source_target, dest_target, is_direct.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from buildanalysis.build import compute_critical_path  # noqa: E402
from buildanalysis.graph import build_dependency_graph  # noqa: E402
from scripts.analysis._common import (  # noqa: E402
    add_dataset_args,
    add_output_args,
    add_scope_args,
    emit,
    emit_kv,
    emit_scope_header,
    load_dataset,
    resolve_scope,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_dataset_args(parser)
    add_scope_args(parser)
    add_output_args(parser, default_limit=25)
    parser.add_argument(
        "--time-col",
        default="total_build_time_ms",
        help="Column in target_metrics to use as the target duration.",
    )
    parser.add_argument(
        "--near-critical-ms",
        type=int,
        default=1000,
        help="Maximum slack (ms) to classify a target as 'near-critical' (default: 1000).",
    )
    args = parser.parse_args(argv)

    ds = load_dataset(args)
    scope = resolve_scope(args, ds)
    emit_scope_header(scope, args)

    bg = build_dependency_graph(ds.target_metrics, ds.edge_list)
    bg = bg.subgraph(scope)  # no-op when scope is global
    result = compute_critical_path(bg, ds.target_metrics, time_col=args.time_col)

    slack = result.target_slack.copy()
    slack = slack.merge(
        ds.target_metrics[["cmake_target", "target_type"]],
        on="cmake_target",
        how="left",
    )

    critical = slack[slack["on_critical_path"]].sort_values("earliest_start_ms").reset_index(drop=True)
    near = slack[(~slack["on_critical_path"]) & (slack["slack_ms"] <= args.near_critical_ms)]
    near = near.sort_values("slack_ms").reset_index(drop=True)
    leaders = slack.sort_values("slack_ms", ascending=False).reset_index(drop=True)

    summary = [
        ("critical_path_time_s", f"{result.total_time_s:.2f}"),
        ("total_work_s", f"{result.total_work_s:.2f}"),
        ("parallelism_ratio", f"{result.parallelism_ratio:.2f}"),
        ("n_targets_on_path", len(result.path)),
        ("near_critical_threshold_ms", args.near_critical_ms),
        ("n_near_critical", len(near)),
    ]
    emit_kv(summary, args, title="Critical path summary")

    emit(
        critical[["cmake_target", "target_type", "build_time_ms", "earliest_start_ms", "earliest_finish_ms"]],
        args,
        title="Targets on the critical path (ordered by start time)",
    )
    emit(
        near[["cmake_target", "target_type", "build_time_ms", "slack_ms"]],
        args,
        title=f"Near-critical targets (slack ≤ {args.near_critical_ms} ms)",
    )
    emit(
        leaders[["cmake_target", "target_type", "build_time_ms", "slack_ms"]],
        args,
        title="Slack leaders (most schedulable head-room)",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
