#!/usr/bin/env python3
"""Extract the full target dependency DAG as dot files using CMake --graphviz."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from build_optimiser.config import load_config, build_cmake_command


def main() -> None:
    cfg = load_config()
    build_dir = Path(cfg["build_dir"])
    raw_dir = Path(cfg["raw_data_dir"])
    dot_output_dir = raw_dir / "dot"

    # Configure CMake with --graphviz flag
    graph_prefix = build_dir / "graph" / "dependencies"
    graph_prefix.parent.mkdir(parents=True, exist_ok=True)

    cmd = build_cmake_command(cfg, extra_args=[f"--graphviz={graph_prefix}"])
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"CMake configure failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    print(result.stdout)

    # Copy generated dot files to data/raw/dot/
    graph_dir = graph_prefix.parent
    dot_output_dir.mkdir(parents=True, exist_ok=True)

    dot_files = list(graph_dir.glob("*"))
    if not dot_files:
        print("Warning: No graph files generated", file=sys.stderr)
        sys.exit(1)

    for f in dot_files:
        dest = dot_output_dir / f.name
        shutil.copy2(f, dest)
        print(f"  Copied {f.name}")

    print(f"\nCopied {len(dot_files)} files to {dot_output_dir}")


if __name__ == "__main__":
    main()
