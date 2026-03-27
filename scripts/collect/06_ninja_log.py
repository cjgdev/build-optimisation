#!/usr/bin/env python3
"""Step 6: Parse the ninja build log for build step timing.

Extracts wall-clock timing data for every build step from .ninja_log v5,
classifying each as compile, archive, link, codegen, or other.

Outputs:
    - data/raw/ninja_log.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from build_optimiser.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_ninja_log(log_path: Path) -> list[dict]:
    """Parse a .ninja_log v5 file into a list of build step records.

    Each record has: start_ms, end_ms, restat_mtime, output_path, command_hash.
    """
    records = []

    with open(log_path) as f:
        header = f.readline().strip()
        if not header.startswith("# ninja log v"):
            logger.warning("Unexpected ninja log header: %s", header)

        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split("\t")
            if len(parts) < 5:
                continue

            records.append({
                "start_ms": int(parts[0]),
                "end_ms": int(parts[1]),
                "restat_mtime": parts[2],
                "output_path": parts[3],
                "command_hash": parts[4],
            })

    return records


def classify_step(
    output_path: str,
    file_index: dict[str, str],
    target_artifacts: dict[str, str],
    codegen_outputs: set[str],
    build_dir: str,
) -> tuple[str, str | None, str | None]:
    """Classify a build step and map to source file / target.

    Returns (step_type, source_file, cmake_target).
    """
    import os

    # Canonicalise the output path relative to build dir
    if not os.path.isabs(output_path):
        abs_output = os.path.realpath(os.path.join(build_dir, output_path))
    else:
        abs_output = os.path.realpath(output_path)

    # Compile step: .o file
    if output_path.endswith(".o"):
        # Extract target from CMakeFiles/<target>.dir/... pattern
        parts = output_path.split("/")
        target_name = None
        source_suffix = None
        for i, part in enumerate(parts):
            if part == "CMakeFiles" and i + 1 < len(parts) and parts[i + 1].endswith(".dir"):
                target_name = parts[i + 1][:-4]
                source_suffix = "/".join(parts[i + 2:])
                break

        if source_suffix and source_suffix.endswith(".o"):
            source_suffix = source_suffix[:-2]

        # Try to find canonical source file
        source_file = None
        if source_suffix:
            for canonical, tgt in file_index.items():
                if canonical.endswith(source_suffix):
                    source_file = canonical
                    target_name = tgt
                    break

        return "compile", source_file, target_name

    # Archive step: .a file
    if output_path.endswith(".a"):
        target = target_artifacts.get(abs_output)
        return "archive", None, target

    # Link step: executable or .so/.dylib
    if output_path.endswith(".so") or output_path.endswith(".dylib"):
        target = target_artifacts.get(abs_output)
        return "link", None, target

    # Check if it's an executable (no extension, or in target artifacts)
    target = target_artifacts.get(abs_output)
    if target:
        return "link", None, target

    # Codegen step: matches a generated file
    if abs_output in codegen_outputs:
        # Find the target that owns this generated file
        target = file_index.get(abs_output)
        return "codegen", abs_output, target

    return "other", None, None


def main() -> None:
    parser = argparse.ArgumentParser(description="Step 6: Ninja log parsing")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()

    cfg = Config.from_yaml(args.config)

    # Recompact the log first
    logger.info("Running ninja -t recompact...")
    subprocess.run(
        ["ninja", "-C", str(cfg.build_dir), "-t", "recompact"],
        check=False,
    )

    # Parse the log
    log_path = cfg.build_dir / ".ninja_log"
    if not log_path.exists():
        logger.error("No .ninja_log found at %s", log_path)
        sys.exit(1)

    records = parse_ninja_log(log_path)
    logger.info("Parsed %d build step records", len(records))

    # Load File API data for classification
    files_json = cfg.raw_data_dir / "cmake_file_api" / "files.json"
    targets_json = cfg.raw_data_dir / "cmake_file_api" / "targets.json"
    codegen_json = cfg.raw_data_dir / "cmake_file_api" / "codegen_inventory.json"

    file_index: dict[str, str] = {}
    if files_json.exists():
        with open(files_json) as f:
            for entry in json.load(f):
                file_index[entry["path"]] = entry["cmake_target"]

    target_artifacts: dict[str, str] = {}
    if targets_json.exists():
        with open(targets_json) as f:
            for target in json.load(f):
                for artifact in target.get("artifacts", []):
                    art_path = artifact.get("path", "")
                    if art_path:
                        target_artifacts[art_path] = target["name"]

    codegen_outputs: set[str] = set()
    if codegen_json.exists():
        with open(codegen_json) as f:
            inventory = json.load(f)
            for files in inventory.values():
                codegen_outputs.update(files)

    # Classify and enrich each record
    build_dir = str(cfg.build_dir)
    output_records = []
    seen_commands: set[tuple] = set()

    for record in records:
        # Deduplicate multi-output build steps
        key = (record["command_hash"], record["start_ms"], record["end_ms"])
        if key in seen_commands:
            continue
        seen_commands.add(key)

        step_type, source_file, cmake_target = classify_step(
            record["output_path"], file_index, target_artifacts, codegen_outputs, build_dir
        )

        output_records.append({
            "output_path": record["output_path"],
            "source_file": source_file or "",
            "cmake_target": cmake_target or "",
            "step_type": step_type,
            "start_ms": record["start_ms"],
            "end_ms": record["end_ms"],
            "duration_ms": record["end_ms"] - record["start_ms"],
            "command_hash": record["command_hash"],
        })

    # Write output
    cfg.raw_data_dir.mkdir(parents=True, exist_ok=True)
    output_path = cfg.raw_data_dir / "ninja_log.csv"
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["output_path", "source_file", "cmake_target", "step_type",
                        "start_ms", "end_ms", "duration_ms", "command_hash"],
        )
        writer.writeheader()
        writer.writerows(output_records)
    logger.info("Wrote %s (%d rows)", output_path, len(output_records))

    # Summary
    by_type = {}
    for r in output_records:
        t = r["step_type"]
        by_type[t] = by_type.get(t, 0) + 1
    for step_type, count in sorted(by_type.items()):
        logger.info("  %s: %d steps", step_type, count)

    logger.info("Step 6 complete.")


if __name__ == "__main__":
    main()
