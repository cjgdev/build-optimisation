#!/usr/bin/env python3
"""Measure wall-clock compile time for every source file via ninja compdb and log."""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from build_optimiser.config import (
    build_cmake_command,
    build_environment,
    build_ninja_command,
    load_config,
)
from build_optimiser.ninja import (
    join_compdb_with_log,
    parse_ninja_log,
    run_compdb,
    run_recompact,
)


def main() -> None:
    cfg = load_config()
    build_dir = Path(cfg["build_dir"])
    raw_dir = Path(cfg["raw_data_dir"])

    env = build_environment(cfg)

    # Reconfigure with -ftime-report
    cmd = build_cmake_command(cfg, pass_flags={"CMAKE_CXX_FLAGS": "-ftime-report"})
    print(f"Configuring: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        print(f"CMake configure failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Clean and rebuild
    clean_cmd = ["ninja", "-C", str(build_dir), "clean"]
    print(f"Cleaning: {' '.join(clean_cmd)}")
    subprocess.run(clean_cmd, capture_output=True, text=True, env=env)

    # Full build, capturing stderr for ftime-report
    ninja_cmd = build_ninja_command(cfg)
    print(f"Building: {' '.join(ninja_cmd)}")
    ftime_log = raw_dir / "ftime_report.log"
    raw_dir.mkdir(parents=True, exist_ok=True)
    with open(ftime_log, "w") as ftime_f:
        result = subprocess.run(
            ninja_cmd, stdout=subprocess.PIPE, stderr=ftime_f, text=True, env=env,
        )
    if result.returncode != 0:
        print(f"Build failed (exit {result.returncode})", file=sys.stderr)

    # Recompact ninja_log, get compdb, parse log, and join
    run_recompact(str(build_dir))
    compdb_entries = run_compdb(str(build_dir))
    log_entries = parse_ninja_log(str(build_dir / ".ninja_log"))
    joined = join_compdb_with_log(compdb_entries, log_entries)

    # Write parsed results
    output_path = raw_dir / "ninja_log.tsv"
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "target_path", "source_file", "cmake_target",
                "start_ms", "end_ms", "wall_clock_ms",
            ],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(joined)

    print(f"Wrote {len(joined)} entries to {output_path}")

    # Parse ftime-report into JSON (best effort)
    try:
        ftime_data = _parse_ftime_report(ftime_log)
        ftime_json_path = raw_dir / "ftime_report.json"
        with open(ftime_json_path, "w") as f:
            json.dump(ftime_data, f, indent=2)
        print(f"Wrote ftime report to {ftime_json_path}")
    except Exception as e:
        print(f"Warning: Could not parse ftime report: {e}", file=sys.stderr)


def _parse_ftime_report(log_path: Path) -> list[dict]:
    """Best-effort parse of GCC -ftime-report output."""
    results = []
    current_file = None
    current_entries: list[dict] = []

    with open(log_path) as f:
        for line in f:
            file_match = re.search(r"Compiling\s+(\S+)", line)
            if file_match:
                if current_file and current_entries:
                    results.append({"file": current_file, "phases": current_entries})
                current_file = file_match.group(1)
                current_entries = []
                continue

            time_match = re.match(
                r"\s+(.+?)\s*:\s+([\d.]+)\s+\(\s*\d+%\)\s+([\d.]+)\s+\(\s*\d+%\)\s+([\d.]+)",
                line,
            )
            if time_match:
                current_entries.append({
                    "phase": time_match.group(1).strip(),
                    "usr_s": float(time_match.group(2)),
                    "sys_s": float(time_match.group(3)),
                    "wall_s": float(time_match.group(4)),
                })

    if current_file and current_entries:
        results.append({"file": current_file, "phases": current_entries})

    return results


if __name__ == "__main__":
    main()
