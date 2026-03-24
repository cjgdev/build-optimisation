#!/usr/bin/env python3
"""Measure the size of the preprocessed translation unit for each source file."""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from build_optimiser.config import load_config
from build_optimiser.metrics import parse_cmake_target_from_object_path


def preprocess_file(command_entry: dict) -> dict | None:
    """Run a single compilation command with -E and measure output size.

    Uses Approach B: extract compile command from compile_commands.json,
    replace output with -E piped to wc -c.
    """
    source_file = command_entry.get("file", "")
    command = command_entry.get("command", "")
    directory = command_entry.get("directory", "")

    if not command:
        return None

    # Extract target from -o flag
    output_match = re.search(r"-o\s+(\S+)", command)
    cmake_target = ""
    if output_match:
        cmake_target = parse_cmake_target_from_object_path(output_match.group(1)) or ""

    # Modify command: remove -o flag and add -E
    # Split command into parts
    parts = command.split()
    new_parts = []
    skip_next = False
    for i, part in enumerate(parts):
        if skip_next:
            skip_next = False
            continue
        if part == "-o":
            skip_next = True
            continue
        if part.startswith("-o"):
            continue
        new_parts.append(part)

    # Add -E flag (preprocess only)
    # Insert -E after the compiler
    if len(new_parts) > 1:
        new_parts.insert(1, "-E")

    try:
        result = subprocess.run(
            " ".join(new_parts),
            shell=True,
            cwd=directory,
            capture_output=True,
            timeout=120,
        )
        preprocessed_bytes = len(result.stdout)
        return {
            "source_file": source_file,
            "cmake_target": cmake_target,
            "preprocessed_bytes": preprocessed_bytes,
        }
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"Warning: Failed to preprocess {source_file}: {e}", file=sys.stderr)
        return None


def main() -> None:
    cfg = load_config()
    build_dir = Path(cfg["build_dir"])
    raw_dir = Path(cfg["raw_data_dir"])
    raw_dir.mkdir(parents=True, exist_ok=True)
    ninja_jobs = cfg.get("ninja_jobs", 0)
    max_workers = ninja_jobs if ninja_jobs > 0 else None

    # Read compile_commands.json (from step 02's build, or reconfigure)
    cc_path = build_dir / "compile_commands.json"
    if not cc_path.exists():
        # Reconfigure to generate compile_commands.json
        from build_optimiser.config import build_cmake_command
        cmd = build_cmake_command(cfg, pass_flags={"CMAKE_CXX_FLAGS": "-E"})
        print(f"Configuring: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"CMake configure failed:\n{result.stderr}", file=sys.stderr)
            sys.exit(1)

    with open(cc_path) as f:
        compile_commands = json.load(f)

    print(f"Processing {len(compile_commands)} files...")

    output_path = raw_dir / "preprocessed_size.csv"
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(preprocess_file, entry): entry
            for entry in compile_commands
        }
        for i, future in enumerate(as_completed(futures)):
            result = future.result()
            if result:
                results.append(result)
            if (i + 1) % 100 == 0:
                print(f"  Processed {i + 1}/{len(compile_commands)} files")

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["source_file", "cmake_target", "preprocessed_bytes"]
        )
        writer.writeheader()
        for r in sorted(results, key=lambda x: x["source_file"]):
            writer.writerow(r)

    print(f"Wrote {len(results)} entries to {output_path}")


if __name__ == "__main__":
    main()
