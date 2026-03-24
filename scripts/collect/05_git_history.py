#!/usr/bin/env python3
"""Count how often each source file has been modified over a configurable time window."""

from __future__ import annotations

import csv
import subprocess
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from build_optimiser.config import load_config


def main() -> None:
    cfg = load_config()
    source_dir = cfg["source_dir"]
    raw_dir = Path(cfg["raw_data_dir"])
    raw_dir.mkdir(parents=True, exist_ok=True)
    months = cfg.get("git_history_months", 12)

    # Get file change counts
    result = subprocess.run(
        [
            "git", "-C", source_dir, "log",
            f"--since={months} months ago",
            "--name-only",
            "--pretty=format:",
            "--", "*.cpp", "*.cc", "*.cxx", "*.h", "*.hpp", "*.hxx",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"git log failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    file_counts = Counter(
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    )

    # Get churn stats (lines added/deleted)
    numstat_result = subprocess.run(
        [
            "git", "-C", source_dir, "log",
            f"--since={months} months ago",
            "--numstat",
            "--pretty=format:",
            "--", "*.cpp", "*.cc", "*.cxx", "*.h", "*.hpp", "*.hxx",
        ],
        capture_output=True,
        text=True,
    )

    churn: dict[str, dict[str, int]] = {}
    if numstat_result.returncode == 0:
        for line in numstat_result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) == 3:
                added, deleted, filepath = parts
                if added == "-" or deleted == "-":
                    continue  # binary file
                if filepath not in churn:
                    churn[filepath] = {"lines_added": 0, "lines_deleted": 0}
                churn[filepath]["lines_added"] += int(added)
                churn[filepath]["lines_deleted"] += int(deleted)

    # Write output
    output_path = raw_dir / "git_history.csv"
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["source_file", "commit_count", "lines_added", "lines_deleted"]
        )
        writer.writeheader()
        for filepath, count in sorted(file_counts.items()):
            file_churn = churn.get(filepath, {})
            writer.writerow({
                "source_file": filepath,
                "commit_count": count,
                "lines_added": file_churn.get("lines_added", 0),
                "lines_deleted": file_churn.get("lines_deleted", 0),
            })

    print(f"Wrote {len(file_counts)} file entries to {output_path}")


if __name__ == "__main__":
    main()
