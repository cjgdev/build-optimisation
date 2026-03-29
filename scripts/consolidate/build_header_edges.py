#!/usr/bin/env python3
"""Extract header inclusion graph and header metrics from file_metrics.parquet.

Reads the ``header_tree`` JSON blobs stored per source file and produces:
  - data/processed/header_edges.parquet  — one row per include relationship
  - data/processed/header_metrics.parquet — one row per unique header file

Must run after build_file_metrics.py so that file_metrics.parquet exists.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from build_optimiser.config import Config
from build_optimiser.metrics import HEADER_EDGES_SCHEMA, HEADER_METRICS_SCHEMA

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Prefixes that indicate system / third-party headers.
# Built from inspecting the actual data — macOS Xcode SDK paths and standard locations.
SYSTEM_PREFIXES = (
    "/usr/include",
    "/usr/local/include",
    "/usr/lib/",
    "/Applications/Xcode.app/",
    "/Library/Developer/",
)

SYSTEM_PATH_FRAGMENTS = (
    "/third_party/",
    "/external/",
    "/vendor/",
    "/3rdparty/",
    "/thirdparty/",
)


def is_system_header(path: str) -> bool:
    """Classify a header as system/third-party based on its path."""
    for prefix in SYSTEM_PREFIXES:
        if path.startswith(prefix):
            return True
    for fragment in SYSTEM_PATH_FRAGMENTS:
        if fragment in path:
            return True
    return False


def canonicalise(path: str) -> str:
    """Resolve ``../`` components without following symlinks on missing files."""
    return os.path.normpath(path)


def extract_edges(source_file: str, tree: list[list]) -> list[dict]:
    """Convert a depth-first header_tree into a list of include-edge dicts.

    The tree is a list of [depth, path] pairs from GCC's ``-H`` output.
    Depth starts at 1 (direct includes of the source file).  The source file
    itself is the implicit depth-0 root.
    """
    edges: list[dict] = []
    seen: set[tuple[str, str]] = set()  # (includer, included) dedup within this TU
    stack: list[tuple[int, str]] = [(0, canonicalise(source_file))]  # seed with root

    for depth, path in tree:
        canon_path = canonicalise(path)

        # Pop stack until we find the parent (depth - 1)
        while stack and stack[-1][0] >= depth:
            stack.pop()

        if stack:
            includer = stack[-1][1]
            pair = (includer, canon_path)
            if pair not in seen and includer != canon_path:
                seen.add(pair)
                edges.append({
                    "includer": includer,
                    "included": canon_path,
                    "depth": depth,
                    "source_file": canonicalise(source_file),
                    "is_system": is_system_header(canon_path),
                })

        stack.append((depth, canon_path))

    return edges


def count_lines(filepath: str) -> dict[str, int]:
    """Simple C/C++ line counter: returns sloc and raw byte size."""
    try:
        size = os.path.getsize(filepath)
    except OSError:
        return {"sloc": 0, "source_size_bytes": 0}

    try:
        with open(filepath, errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return {"sloc": 0, "source_size_bytes": size}

    code = 0
    in_block_comment = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if in_block_comment:
            if "*/" in stripped:
                in_block_comment = False
            continue
        if stripped.startswith("//"):
            continue
        if stripped.startswith("/*"):
            if "*/" not in stripped:
                in_block_comment = True
            continue
        code += 1

    return {"sloc": code, "source_size_bytes": size}


def build_target_lookup(target_metrics_path: Path) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Build lookup structures for header→target ownership.

    Returns:
        file_to_target: direct mapping from source file path to cmake_target
        target_dirs: list of (directory_prefix, cmake_target) sorted longest-first
    """
    file_to_target: dict[str, str] = {}
    target_dirs: list[tuple[str, str]] = []

    if not target_metrics_path.exists():
        logger.warning("target_metrics.parquet not found — ownership will be null")
        return file_to_target, target_dirs

    tm = pd.read_parquet(target_metrics_path)
    for _, row in tm.iterrows():
        target = row["cmake_target"]
        sources: list[str] = []
        if pd.notna(row.get("source_files")):
            sources = json.loads(row["source_files"])
        if pd.notna(row.get("generated_files")):
            sources.extend(json.loads(row["generated_files"]))

        dirs: set[str] = set()
        for src in sources:
            canon = canonicalise(src)
            file_to_target[canon] = target
            dirs.add(os.path.dirname(canon))

        for d in dirs:
            target_dirs.append((d, target))

    # Sort longest prefix first for best-match
    target_dirs.sort(key=lambda x: len(x[0]), reverse=True)
    return file_to_target, target_dirs


def resolve_target(header_path: str, file_to_target: dict[str, str],
                   target_dirs: list[tuple[str, str]]) -> str | None:
    """Determine which cmake_target owns a header file."""
    # Direct lookup
    if header_path in file_to_target:
        return file_to_target[header_path]
    # Longest common directory prefix
    for prefix, target in target_dirs:
        if header_path.startswith(prefix + "/"):
            return target
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Build header edge list and header metrics")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    cfg = Config.from_yaml(args.config)
    processed = cfg.processed_data_dir
    fm_path = processed / "file_metrics.parquet"

    if not fm_path.exists():
        logger.error("file_metrics.parquet not found at %s — run build_file_metrics.py first", fm_path)
        sys.exit(1)

    fm = pd.read_parquet(fm_path)
    logger.info("Loaded file_metrics: %d rows", len(fm))

    # --- 1. Extract header edges ---
    all_edges: list[dict] = []
    trees_processed = 0

    for _, row in fm.iterrows():
        ht = row.get("header_tree")
        if pd.isna(ht) or ht == "[]":
            continue
        tree = json.loads(ht)
        if not tree:
            continue
        edges = extract_edges(row["source_file"], tree)
        all_edges.extend(edges)
        trees_processed += 1

    logger.info("Processed %d header trees, extracted %d edges", trees_processed, len(all_edges))

    if all_edges:
        edges_df = pd.DataFrame(all_edges)
    else:
        edges_df = pd.DataFrame(columns=["includer", "included", "depth", "source_file", "is_system"])

    edges_df["depth"] = edges_df["depth"].astype("int64")
    edges_df["is_system"] = edges_df["is_system"].astype("bool")

    processed.mkdir(parents=True, exist_ok=True)
    edges_table = pa.Table.from_pandas(edges_df, schema=HEADER_EDGES_SCHEMA, preserve_index=False)
    edges_path = processed / "header_edges.parquet"
    pq.write_table(edges_table, edges_path)
    logger.info("Wrote %s (%d rows)", edges_path, len(edges_df))

    # --- 2. Build header metrics ---
    # Collect all unique headers that appear as "included" in edges
    all_headers: set[str] = set()
    if not edges_df.empty:
        all_headers = set(edges_df["included"].unique())
    # Also add includers that are headers (not source files)
    header_exts = {".h", ".hh", ".hpp", ".hxx", ".inl", ".inc", ".ipp", ".tpp"}
    if not edges_df.empty:
        for inc in edges_df["includer"].unique():
            if Path(inc).suffix.lower() in header_exts:
                all_headers.add(inc)

    logger.info("Found %d unique header files", len(all_headers))

    # Build target ownership lookup
    tm_path = processed / "target_metrics.parquet"
    file_to_target, target_dirs = build_target_lookup(tm_path)

    # Build metrics for each header
    header_rows: list[dict] = []
    for header_path in sorted(all_headers):
        system = is_system_header(header_path)
        target = resolve_target(header_path, file_to_target, target_dirs) if not system else None

        if system or not os.path.exists(header_path):
            sloc = 0
            size_bytes = 0
        else:
            counts = count_lines(header_path)
            sloc = counts["sloc"]
            size_bytes = counts["source_size_bytes"]

        header_rows.append({
            "header_file": header_path,
            "cmake_target": target,
            "sloc": sloc,
            "source_size_bytes": size_bytes,
            "is_system": system,
        })

    hm_df = pd.DataFrame(header_rows) if header_rows else pd.DataFrame(
        columns=["header_file", "cmake_target", "sloc", "source_size_bytes", "is_system"]
    )
    hm_df["sloc"] = hm_df["sloc"].astype("int64")
    hm_df["source_size_bytes"] = hm_df["source_size_bytes"].astype("int64")
    hm_df["is_system"] = hm_df["is_system"].astype("bool")

    hm_table = pa.Table.from_pandas(hm_df, schema=HEADER_METRICS_SCHEMA, preserve_index=False)
    hm_path = processed / "header_metrics.parquet"
    pq.write_table(hm_table, hm_path)
    logger.info("Wrote %s (%d rows, %d system, %d project)",
                hm_path, len(hm_df),
                int(hm_df["is_system"].sum()),
                int((~hm_df["is_system"]).sum()))


if __name__ == "__main__":
    main()
