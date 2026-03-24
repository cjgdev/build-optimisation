#!/usr/bin/env python3
"""Measure the wall-clock time for the link step of each target."""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from build_optimiser.config import load_config, build_cmake_command, build_ninja_command


def parse_ninja_log_links(ninja_log_path: Path) -> list[dict]:
    """Parse .ninja_log and extract link step timing.

    Link steps are identified by output paths that are NOT .o files
    (i.e., they are .a, .so, or extensionless executables).
    """
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
                target_path = parts[4] if len(parts) > 4 else parts[3]

                # Identify link steps: not .o, not .o.d
                if target_path.endswith(".o") or target_path.endswith(".o.d"):
                    continue

                # This is likely a link step
                entries.append({
                    "output_path": target_path,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "link_time_ms": end_ms - start_ms,
                })
    return entries


def infer_target_name(output_path: str) -> str:
    """Infer CMake target name from the linked output path."""
    p = Path(output_path)
    name = p.stem
    # Strip 'lib' prefix for libraries
    if name.startswith("lib"):
        name = name[3:]
    return name


def main() -> None:
    cfg = load_config()
    build_dir = Path(cfg["build_dir"])
    raw_dir = Path(cfg["raw_data_dir"])
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Reconfigure with normal flags (clean build)
    cmd = build_cmake_command(cfg)
    print(f"Configuring: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"CMake configure failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Clean and full rebuild
    clean_cmd = ["ninja", "-C", str(build_dir), "clean"]
    print(f"Cleaning: {' '.join(clean_cmd)}")
    subprocess.run(clean_cmd, capture_output=True, text=True)

    ninja_cmd = build_ninja_command(cfg)
    print(f"Building: {' '.join(ninja_cmd)}")
    result = subprocess.run(ninja_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Build failed (exit {result.returncode})", file=sys.stderr)

    # Parse ninja log for link steps
    ninja_log_path = build_dir / ".ninja_log"
    if not ninja_log_path.exists():
        print("Error: .ninja_log not found", file=sys.stderr)
        sys.exit(1)

    entries = parse_ninja_log_links(ninja_log_path)

    output_path = raw_dir / "link_times.csv"
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["cmake_target", "output_path", "link_time_ms"]
        )
        writer.writeheader()
        for entry in entries:
            writer.writerow({
                "cmake_target": infer_target_name(entry["output_path"]),
                "output_path": entry["output_path"],
                "link_time_ms": entry["link_time_ms"],
            })

    print(f"Wrote {len(entries)} link time entries to {output_path}")


if __name__ == "__main__":
    main()
