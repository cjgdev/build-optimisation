#!/usr/bin/env python3
"""Deep-dive report on a single CMake target.

Question answered
-----------------
"Tell me everything relevant about target X — its size, timing, dependency
footprint, churn, top contributors, and worst compile-time files."

Attributes consumed:
    target_metrics, edge_list, file_metrics, contributor_target_commits.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import networkx as nx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from buildanalysis.graph import build_dependency_graph  # noqa: E402
from scripts.analysis._common import add_dataset_args, add_output_args, emit, emit_kv, load_dataset  # noqa: E402


def _fmt_ms(value: object) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    v = float(value)
    return f"{v:,.0f} ms ({v / 1000:.2f} s)"


def _target_row(tm: pd.DataFrame, name: str) -> pd.Series:
    match = tm[tm["cmake_target"] == name]
    if match.empty:
        raise SystemExit(f"Target '{name}' not found in target_metrics.")
    return match.iloc[0]


def summarise_target(row: pd.Series) -> list[tuple[str, object]]:
    """Return the key/value summary rows for a single-target report."""

    def _opt_ms(key: str) -> str:
        value = row.get(key)
        return _fmt_ms(value) if pd.notna(value) else "n/a"

    pairs: list[tuple[str, object]] = [
        ("cmake_target", row["cmake_target"]),
        ("target_type", row["target_type"]),
        ("output_artifact", row.get("output_artifact", "n/a")),
        ("source_directory", row.get("source_directory", "n/a")),
        ("file_count", int(row.get("file_count", 0))),
        ("authored_file_count", int(row.get("authored_file_count", 0))),
        ("codegen_file_count", int(row.get("codegen_file_count", 0))),
        ("codegen_ratio", f"{float(row.get('codegen_ratio', 0.0)):.2%}"),
        ("code_lines_total", int(row.get("code_lines_total", 0))),
        ("compile_time_sum", _fmt_ms(row.get("compile_time_sum_ms"))),
        ("compile_time_max", _fmt_ms(row.get("compile_time_max_ms"))),
        ("compile_time_p99", _fmt_ms(row.get("compile_time_p99_ms"))),
        ("link_time", _fmt_ms(row.get("link_time_ms"))),
        ("total_build_time", _fmt_ms(row.get("total_build_time_ms"))),
        ("compiler_parse_sum", _opt_ms("compiler_parse_time_sum_ms")),
        ("compiler_template_sum", _opt_ms("compiler_template_time_sum_ms")),
        ("compiler_codegen_sum", _opt_ms("compiler_codegen_phase_sum_ms")),
        ("preprocessed_bytes_total", int(row.get("preprocessed_bytes_total", 0) or 0)),
        ("object_size_total_bytes", int(row.get("object_size_total_bytes", 0) or 0)),
        ("direct_dependency_count", int(row.get("direct_dependency_count", 0))),
        ("transitive_dependency_count", int(row.get("transitive_dependency_count", 0))),
        ("direct_dependant_count", int(row.get("direct_dependant_count", 0))),
        ("transitive_dependant_count", int(row.get("transitive_dependant_count", 0))),
        ("topological_depth", int(row.get("topological_depth", 0))),
        ("critical_path_contribution_ms", int(row.get("critical_path_contribution_ms", 0))),
        ("betweenness_centrality", f"{float(row.get('betweenness_centrality', 0.0)):.4f}"),
        ("git_commit_count_total", int(row.get("git_commit_count_total", 0))),
        ("git_churn_total", int(row.get("git_churn_total", 0))),
        ("git_distinct_authors", int(row.get("git_distinct_authors", 0))),
    ]
    return pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_dataset_args(parser)
    add_output_args(parser, default_limit=10)
    parser.add_argument("--target", required=True, help="CMake target name to report on.")
    args = parser.parse_args(argv)

    ds = load_dataset(args)
    row = _target_row(ds.target_metrics, args.target)
    emit_kv(summarise_target(row), args, title=f"Target summary: {args.target}")

    # Direct neighbours in the dependency graph
    bg = build_dependency_graph(ds.target_metrics, ds.edge_list)
    if args.target in bg.graph:
        deps = list(bg.graph.successors(args.target))
        dependants = list(bg.graph.predecessors(args.target))
        transitive_dependants = sorted(nx.ancestors(bg.graph, args.target) - set(dependants))

        tm = ds.target_metrics.set_index("cmake_target")

        def _row(name: str, relation: str) -> dict:
            return {
                "cmake_target": name,
                "relation": relation,
                "target_type": tm.at[name, "target_type"] if name in tm.index else "n/a",
                "total_build_time_ms": tm.at[name, "total_build_time_ms"] if name in tm.index else None,
            }

        neighbours = pd.DataFrame(
            [_row(d, "direct_dependency") for d in deps]
            + [_row(d, "direct_dependant") for d in dependants]
            + [_row(d, "transitive_dependant") for d in transitive_dependants]
        )
        if not neighbours.empty:
            neighbours = neighbours.sort_values(
                ["relation", "total_build_time_ms"], ascending=[True, False]
            ).reset_index(drop=True)
        emit(neighbours, args, title="Dependency neighbours")

    # Worst files in this target by compile time
    files = ds.file_metrics
    in_target = files[files["cmake_target"] == args.target].copy()
    if not in_target.empty:
        file_cols = [
            "source_file",
            "is_generated",
            "compile_time_ms",
            "code_lines",
            "compiler_template_instantiation_ms",
            "preprocessed_bytes",
            "expansion_ratio",
        ]
        slow = in_target.sort_values("compile_time_ms", ascending=False)[
            [c for c in file_cols if c in in_target.columns]
        ].reset_index(drop=True)
        emit(slow, args, title="Slowest files in this target")

    # Top contributors
    try:
        ctc = ds.contributor_target_commits
    except FileNotFoundError:
        ctc = pd.DataFrame()
    if not ctc.empty:
        top = (
            ctc[ctc["cmake_target"] == args.target].sort_values("commit_count", ascending=False).reset_index(drop=True)
        )
        emit(top, args, title="Top contributors to this target")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
