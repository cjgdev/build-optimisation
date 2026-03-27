#!/usr/bin/env python3
"""Step 3: Execute an instrumented build and parse stderr logs.

Runs ninja with the build tree configured in step 1 (which includes
-ftime-report, -H, and the capture_stderr.sh wrapper). Parses the
captured per-file stderr logs for GCC timing data and header trees.

Outputs:
    - data/raw/ftime_report.json   (GCC phase timing per file)
    - data/raw/header_data.json    (header inclusion data per file)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from build_optimiser.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# GCC -ftime-report phase line pattern
# Example: " phase parsing                 :   0.12 ( 14%)   0.01 ( 25%)   0.13 ( 14%)  8027 kB ( 10%)"
FTIME_RE = re.compile(
    r"^\s*(.+?)\s*:\s+"
    r"(\d+\.\d+)\s+\(\s*\d+%\)\s+"  # usr
    r"(\d+\.\d+)\s+\(\s*\d+%\)\s+"  # sys
    r"(\d+\.\d+)\s+\(\s*\d+%\)\s+"  # wall
    r"(\d+)\s+kB"                     # GGC memory
)
FTIME_TOTAL_RE = re.compile(
    r"^\s*TOTAL\s*:\s+"
    r"(\d+\.\d+)\s+"  # usr
    r"(\d+\.\d+)\s+"  # sys
    r"(\d+\.\d+)\s+"  # wall
)

# GCC -H header inclusion line: dots followed by a path
HEADER_RE = re.compile(r"^(\.+)\s+(.+)$")


def parse_ftime_report_text(text: str) -> dict:
    """Parse GCC -ftime-report output from stderr text.

    Returns dict with 'phases' (name -> wall_seconds) and 'wall_total_ms'.
    """
    phases: dict[str, float] = {}

    for line in text.splitlines():
        total_match = FTIME_TOTAL_RE.match(line)
        if total_match:
            phases["TOTAL"] = float(total_match.group(3))
            continue

        match = FTIME_RE.match(line)
        if match:
            phase_name = match.group(1).strip()
            wall_time = float(match.group(4))
            phases[phase_name] = wall_time

    wall_total_ms = int(phases.get("TOTAL", 0) * 1000)

    return {
        "phases": phases,
        "wall_total_ms": wall_total_ms,
    }


def parse_header_tree_text(text: str) -> dict:
    """Parse GCC -H output from stderr text.

    Returns dict with max_include_depth, unique_headers, total_includes, header_tree.
    """
    tree: list[list] = []
    headers_seen: set[str] = set()

    for line in text.splitlines():
        match = HEADER_RE.match(line)
        if match:
            depth = len(match.group(1))
            header_path = match.group(2).strip()
            tree.append([depth, header_path])
            headers_seen.add(header_path)

    return {
        "max_include_depth": max((t[0] for t in tree), default=0),
        "unique_headers": len(headers_seen),
        "total_includes": len(tree),
        "header_tree": tree,
    }


def source_file_from_log_name(log_name: str, source_dir: str) -> str | None:
    """Reverse the log filename back to a canonical source path.

    The wrapper hashes the source path with MD5 (first 16 hex chars), so the
    transformation is not reversible. Callers should use build_log_file_map()
    which matches against known files instead.
    """
    if log_name.endswith(".stderr"):
        log_name = log_name[:-7]
    # Cannot reverse a hash — return None and let the caller match against known files
    return None


def build_log_file_map(stderr_dir: Path, files_json_path: Path) -> dict[str, str]:
    """Map stderr log files to canonical source file paths.

    Uses the file list from the File API to match log filenames back to source files.
    """
    # Load known files
    if files_json_path.exists():
        with open(files_json_path) as f:
            files_data = json.load(f)
        # Build a mapping: hashed name -> canonical path
        known_files: dict[str, str] = {}
        for entry in files_data:
            path = entry["path"]
            hashed = hashlib.md5(path.encode()).hexdigest()[:16] + ".stderr"
            known_files[hashed] = path
    else:
        known_files = {}

    result: dict[str, str] = {}
    for log_file in stderr_dir.iterdir():
        if not log_file.name.endswith(".stderr"):
            continue
        canonical = known_files.get(log_file.name)
        if canonical:
            result[str(log_file)] = canonical

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Step 3: Instrumented build + stderr parsing")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--skip-build", action="store_true", help="Skip build, only parse existing logs")
    args = parser.parse_args()

    cfg = Config.from_yaml(args.config)

    stderr_dir = cfg.raw_data_dir / "stderr_logs"
    stderr_dir.mkdir(parents=True, exist_ok=True)
    os.environ["BUILD_OPTIMISER_STDERR_DIR"] = str(stderr_dir)

    if not args.skip_build:
        # Clean and build
        logger.info("Running ninja clean...")
        subprocess.run(
            cfg.ninja_command(targets=["clean"]),
            check=False,  # clean may fail if no build exists yet
        )

        logger.info("Running instrumented build...")
        start = time.monotonic()
        result = subprocess.run(cfg.ninja_command(), check=False)
        elapsed = time.monotonic() - start
        logger.info("Build completed in %.1fs (exit code %d)", elapsed, result.returncode)

        if result.returncode != 0:
            raise RuntimeError(f"Build failed with exit code {result.returncode}")

    # Parse stderr logs
    files_json = cfg.raw_data_dir / "cmake_file_api" / "files.json"
    log_map = build_log_file_map(stderr_dir, files_json)
    logger.info("Found %d stderr log files", len(log_map))

    ftime_data: dict[str, dict] = {}
    header_data: dict[str, dict] = {}

    for log_path, source_file in log_map.items():
        text = Path(log_path).read_text(errors="replace")

        ftime = parse_ftime_report_text(text)
        if ftime["phases"]:
            ftime_data[source_file] = ftime

        headers = parse_header_tree_text(text)
        if headers["total_includes"] > 0:
            header_data[source_file] = headers

    # Write outputs
    cfg.raw_data_dir.mkdir(parents=True, exist_ok=True)

    ftime_path = cfg.raw_data_dir / "ftime_report.json"
    with open(ftime_path, "w") as f:
        json.dump(ftime_data, f, indent=2)
    logger.info("Wrote %s (%d files)", ftime_path, len(ftime_data))

    header_path = cfg.raw_data_dir / "header_data.json"
    with open(header_path, "w") as f:
        json.dump(header_data, f, indent=2)
    logger.info("Wrote %s (%d files)", header_path, len(header_data))

    logger.info("Step 3 complete.")


if __name__ == "__main__":
    main()
