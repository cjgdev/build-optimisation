#!/usr/bin/env python3
"""Step 4: Collect object file sizes and source lines of code.

Walks the build tree for .o files and runs a line counter over all source files.
Must run after the build (step 3) so that generated files and objects exist.

Outputs:
    - data/raw/object_files.csv
    - data/raw/sloc.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from build_optimiser.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def find_object_files(build_dir: Path) -> list[Path]:
    """Walk the build tree to find all .o files."""
    return list(build_dir.rglob("*.o"))


def map_object_to_source(
    obj_path: Path,
    build_dir: Path,
    file_index: dict[str, str],
) -> tuple[str | None, str | None]:
    """Map an object file path to its source file and target.

    Object files live under CMakeFiles/<target>.dir/path/to/source.cpp.o
    """
    rel = str(obj_path.relative_to(build_dir))
    parts = rel.split("/")

    # Find CMakeFiles/<target>.dir pattern
    target_name = None
    source_suffix = None
    for i, part in enumerate(parts):
        if part == "CMakeFiles" and i + 1 < len(parts) and parts[i + 1].endswith(".dir"):
            target_name = parts[i + 1][:-4]  # strip .dir
            source_suffix = "/".join(parts[i + 2:])
            break

    if source_suffix and source_suffix.endswith(".o"):
        source_suffix = source_suffix[:-2]  # strip .o

    # Try to find the source file in the file index
    if source_suffix:
        for canonical_path, tgt in file_index.items():
            if canonical_path.endswith(source_suffix):
                return canonical_path, tgt

    return None, target_name


def count_lines_python(filepath: str) -> dict:
    """Simple Python-based line counter as fallback for cloc."""
    try:
        with open(filepath, errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return {"blank_lines": 0, "comment_lines": 0, "code_lines": 0}

    blank = 0
    comment = 0
    code = 0
    in_block_comment = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            blank += 1
        elif in_block_comment:
            comment += 1
            if "*/" in stripped:
                in_block_comment = False
        elif stripped.startswith("//"):
            comment += 1
        elif stripped.startswith("/*"):
            comment += 1
            if "*/" not in stripped:
                in_block_comment = True
        else:
            code += 1

    return {"blank_lines": blank, "comment_lines": comment, "code_lines": code}


def try_cloc(filepaths: list[str]) -> dict[str, dict] | None:
    """Try to run cloc for accurate SLOC counts. Returns None if cloc unavailable."""
    try:
        # Write file list to temp file
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            for fp in filepaths:
                f.write(fp + "\n")
            list_file = f.name

        result = subprocess.run(
            ["cloc", "--by-file", "--json", f"--list-file={list_file}"],
            capture_output=True, text=True, check=True,
        )
        os.unlink(list_file)

        data = json.loads(result.stdout)
        results = {}
        for filepath, counts in data.items():
            if filepath in ("header", "SUM"):
                continue
            if isinstance(counts, dict) and "code" in counts:
                results[filepath] = {
                    "blank_lines": counts.get("blank", 0),
                    "comment_lines": counts.get("comment", 0),
                    "code_lines": counts.get("code", 0),
                    "language": counts.get("language", ""),
                }
        return results
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Step 4: Post-build metrics")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()

    cfg = Config.from_yaml(args.config)

    # Load file index from File API output
    files_json = cfg.raw_data_dir / "cmake_file_api" / "files.json"
    with open(files_json) as f:
        files_data = json.load(f)
    file_index = {entry["path"]: entry["cmake_target"] for entry in files_data}
    generated_files = {entry["path"] for entry in files_data if entry.get("is_generated", False)}

    cfg.raw_data_dir.mkdir(parents=True, exist_ok=True)

    # Object file sizes
    logger.info("Scanning for object files...")
    obj_files = find_object_files(cfg.build_dir)
    logger.info("Found %d object files", len(obj_files))

    obj_records = []
    for obj_path in obj_files:
        source_file, target = map_object_to_source(obj_path, cfg.build_dir, file_index)
        obj_records.append({
            "source_file": source_file or "",
            "cmake_target": target or "",
            "object_file_path": str(obj_path),
            "object_size_bytes": obj_path.stat().st_size,
        })

    obj_path = cfg.raw_data_dir / "object_files.csv"
    with open(obj_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["source_file", "cmake_target", "object_file_path", "object_size_bytes"])
        writer.writeheader()
        writer.writerows(obj_records)
    logger.info("Wrote %s (%d rows)", obj_path, len(obj_records))

    # SLOC
    logger.info("Counting source lines of code...")
    all_source_paths = list(file_index.keys())
    existing_sources = [p for p in all_source_paths if os.path.exists(p)]

    # Try cloc first, fall back to Python counter
    cloc_results = try_cloc(existing_sources)
    use_cloc = cloc_results is not None
    if use_cloc:
        logger.info("Using cloc for SLOC counts")
    else:
        logger.info("cloc not available, using Python line counter")

    sloc_records = []
    for source_file in all_source_paths:
        target = file_index[source_file]
        is_generated = source_file in generated_files

        if use_cloc and source_file in cloc_results:
            counts = cloc_results[source_file]
            language = counts.get("language", "")
        elif os.path.exists(source_file):
            counts = count_lines_python(source_file)
            ext = Path(source_file).suffix
            language = "C++" if ext in (".cpp", ".cc", ".cxx", ".hpp", ".hxx") else "C" if ext in (".c", ".h") else ""
        else:
            counts = {"blank_lines": 0, "comment_lines": 0, "code_lines": 0}
            language = ""

        source_size = os.path.getsize(source_file) if os.path.exists(source_file) else 0

        sloc_records.append({
            "source_file": source_file,
            "cmake_target": target,
            "language": language,
            "blank_lines": counts["blank_lines"],
            "comment_lines": counts["comment_lines"],
            "code_lines": counts["code_lines"],
            "is_generated": is_generated,
            "source_size_bytes": source_size,
        })

    sloc_path = cfg.raw_data_dir / "sloc.csv"
    with open(sloc_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["source_file", "cmake_target", "language", "blank_lines",
                          "comment_lines", "code_lines", "is_generated", "source_size_bytes"]
        )
        writer.writeheader()
        writer.writerows(sloc_records)
    logger.info("Wrote %s (%d rows)", sloc_path, len(sloc_records))

    logger.info("Step 4 complete.")


if __name__ == "__main__":
    main()
