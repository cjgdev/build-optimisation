#!/usr/bin/env python3
"""Step 5: Measure preprocessed translation unit sizes.

Reruns the compiler with -E for each source file in parallel to measure
the preprocessed output size — a proxy for template expansion cost and
include bloat. Must run after the build so generated files exist.

Outputs:
    - data/raw/preprocessed_size.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from build_optimiser.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Flags to strip from compile commands for preprocessing
STRIP_FLAGS = {"-ftime-report", "-H"}


def modify_command_for_preprocess(command: str) -> str | None:
    """Modify a compile command to preprocess only (-E) and write to stdout.

    Strips incompatible flags and replaces -o <file> with -E.
    """
    parts = shlex.split(command)
    new_parts = []
    skip_next = False

    for i, part in enumerate(parts):
        if skip_next:
            skip_next = False
            continue

        # Strip -o <output>
        if part == "-o":
            skip_next = True
            continue

        # Strip incompatible flags
        if part in STRIP_FLAGS:
            continue

        # Strip compiler launcher (capture_stderr.sh prefix)
        if "capture_stderr" in part:
            continue

        new_parts.append(part)

    # Add -E flag after compiler
    if len(new_parts) >= 1:
        new_parts.insert(1, "-E")

    return " ".join(shlex.quote(p) for p in new_parts)


def preprocess_file(entry: dict) -> dict:
    """Run preprocessing for a single file and measure output size."""
    source_file = entry["file"]
    cmake_target = entry.get("cmake_target", "")
    is_generated = entry.get("is_generated", False)
    command = entry["command"]

    modified_cmd = modify_command_for_preprocess(command)
    if not modified_cmd:
        return {
            "source_file": source_file,
            "cmake_target": cmake_target,
            "preprocessed_bytes": 0,
            "is_generated": is_generated,
        }

    try:
        with tempfile.NamedTemporaryFile(suffix=".i", delete=False) as tmp:
            tmp_path = tmp.name

        full_cmd = f"{modified_cmd} -o {shlex.quote(tmp_path)}"
        result = subprocess.run(
            full_cmd,
            shell=True,
            capture_output=True,
            cwd=entry.get("directory", "."),
            timeout=120,
        )

        if result.returncode == 0 and os.path.exists(tmp_path):
            size = os.path.getsize(tmp_path)
        else:
            size = 0

        os.unlink(tmp_path)
    except (subprocess.TimeoutExpired, OSError):
        size = 0
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return {
        "source_file": source_file,
        "cmake_target": cmake_target,
        "preprocessed_bytes": size,
        "is_generated": is_generated,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Step 5: Preprocessed size measurement")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()

    cfg = Config.from_yaml(args.config)

    # Load compile commands (enriched version preferred)
    enriched_path = cfg.raw_data_dir / "cmake_file_api" / "compile_commands_enriched.json"
    standard_path = cfg.build_dir / "compile_commands.json"

    if enriched_path.exists():
        with open(enriched_path) as f:
            entries = json.load(f)
        logger.info("Loaded %d entries from enriched compile commands", len(entries))
    elif standard_path.exists():
        with open(standard_path) as f:
            entries = json.load(f)
        logger.info("Loaded %d entries from standard compile_commands.json", len(entries))
    else:
        logger.error("No compile commands found")
        sys.exit(1)

    # Process in parallel
    workers = cfg.preprocess_workers
    logger.info("Preprocessing %d files with %d workers...", len(entries), workers)

    results = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(preprocess_file, entry): entry for entry in entries}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)
            if i % 100 == 0 or i == len(entries):
                logger.info("  processed %d/%d files", i, len(entries))

    # Write output
    cfg.raw_data_dir.mkdir(parents=True, exist_ok=True)
    output_path = cfg.raw_data_dir / "preprocessed_size.csv"
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["source_file", "cmake_target", "preprocessed_bytes", "is_generated"]
        )
        writer.writeheader()
        writer.writerows(results)
    logger.info("Wrote %s (%d rows)", output_path, len(results))

    logger.info("Step 5 complete.")


if __name__ == "__main__":
    main()
