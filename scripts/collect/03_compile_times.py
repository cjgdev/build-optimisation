#!/usr/bin/env python3
"""Measure wall-clock compile time for every source file via Ninja log and -ftime-report."""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from build_optimiser.config import load_config, build_cmake_command, build_ninja_command, build_environment
from build_optimiser.metrics import parse_cmake_target_from_object_path


def parse_ninja_log(ninja_log_path: Path) -> list[dict]:
    """Parse .ninja_log and extract timing information."""
    entries = []
    with open(ninja_log_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 5:
                start_ms = int(parts[0])
                end_ms = int(parts[1])
                # parts[2] is mtime_ms (restat)
                # parts[3] is command_hash
                target_path = parts[4] if len(parts) > 4 else parts[3]
                entries.append({
                    "target_path": target_path,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "wall_clock_ms": end_ms - start_ms,
                })
    return entries


def map_object_to_source(build_dir: Path) -> dict[str, str]:
    """Map .o file paths to source file paths using compile_commands.json."""
    cc_path = build_dir / "compile_commands.json"
    if not cc_path.exists():
        return {}

    with open(cc_path) as f:
        entries = json.load(f)

    mapping = {}
    for entry in entries:
        source = entry.get("file", "")
        command = entry.get("command", "")
        output_match = re.search(r"-o\s+(\S+)", command)
        if output_match:
            output = output_match.group(1)
            mapping[output] = source
    return mapping


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
        print(f"CMake configure failed (exit {result.returncode}):", file=sys.stderr)
        if result.stdout:
            print(f"CMake stdout:\n{result.stdout}", file=sys.stderr)
        if result.stderr:
            print(f"CMake stderr:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Clean and rebuild
    clean_cmd = ["ninja", "-C", str(build_dir), "clean"]
    print(f"Cleaning: {' '.join(clean_cmd)}")
    clean_result = subprocess.run(clean_cmd, capture_output=True, text=True, env=env)
    if clean_result.returncode != 0:
        print(f"Warning: clean failed (exit {clean_result.returncode})", file=sys.stderr)
        if clean_result.stdout:
            print(f"clean stdout:\n{clean_result.stdout}", file=sys.stderr)
        if clean_result.stderr:
            print(f"clean stderr:\n{clean_result.stderr}", file=sys.stderr)

    # Full build, capturing stderr for ftime-report
    ninja_cmd = build_ninja_command(cfg)
    print(f"Building: {' '.join(ninja_cmd)}")
    ftime_log = raw_dir / "ftime_report.log"
    raw_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(ninja_cmd, capture_output=True, text=True, env=env)

    # Write stderr to ftime_report.log (contains -ftime-report output)
    with open(ftime_log, "w") as ftime_f:
        ftime_f.write(result.stderr)

    if result.returncode != 0:
        print(f"Build failed (exit {result.returncode})", file=sys.stderr)
        if result.stdout:
            print(f"Build stdout:\n{result.stdout}", file=sys.stderr)
        if result.stderr:
            print(f"Build stderr:\n{result.stderr}", file=sys.stderr)
        # Continue anyway to parse what we got

    # Parse ninja log
    ninja_log_path = build_dir / ".ninja_log"
    if not ninja_log_path.exists():
        print("Error: .ninja_log not found", file=sys.stderr)
        sys.exit(1)

    entries = parse_ninja_log(ninja_log_path)
    obj_to_source = map_object_to_source(build_dir)

    # Write parsed ninja log
    output_path = raw_dir / "ninja_log.tsv"
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["target_path", "source_file", "cmake_target", "start_ms", "end_ms", "wall_clock_ms"],
            delimiter="\t",
        )
        writer.writeheader()
        for entry in entries:
            target_path = entry["target_path"]
            source_file = obj_to_source.get(target_path, "")
            cmake_target = parse_cmake_target_from_object_path(target_path) or ""
            writer.writerow({
                "target_path": target_path,
                "source_file": source_file,
                "cmake_target": cmake_target,
                "start_ms": entry["start_ms"],
                "end_ms": entry["end_ms"],
                "wall_clock_ms": entry["wall_clock_ms"],
            })

    print(f"Wrote {len(entries)} entries to {output_path}")

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
    current_entries = []

    with open(log_path) as f:
        for line in f:
            # GCC ftime-report lines look like:
            # Time variable                                   usr           sys          wall
            #  phase opt and target          :   0.01 (  5%)   0.00 (  0%)   0.01 (  5%)
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
