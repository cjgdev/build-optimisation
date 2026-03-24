#!/usr/bin/env python3
"""Count object files and measure their on-disk size per target."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from build_optimiser.config import load_config


def main() -> None:
    cfg = load_config()
    build_dir = Path(cfg["build_dir"])
    raw_dir = Path(cfg["raw_data_dir"])
    raw_dir.mkdir(parents=True, exist_ok=True)

    cmake_files_dir = build_dir / "CMakeFiles"
    if not cmake_files_dir.exists():
        print(f"Error: {cmake_files_dir} not found. Run step 02 first.", file=sys.stderr)
        sys.exit(1)

    output_path = raw_dir / "object_files.csv"
    count = 0
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["cmake_target", "object_file_path", "size_bytes"])
        writer.writeheader()

        for target_dir in sorted(cmake_files_dir.iterdir()):
            if not target_dir.is_dir() or not target_dir.name.endswith(".dir"):
                continue
            target_name = target_dir.name[:-len(".dir")]

            for obj_file in target_dir.rglob("*.o"):
                size = obj_file.stat().st_size
                writer.writerow({
                    "cmake_target": target_name,
                    "object_file_path": str(obj_file),
                    "size_bytes": size,
                })
                count += 1

    print(f"Wrote {count} object file entries to {output_path}")


if __name__ == "__main__":
    main()
