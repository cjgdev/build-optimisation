#!/usr/bin/env python3
"""Step 2: Collect git change history for all known source files.

Runs git log --numstat over the configured time window, scoped to files
that participate in the build (from files.json).

Outputs:
    - data/raw/git_history_detail.csv        (one row per file-commit pair)
    - data/raw/git_history_summary.csv       (one row per file, aggregated)
    - data/raw/contributor_file_commits.csv  (per-contributor-per-file commit counts)
    - data/raw/contributors.csv              (per-contributor summary)
    - data/processed/git_commit_log.parquet  (one row per commit × file, excluding merges and mega-commits)
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from buildanalysis.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

COMMIT_RE = re.compile(r"^COMMIT:([a-f0-9]+)\|(.+)\|(.+)\|(.+)\|(.*)$")
NUMSTAT_RE = re.compile(r"^(\d+|-)\t(\d+|-)\t(.+)$")


def parse_git_log(output: str, git_toplevel: str) -> list[dict]:
    """Parse git log --numstat output into per-file commit records."""
    records = []
    current_commit = None

    for line in output.splitlines():
        commit_match = COMMIT_RE.match(line)
        if commit_match:
            current_commit = {
                "commit_hash": commit_match.group(1),
                "commit_date": commit_match.group(2),
                "author": commit_match.group(3),
                "author_email": commit_match.group(4),
                "message": commit_match.group(5),
            }
            continue

        if current_commit is None:
            continue

        numstat_match = NUMSTAT_RE.match(line)
        if numstat_match:
            added = numstat_match.group(1)
            deleted = numstat_match.group(2)
            filepath = numstat_match.group(3)

            # Skip binary files (shown as - - path)
            if added == "-" or deleted == "-":
                continue

            # Canonicalise path relative to git toplevel
            canonical = os.path.realpath(os.path.join(git_toplevel, filepath))

            records.append(
                {
                    **current_commit,
                    "lines_added": int(added),
                    "lines_deleted": int(deleted),
                    "source_file": canonical,
                }
            )

    return records


MAX_FILES_PER_COMMIT = 500


def filter_mega_commits(records: list[dict]) -> list[dict]:
    """Remove records belonging to commits that touch more than MAX_FILES_PER_COMMIT files."""
    files_per_commit: dict[str, set[str]] = defaultdict(set)
    for r in records:
        files_per_commit[r["commit_hash"]].add(r["source_file"])

    mega_hashes = set()
    for commit_hash, files in files_per_commit.items():
        if len(files) > MAX_FILES_PER_COMMIT:
            mega_hashes.add(commit_hash)
            logger.warning(
                "Skipping mega-commit %s (%d files > %d threshold)",
                commit_hash[:12],
                len(files),
                MAX_FILES_PER_COMMIT,
            )

    if mega_hashes:
        records = [r for r in records if r["commit_hash"] not in mega_hashes]
        logger.info("Filtered out %d mega-commits, %d records remain", len(mega_hashes), len(records))

    return records


def write_commit_log_parquet(records: list[dict], output_path: Path) -> None:
    """Write the raw commit-level records to a parquet file."""
    schema = pa.schema(
        [
            ("commit_hash", pa.string()),
            ("timestamp", pa.timestamp("us", tz="UTC")),
            ("contributor", pa.string()),
            ("source_file", pa.string()),
            ("lines_added", pa.int64()),
            ("lines_deleted", pa.int64()),
        ]
    )

    rows = []
    for r in records:
        # Parse ISO 8601 timestamp to UTC datetime
        ts = datetime.fromisoformat(r["commit_date"]).astimezone(timezone.utc)
        rows.append(
            {
                "commit_hash": r["commit_hash"],
                "timestamp": ts,
                "contributor": r["author_email"],
                "source_file": r["source_file"],
                "lines_added": r["lines_added"],
                "lines_deleted": r["lines_deleted"],
            }
        )

    if rows:
        import pandas as pd

        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
    else:
        table = pa.table({name: pa.array([], type=field.type) for name, field in zip(schema.names, schema)})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, output_path)
    logger.info("Wrote %s (%d rows)", output_path, len(rows))


def summarise(records: list[dict]) -> list[dict]:
    """Aggregate per-file commit records into summary statistics."""
    by_file: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_file[r["source_file"]].append(r)

    summaries = []
    for source_file, commits in by_file.items():
        authors = set(c["author"] for c in commits)
        dates = [c["commit_date"] for c in commits]
        summaries.append(
            {
                "source_file": source_file,
                "commit_count": len(commits),
                "total_lines_added": sum(c["lines_added"] for c in commits),
                "total_lines_deleted": sum(c["lines_deleted"] for c in commits),
                "total_churn": sum(c["lines_added"] + c["lines_deleted"] for c in commits),
                "distinct_authors": len(authors),
                "first_change_date": min(dates),
                "last_change_date": max(dates),
            }
        )

    return summaries


def summarise_contributor_files(records: list[dict]) -> list[dict]:
    """Aggregate per-contributor-per-file commit counts."""
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for r in records:
        key = (r["author_email"], r["source_file"])
        counts[key] += 1

    return [
        {"contributor": email, "source_file": source_file, "commit_count": count}
        for (email, source_file), count in sorted(counts.items())
    ]


def summarise_contributors(records: list[dict]) -> list[dict]:
    """Aggregate per-contributor summary statistics."""
    by_contributor: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_contributor[r["author_email"]].append(r)

    summaries = []
    for contributor, commits in sorted(by_contributor.items()):
        # Deduplicate by commit hash to count distinct commits
        unique_hashes = set()
        files = set()
        dates = []
        for c in commits:
            unique_hashes.add(c["commit_hash"])
            files.add(c["source_file"])
            dates.append(c["commit_date"])
        summaries.append(
            {
                "contributor": contributor,
                "total_commits": len(unique_hashes),
                "first_commit_date": min(dates),
                "last_commit_date": max(dates),
                "files_touched": len(files),
            }
        )

    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(description="Step 2: Git history collection")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()

    cfg = Config.from_yaml(args.config)
    source_dir = str(cfg.source_dir)

    # Find the git toplevel so paths resolve correctly
    # (source_dir may be a subdirectory within the git repo)
    git_toplevel_result = subprocess.run(
        ["git", "-C", source_dir, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    git_toplevel = git_toplevel_result.stdout.strip()

    # Load file list to scope collection
    files_json = cfg.raw_data_dir / "cmake_file_api" / "files.json"
    if files_json.exists():
        with open(files_json) as f:
            files_data = json.load(f)
        known_files = {entry["path"] for entry in files_data if not entry.get("is_generated", False)}
        logger.info("Scoped to %d non-generated files from files.json", len(known_files))
    else:
        known_files = None
        logger.warning("files.json not found — collecting history for all C++ files")

    # Run git log from repo root, scoped to the source directory
    since = f"{cfg.git_history_months} months ago"
    cmd = [
        "git",
        "-C",
        git_toplevel,
        "log",
        f"--since={since}",
        "--no-merges",
        "--numstat",
        "--pretty=format:COMMIT:%H|%aI|%an|%ae|%s",
        "--",
        f"{source_dir}/**/*.cpp",
        f"{source_dir}/**/*.cc",
        f"{source_dir}/**/*.cxx",
        f"{source_dir}/**/*.h",
        f"{source_dir}/**/*.hpp",
        f"{source_dir}/**/*.hxx",
    ]

    logger.info("Running git log (since %s)...", since)
    start = time.monotonic()
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    elapsed = time.monotonic() - start
    logger.info("Git log completed in %.1fs", elapsed)

    # Parse — paths in git numstat are relative to git_toplevel
    records = parse_git_log(result.stdout, git_toplevel)
    logger.info("Parsed %d file-commit records", len(records))

    # Filter to known files if we have a file list
    if known_files:
        records = [r for r in records if r["source_file"] in known_files]
        logger.info("After scoping: %d records for known build files", len(records))

    # Filter out mega-commits (>500 files) that distort coupling analysis
    records = filter_mega_commits(records)

    # Write commit-level parquet (before aggregation)
    commit_log_path = cfg.processed_data_dir / "git_commit_log.parquet"
    write_commit_log_parquet(records, commit_log_path)

    # Write detail CSV
    cfg.raw_data_dir.mkdir(parents=True, exist_ok=True)
    detail_path = cfg.raw_data_dir / "git_history_detail.csv"
    detail_fields = [
        "source_file",
        "commit_hash",
        "commit_date",
        "author",
        "author_email",
        "message",
        "lines_added",
        "lines_deleted",
    ]
    with open(detail_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=detail_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    logger.info("Wrote %s (%d rows)", detail_path, len(records))

    # Write summary CSV
    summaries = summarise(records)
    summary_path = cfg.raw_data_dir / "git_history_summary.csv"
    summary_fields = [
        "source_file",
        "commit_count",
        "total_lines_added",
        "total_lines_deleted",
        "total_churn",
        "distinct_authors",
        "first_change_date",
        "last_change_date",
    ]
    with open(summary_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(summaries)
    logger.info("Wrote %s (%d rows)", summary_path, len(summaries))

    # Write contributor-file commit counts
    contributor_files = summarise_contributor_files(records)
    contrib_file_path = cfg.raw_data_dir / "contributor_file_commits.csv"
    contrib_file_fields = ["contributor", "source_file", "commit_count"]
    with open(contrib_file_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=contrib_file_fields)
        writer.writeheader()
        writer.writerows(contributor_files)
    logger.info("Wrote %s (%d rows)", contrib_file_path, len(contributor_files))

    # Write contributor summary
    contributors = summarise_contributors(records)
    contributors_path = cfg.raw_data_dir / "contributors.csv"
    contributors_fields = ["contributor", "total_commits", "first_commit_date", "last_commit_date", "files_touched"]
    with open(contributors_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=contributors_fields)
        writer.writeheader()
        writer.writerows(contributors)
    logger.info("Wrote %s (%d rows)", contributors_path, len(contributors))

    logger.info("Step 2 complete.")


if __name__ == "__main__":
    main()
