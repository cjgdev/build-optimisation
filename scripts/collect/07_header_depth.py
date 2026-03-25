#!/usr/bin/env python3
"""Measure the maximum header inclusion depth for each source file."""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from build_optimiser.config import load_config, build_cmake_command, build_ninja_command, build_environment
from build_optimiser.metrics import parse_cmake_target_from_object_path


def parse_header_depth_output(stderr_path: Path) -> dict[str, dict]:
    """Parse GCC -H output from a single file's stderr.

    Lines look like: '... path/to/header.h' where dot count = depth.
    """
    max_depth = 0
    unique_headers: set[str] = set()
    total_includes = 0

    with open(stderr_path, errors="replace") as f:
        for line in f:
            match = re.match(r"^(\.+)\s+(.+)$", line)
            if match:
                depth = len(match.group(1))
                header = match.group(2).strip()
                max_depth = max(max_depth, depth)
                unique_headers.add(header)
                total_includes += 1

    return {
        "max_depth": max_depth,
        "unique_headers": len(unique_headers),
        "total_includes": total_includes,
    }


def main() -> None:
    cfg = load_config()
    build_dir = Path(cfg["build_dir"])
    raw_dir = Path(cfg["raw_data_dir"])
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Set up stderr capture directory
    stderr_dir = raw_dir / "header_depth_stderr"
    stderr_dir.mkdir(parents=True, exist_ok=True)

    # Path to the wrapper script
    wrapper = PROJECT_ROOT / "scripts" / "collect" / "wrappers" / "capture_stderr.sh"

    env = build_environment(cfg)

    # Reconfigure with -H -fsyntax-only and the wrapper
    pass_flags = {"CMAKE_CXX_FLAGS": "-H -fsyntax-only"}
    extra_args = []
    if wrapper.exists():
        extra_args.append(f"-DCMAKE_CXX_COMPILER_LAUNCHER={wrapper}")
        env["BUILD_OPTIMISER_STDERR_DIR"] = str(stderr_dir)

    cmd = build_cmake_command(cfg, pass_flags=pass_flags, extra_args=extra_args)
    print(f"Configuring: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        print(f"CMake configure failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Build (syntax-only, so relatively fast)
    ninja_cmd = build_ninja_command(cfg)
    print(f"Building: {' '.join(ninja_cmd)}")

    if not wrapper.exists():
        # Without wrapper, capture all stderr to a single file
        all_stderr = raw_dir / "header_depth_all.stderr"
        with open(all_stderr, "w") as stderr_f:
            result = subprocess.run(ninja_cmd, stdout=subprocess.PIPE, stderr=stderr_f, text=True, env=env)
    else:
        result = subprocess.run(ninja_cmd, capture_output=True, text=True, env=env)

    # Build source-to-target mapping from compile_commands.json
    cc_path = build_dir / "compile_commands.json"
    source_to_target: dict[str, str] = {}
    if cc_path.exists():
        with open(cc_path) as f:
            for entry in json.load(f):
                command = entry.get("command", "")
                output_match = re.search(r"-o\s+(\S+)", command)
                if output_match:
                    target = parse_cmake_target_from_object_path(output_match.group(1))
                    if target:
                        source_to_target[entry["file"]] = target

    # Parse stderr files
    output_path = raw_dir / "header_depth.csv"
    count = 0
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["source_file", "cmake_target", "max_depth", "unique_headers", "total_includes"],
        )
        writer.writeheader()

        for stderr_file in sorted(stderr_dir.glob("*.stderr")):
            # Reconstruct source file from the log filename
            source_name = stderr_file.stem.replace("_", "/")
            depth_info = parse_header_depth_output(stderr_file)

            # Try to find matching source file
            cmake_target = ""
            matched_source = source_name
            for src, tgt in source_to_target.items():
                if src.endswith(source_name) or source_name in src:
                    cmake_target = tgt
                    matched_source = src
                    break

            writer.writerow({
                "source_file": matched_source,
                "cmake_target": cmake_target,
                **depth_info,
            })
            count += 1

    print(f"Wrote {count} entries to {output_path}")


if __name__ == "__main__":
    main()
