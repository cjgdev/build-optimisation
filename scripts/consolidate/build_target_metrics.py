#!/usr/bin/env python3
"""Consolidate file-level metrics into target_metrics.parquet.

Reads file_metrics.parquet (from build_file_metrics.py), targets.json,
dependencies.json, and ninja_log.csv to produce one row per CMake target.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import networkx as nx
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from build_optimiser.config import Config
from build_optimiser.metrics import TARGET_METRICS_SCHEMA, aggregate_file_metrics_for_target

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidate target-level metrics")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    cfg = Config.from_yaml(args.config)

    # Load file metrics
    file_metrics_path = cfg.processed_data_dir / "file_metrics.parquet"
    if not file_metrics_path.exists():
        logger.error("file_metrics.parquet not found — run build_file_metrics.py first")
        sys.exit(1)
    file_df = pd.read_parquet(file_metrics_path)
    logger.info("Loaded file_metrics: %d rows", len(file_df))

    # Load targets.json for target metadata
    targets_path = cfg.raw_data_dir / "cmake_file_api" / "targets.json"
    with open(targets_path) as f:
        targets_data = json.load(f)
    target_meta = {t["name"]: t for t in targets_data}

    # Load ninja log for non-compile step times
    ninja_path = cfg.raw_data_dir / "ninja_log.csv"
    ninja_df = pd.read_csv(ninja_path) if ninja_path.exists() else pd.DataFrame()

    # Build step times per target
    step_times: dict[str, dict[str, int]] = {}
    if not ninja_df.empty:
        for _, row in ninja_df.iterrows():
            target = row.get("cmake_target", "")
            if not target:
                continue
            if target not in step_times:
                step_times[target] = {"codegen": 0, "archive": 0, "link": 0}
            step_type = row.get("step_type", "")
            duration = int(row.get("duration_ms", 0))
            if step_type in step_times[target]:
                step_times[target][step_type] += duration

    # Load dependency data for graph metrics
    deps_path = cfg.raw_data_dir / "cmake_file_api" / "dependencies.json"
    with open(deps_path) as f:
        deps_data = json.load(f)

    # Build a NetworkX graph for centrality/depth computations
    G = nx.DiGraph()
    for t in target_meta:
        G.add_node(t)
    for edge in deps_data:
        src = edge["source_target"]
        dst = edge["dest_target"]
        if src in G and dst in G:
            G.add_edge(src, dst, is_direct=edge.get("is_direct", False))

    # Compute graph metrics
    try:
        centrality = nx.betweenness_centrality(G)
    except Exception:
        centrality = {n: 0.0 for n in G}

    # Compute topological depth per node
    topo_depth = {}
    for node in G:
        try:
            ancestors = nx.ancestors(G, node)
            if ancestors:
                paths = [nx.shortest_path_length(G, a, node) for a in ancestors if nx.has_path(G, a, node)]
                topo_depth[node] = max(paths) if paths else 0
            else:
                topo_depth[node] = 0
        except Exception:
            topo_depth[node] = 0

    # Aggregate per target
    rows = []
    for target_name, meta in target_meta.items():
        target_files = file_df[file_df["cmake_target"] == target_name]

        if target_files.empty:
            agg = {k: 0 for k in [
                "file_count", "codegen_file_count", "authored_file_count",
                "code_lines_total", "code_lines_authored", "code_lines_generated",
                "compile_time_sum_ms", "compile_time_max_ms",
            ]}
            agg["codegen_ratio"] = 0.0
            for k in ["compile_time_mean_ms", "compile_time_median_ms", "compile_time_std_ms",
                       "compile_time_p90_ms", "compile_time_p99_ms"]:
                agg[k] = 0.0
            for k in ["authored_compile_time_sum_ms", "authored_compile_time_max_ms",
                       "codegen_compile_time_sum_ms", "codegen_compile_time_max_ms"]:
                agg[k] = 0
            for k in ["gcc_parse_time_sum_ms", "gcc_template_time_sum_ms",
                       "gcc_codegen_phase_sum_ms", "gcc_optimization_time_sum_ms"]:
                agg[k] = 0.0
            for k in ["header_depth_max", "unique_headers_total", "total_includes_sum",
                       "preprocessed_bytes_total", "object_size_total_bytes", "object_file_count"]:
                agg[k] = 0
            agg["header_depth_mean"] = 0.0
            agg["preprocessed_bytes_mean"] = 0.0
            agg["expansion_ratio_mean"] = 0.0
            agg["git_commit_count_total"] = 0
            agg["git_churn_total"] = 0
            agg["git_distinct_authors"] = 0
            agg["git_hotspot_file_count"] = 0
        else:
            agg = aggregate_file_metrics_for_target(target_files)

        # Target metadata
        agg["cmake_target"] = target_name
        agg["target_type"] = meta.get("type", "")
        agg["output_artifact"] = meta.get("name_on_disk") or ""

        # Build step timing
        times = step_times.get(target_name, {})
        agg["codegen_time_ms"] = times.get("codegen", 0)
        agg["archive_time_ms"] = times.get("archive", 0)
        agg["link_time_ms"] = times.get("link", 0)
        agg["total_build_time_ms"] = (
            agg.get("compile_time_sum_ms", 0) +
            agg["codegen_time_ms"] + agg["archive_time_ms"] + agg["link_time_ms"]
        )

        # Dependency graph metrics
        direct_deps = [n for n in G.successors(target_name) if G[target_name][n].get("is_direct")]
        all_deps = list(G.successors(target_name))
        direct_dependants = [n for n in G.predecessors(target_name) if G[n][target_name].get("is_direct")]

        agg["direct_dependency_count"] = len(direct_deps)
        agg["transitive_dependency_count"] = len(all_deps) - len(direct_deps)
        agg["total_dependency_count"] = len(all_deps)
        agg["direct_dependant_count"] = len(direct_dependants)
        try:
            agg["transitive_dependant_count"] = len(nx.ancestors(G, target_name))
        except Exception:
            agg["transitive_dependant_count"] = 0
        agg["topological_depth"] = topo_depth.get(target_name, 0)
        agg["critical_path_contribution_ms"] = 0  # computed in notebook 03
        agg["fan_in"] = len(direct_dependants)
        agg["fan_out"] = len(direct_deps)
        agg["betweenness_centrality"] = centrality.get(target_name, 0.0)

        # File lists as JSON
        source_files = target_files["source_file"].tolist() if not target_files.empty else []
        generated = target_files[target_files["is_generated"] == True]["source_file"].tolist() if not target_files.empty else []  # noqa: E712
        artifacts = [a.get("path", "") for a in meta.get("artifacts", [])]
        agg["source_files"] = json.dumps(source_files)
        agg["generated_files"] = json.dumps(generated)
        agg["output_files"] = json.dumps(artifacts)

        rows.append(agg)

    result_df = pd.DataFrame(rows)
    logger.info("Aggregated %d targets", len(result_df))

    # Ensure all schema columns exist
    for field in TARGET_METRICS_SCHEMA:
        if field.name not in result_df.columns:
            result_df[field.name] = pd.NA

    result_df = result_df[[f.name for f in TARGET_METRICS_SCHEMA]]

    cfg.processed_data_dir.mkdir(parents=True, exist_ok=True)
    output_path = cfg.processed_data_dir / "target_metrics.parquet"
    table = pa.Table.from_pandas(result_df, schema=TARGET_METRICS_SCHEMA, preserve_index=False)
    pq.write_table(table, output_path)
    logger.info("Wrote %s (%d rows, %d columns)", output_path, len(result_df), len(result_df.columns))


if __name__ == "__main__":
    main()
