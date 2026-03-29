#!/usr/bin/env python3
"""Consolidate dependency edges into edge_list.parquet.

Reads dependencies.json and targets.json to produce an edge list
enriched with target types.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from build_optimiser.config import Config
from build_optimiser.metrics import EDGE_LIST_SCHEMA

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidate edge list")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    cfg = Config.from_yaml(args.config)

    # Load dependencies
    deps_path = cfg.raw_data_dir / "cmake_file_api" / "dependencies.json"
    with open(deps_path) as f:
        deps_data = json.load(f)

    # Load target types
    targets_path = cfg.raw_data_dir / "cmake_file_api" / "targets.json"
    with open(targets_path) as f:
        targets_data = json.load(f)
    target_types = {t["name"]: t.get("type", "") for t in targets_data}

    # Build DataFrame
    rows = []
    for edge in deps_data:
        src = edge["source_target"]
        dst = edge["dest_target"]
        is_direct = edge.get("is_direct", False)
        rows.append({
            "source_target": src,
            "dest_target": dst,
            "is_direct": is_direct,
            "dependency_type": edge.get("dependency_type", "transitive"),
            "source_target_type": target_types.get(src, ""),
            "dest_target_type": target_types.get(dst, ""),
            "from_dependency": edge.get("from_dependency"),
            "cmake_visibility": "TRANSITIVE" if not is_direct else edge.get("cmake_visibility", "UNKNOWN"),
        })

    df = pd.DataFrame(rows)
    logger.info("Edge list: %d edges", len(df))

    # Ensure all schema columns
    for field in EDGE_LIST_SCHEMA:
        if field.name not in df.columns:
            df[field.name] = pd.NA

    df = df[[f.name for f in EDGE_LIST_SCHEMA]]

    cfg.processed_data_dir.mkdir(parents=True, exist_ok=True)
    output_path = cfg.processed_data_dir / "edge_list.parquet"
    table = pa.Table.from_pandas(df, schema=EDGE_LIST_SCHEMA, preserve_index=False)
    pq.write_table(table, output_path)
    logger.info("Wrote %s (%d rows)", output_path, len(df))


if __name__ == "__main__":
    main()
