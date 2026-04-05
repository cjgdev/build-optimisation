#!/usr/bin/env python3
"""Consolidate ninja build log into build_schedule.parquet.

Preserves start/end timestamps for every build step, enabling parallelism
analysis and build simulation validation.

Outputs:
    - data/processed/build_schedule.parquet
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from buildanalysis.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SCHEDULE_SCHEMA = pa.schema(
    [
        pa.field("output_file", pa.string()),
        pa.field("source_file", pa.string()),
        pa.field("cmake_target", pa.string()),
        pa.field("step_type", pa.string()),
        pa.field("start_time_ms", pa.int64()),
        pa.field("end_time_ms", pa.int64()),
        pa.field("duration_ms", pa.int64()),
    ]
)

VALID_STEP_TYPES = {"compile", "codegen", "archive", "link", "other"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build schedule from ninja log")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    cfg = Config.from_yaml(args.config)

    # Load ninja log CSV
    ninja_path = cfg.raw_data_dir / "ninja_log.csv"
    if not ninja_path.exists():
        logger.error("ninja_log.csv not found at %s — run 06_ninja_log.py first", ninja_path)
        sys.exit(1)

    ninja_df = pd.read_csv(ninja_path)
    logger.info("Loaded ninja_log.csv: %d rows", len(ninja_df))

    if ninja_df.empty:
        logger.error("ninja_log.csv is empty")
        sys.exit(1)

    # Build the schedule DataFrame with the required schema
    schedule = pd.DataFrame(
        {
            "output_file": ninja_df["output_path"],
            "source_file": ninja_df["source_file"].replace("", pd.NA),
            "cmake_target": ninja_df["cmake_target"].replace("", pd.NA),
            "step_type": ninja_df["step_type"],
            "start_time_ms": ninja_df["start_ms"].astype("int64"),
            "end_time_ms": ninja_df["end_ms"].astype("int64"),
            "duration_ms": ninja_df["duration_ms"].astype("int64"),
        }
    )

    # Validate step types
    invalid = set(schedule["step_type"].unique()) - VALID_STEP_TYPES
    if invalid:
        logger.warning("Unexpected step types found: %s — mapping to 'other'", invalid)
        schedule.loc[~schedule["step_type"].isin(VALID_STEP_TYPES), "step_type"] = "other"

    # Write parquet
    cfg.processed_data_dir.mkdir(parents=True, exist_ok=True)
    output_path = cfg.processed_data_dir / "build_schedule.parquet"
    table = pa.Table.from_pandas(schedule, schema=SCHEDULE_SCHEMA, preserve_index=False)
    pq.write_table(table, output_path)
    logger.info("Wrote %s (%d rows, %d columns)", output_path, len(schedule), len(schedule.columns))

    # Summary statistics
    total_steps = len(schedule)
    type_counts = schedule["step_type"].value_counts()
    logger.info("Total build steps: %d", total_steps)
    for step_type, count in type_counts.items():
        logger.info("  %s: %d steps", step_type, count)

    wall_time_ms = schedule["end_time_ms"].max() - schedule["start_time_ms"].min()
    logger.info("Total wall time: %.1f minutes", wall_time_ms / 1000 / 60)

    cpu_time_ms = schedule["duration_ms"].sum()
    logger.info("Total CPU time: %.1f minutes", cpu_time_ms / 1000 / 60)

    # Observed max parallelism by sampling time points
    min_start = schedule["start_time_ms"].min()
    max_end = schedule["end_time_ms"].max()
    sample_times = np.linspace(min_start, max_end, min(1000, total_steps))
    starts = schedule["start_time_ms"].values
    ends = schedule["end_time_ms"].values
    max_concurrent = 0
    for t in sample_times:
        concurrent = int(((starts <= t) & (ends > t)).sum())
        if concurrent > max_concurrent:
            max_concurrent = concurrent
    logger.info("Observed max parallelism (sampled): %d concurrent steps", max_concurrent)

    # Coverage stats
    has_target = schedule["cmake_target"].notna().mean()
    logger.info("Steps with cmake_target: %.1f%%", has_target * 100)

    compile_steps = schedule[schedule["step_type"] == "compile"]
    if len(compile_steps) > 0:
        has_source = compile_steps["source_file"].notna().mean()
        logger.info("Compile steps with source_file: %.1f%%", has_source * 100)


if __name__ == "__main__":
    main()
