#!/usr/bin/env python3
"""Consolidate contributor-file commit data into contributor-target commit counts.

Joins contributor_file_commits.csv with the file-to-target mapping from
files.json to produce per-contributor-per-target commit counts.

Outputs:
    - data/processed/contributor_target_commits.parquet
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

from buildanalysis.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def build_file_to_target_map(files_json_path: Path) -> dict[str, str]:
    """Build a mapping from canonical file path to CMake target name."""
    with open(files_json_path) as f:
        files_data = json.load(f)
    return {entry["path"]: entry["cmake_target"] for entry in files_data if "cmake_target" in entry}


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidate contributor-target metrics")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    cfg = Config.from_yaml(args.config)

    # Load contributor-file commits
    contrib_file_path = cfg.raw_data_dir / "contributor_file_commits.csv"
    if not contrib_file_path.exists():
        logger.error("contributor_file_commits.csv not found — run 02_git_history.py first")
        sys.exit(1)
    contrib_file_df = pd.read_csv(contrib_file_path)
    logger.info("Loaded contributor_file_commits: %d rows", len(contrib_file_df))

    # Load file-to-target mapping
    files_json = cfg.raw_data_dir / "cmake_file_api" / "files.json"
    if not files_json.exists():
        logger.error("files.json not found — run 01_cmake_file_api.py first")
        sys.exit(1)
    file_to_target = build_file_to_target_map(files_json)
    logger.info("Loaded file-to-target mapping: %d files", len(file_to_target))

    # Join: map each contributor-file row to a target
    contrib_file_df["cmake_target"] = contrib_file_df["source_file"].map(file_to_target)

    # Drop rows where file doesn't map to a target (e.g. headers not in any target)
    unmapped = contrib_file_df["cmake_target"].isna().sum()
    if unmapped > 0:
        logger.info("Dropping %d rows with no target mapping", unmapped)
    contrib_file_df = contrib_file_df.dropna(subset=["cmake_target"])

    # Aggregate: per-contributor-per-target commit counts
    target_commits = contrib_file_df.groupby(["contributor", "cmake_target"], as_index=False)["commit_count"].sum()
    logger.info("Aggregated to %d contributor-target pairs", len(target_commits))

    # Write output
    cfg.processed_data_dir.mkdir(parents=True, exist_ok=True)
    output_path = cfg.processed_data_dir / "contributor_target_commits.parquet"
    schema = pa.schema(
        [
            ("contributor", pa.string()),
            ("cmake_target", pa.string()),
            ("commit_count", pa.int64()),
        ]
    )
    table = pa.Table.from_pandas(target_commits, schema=schema, preserve_index=False)
    pq.write_table(table, output_path)
    logger.info("Wrote %s (%d rows)", output_path, len(target_commits))


if __name__ == "__main__":
    main()
