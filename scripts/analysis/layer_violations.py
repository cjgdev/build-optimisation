#!/usr/bin/env python3
"""List dependency edges that violate strict architectural layering.

Question answered
-----------------
"Where is my architecture drifting? Which targets are depending upward or
laterally through the layer hierarchy?"

Layers are inferred automatically from the dependency graph: layer 0 is
any target with no dependencies, and a target's layer is one plus the max
layer of its dependencies. A violation is any edge whose destination is at
a higher layer than, or the same layer as, its source.

When a scope is supplied the analysis is restricted to the induced subgraph
(scoped targets PLUS their transitive dependencies, so the subgraph is
closed under the build relation).

Attributes consumed:
    target_metrics, edge_list.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from buildanalysis.graph import (  # noqa: E402
    build_dependency_graph,
    compute_layer_assignments,
    find_layer_violations,
)
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
    add_output_args(parser, default_limit=50)
    parser.add_argument(
        "--violation-type",
        choices=["all", "upward", "lateral"],
        default="all",
        help="Filter to a specific violation type (default: all).",
    )
    args = parser.parse_args(argv)

    ds = load_dataset(args)
    scope = resolve_scope(args, ds)
    emit_scope_header(scope, args)

    bg = build_dependency_graph(ds.target_metrics, ds.edge_list)
    bg = bg.subgraph(scope)
    layers = compute_layer_assignments(bg)
    violations = find_layer_violations(bg, layers)

    if args.violation_type != "all":
        violations = violations[violations["violation_type"] == args.violation_type].reset_index(drop=True)

    summary = [
        ("n_targets", len(layers)),
        ("max_layer", int(layers["layer"].max()) if not layers.empty else 0),
        ("n_violations", len(violations)),
        ("n_upward", int((violations["violation_type"] == "upward").sum()) if not violations.empty else 0),
        ("n_lateral", int((violations["violation_type"] == "lateral").sum()) if not violations.empty else 0),
    ]
    emit_kv(summary, args, title="Layer violation summary")
    emit(violations, args, title="Layer violations")
    emit(layers.sort_values("layer"), args, title="Layer assignment (0 = leaf)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
