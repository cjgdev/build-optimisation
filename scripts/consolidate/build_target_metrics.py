#!/usr/bin/env python3
"""Aggregate file-level metrics to one row per CMake target."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from build_optimiser.config import load_config
from build_optimiser.graph import load_graph, all_topological_depths, critical_path, critical_path_length

import networkx as nx


def main() -> None:
    cfg = load_config()
    raw_dir = Path(cfg["raw_data_dir"])
    processed_dir = Path(cfg["processed_data_dir"])
    processed_dir.mkdir(parents=True, exist_ok=True)

    # Load file metrics
    file_metrics_path = processed_dir / "file_metrics.parquet"
    if not file_metrics_path.exists():
        print("Error: file_metrics.parquet not found. Run build_file_metrics.py first.", file=sys.stderr)
        sys.exit(1)
    file_df = pd.read_parquet(file_metrics_path)

    # Aggregate file metrics to target level
    agg = file_df.groupby("cmake_target").agg(
        compile_time_sum_ms=("compile_time_ms", "sum"),
        compile_time_max_ms=("compile_time_ms", "max"),
        file_count=("source_file", "count"),
        code_lines_total=("code_lines", "sum"),
        header_depth_mean=("header_max_depth", "mean"),
        header_depth_max=("header_max_depth", "max"),
        preprocessed_bytes_total=("preprocessed_bytes", "sum"),
        object_size_total_bytes=("object_size_bytes", "sum"),
        git_commit_count_total=("git_commit_count", "sum"),
    ).reset_index()

    # Add object file count
    obj_path = raw_dir / "object_files.csv"
    if obj_path.exists():
        obj_df = pd.read_csv(obj_path)
        obj_count = obj_df.groupby("cmake_target").size().reset_index(name="object_file_count")
        agg = agg.merge(obj_count, on="cmake_target", how="left")
    else:
        agg["object_file_count"] = agg["file_count"]

    # Add link times
    link_path = raw_dir / "link_times.csv"
    if link_path.exists():
        link_df = pd.read_csv(link_path)
        link_df = link_df[["cmake_target", "link_time_ms"]]
        agg = agg.merge(link_df, on="cmake_target", how="left")
    else:
        agg["link_time_ms"] = 0

    # Add graph-derived metrics
    dot_dir = raw_dir / "dot"
    if dot_dir.exists() and any(dot_dir.glob("*.dot")):
        try:
            G = load_graph(str(dot_dir))

            graph_metrics = []
            depths = all_topological_depths(G)

            for target in agg["cmake_target"]:
                row = {"cmake_target": target}
                if target in G:
                    row["direct_dependency_count"] = len(list(G.successors(target)))
                    row["transitive_dependency_count"] = len(nx.descendants(G, target))
                    row["direct_dependant_count"] = len(list(G.predecessors(target)))
                    row["transitive_dependant_count"] = len(nx.ancestors(G, target))
                    row["topological_depth"] = depths.get(target, 0)
                else:
                    for col in ["direct_dependency_count", "transitive_dependency_count",
                                "direct_dependant_count", "transitive_dependant_count",
                                "topological_depth"]:
                        row[col] = 0
                graph_metrics.append(row)

            graph_df = pd.DataFrame(graph_metrics)
            agg = agg.merge(graph_df, on="cmake_target", how="left")

            # Compute critical path length per node
            # Attach compile times as node weights
            from build_optimiser.graph import attach_metrics
            attach_metrics(G, agg, key_column="cmake_target")

            # For each node, compute longest weighted path through it
            cp = critical_path(G, weight_attr="compile_time_sum_ms")
            cp_length = critical_path_length(G, weight_attr="compile_time_sum_ms")

            cp_set = set(cp)
            agg["critical_path_length_ms"] = agg["cmake_target"].apply(
                lambda t: cp_length if t in cp_set else 0
            )
        except Exception as e:
            print(f"Warning: Could not compute graph metrics: {e}", file=sys.stderr)
            for col in ["direct_dependency_count", "transitive_dependency_count",
                        "direct_dependant_count", "transitive_dependant_count",
                        "topological_depth", "critical_path_length_ms"]:
                if col not in agg.columns:
                    agg[col] = 0
    else:
        for col in ["direct_dependency_count", "transitive_dependency_count",
                    "direct_dependant_count", "transitive_dependant_count",
                    "topological_depth", "critical_path_length_ms"]:
            agg[col] = 0

    # Fill NaN
    numeric_cols = agg.select_dtypes(include="number").columns
    agg[numeric_cols] = agg[numeric_cols].fillna(0)

    # Cast integer columns
    int_cols = [c for c in agg.columns if c != "cmake_target" and c != "header_depth_mean"]
    for col in int_cols:
        if col in agg.columns:
            agg[col] = agg[col].astype(int)

    # Write output
    output_path = processed_dir / "target_metrics.parquet"
    agg.to_parquet(output_path, index=False)
    print(f"Wrote {len(agg)} target rows to {output_path}")
    print(f"Columns: {list(agg.columns)}")


if __name__ == "__main__":
    main()
