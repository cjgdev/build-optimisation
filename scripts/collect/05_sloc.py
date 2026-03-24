#!/usr/bin/env python3
"""Count source lines of code per file, grouped by target."""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from build_optimiser.config import load_config
from build_optimiser.metrics import parse_cmake_target_from_object_path


def count_sloc_python(filepath: str) -> dict[str, int]:
    """Lightweight SLOC counter for C/C++ files."""
    blank = 0
    comment = 0
    code = 0
    in_block_comment = False

    try:
        with open(filepath, errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    blank += 1
                    continue

                if in_block_comment:
                    comment += 1
                    if "*/" in stripped:
                        in_block_comment = False
                    continue

                if stripped.startswith("/*"):
                    comment += 1
                    if "*/" not in stripped[2:]:
                        in_block_comment = True
                    continue

                if stripped.startswith("//"):
                    comment += 1
                    continue

                code += 1
    except OSError:
        pass

    return {"blank_lines": blank, "comment_lines": comment, "code_lines": code}


def main() -> None:
    cfg = load_config()
    build_dir = Path(cfg["build_dir"])
    raw_dir = Path(cfg["raw_data_dir"])
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Parse compile_commands.json
    cc_path = build_dir / "compile_commands.json"
    if not cc_path.exists():
        print(f"Error: {cc_path} not found. Run step 02 first.", file=sys.stderr)
        sys.exit(1)

    with open(cc_path) as f:
        compile_commands = json.load(f)

    # Try to use cloc if available
    use_cloc = shutil.which("cloc") is not None

    output_path = raw_dir / "sloc.csv"
    count = 0

    with open(output_path, "w", newline="") as out_f:
        writer = csv.DictWriter(
            out_f,
            fieldnames=["source_file", "cmake_target", "language", "blank_lines", "comment_lines", "code_lines"],
        )
        writer.writeheader()

        if use_cloc:
            # Collect all source files
            files = [entry["file"] for entry in compile_commands]
            file_list_path = raw_dir / "sloc_file_list.txt"
            with open(file_list_path, "w") as fl:
                fl.write("\n".join(files))

            result = subprocess.run(
                ["cloc", "--by-file", "--json", f"--list-file={file_list_path}"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                cloc_data = json.loads(result.stdout)
                # Build target mapping
                target_map = {}
                for entry in compile_commands:
                    command = entry.get("command", "")
                    output_match = re.search(r"-o\s+(\S+)", command)
                    if output_match:
                        target = parse_cmake_target_from_object_path(output_match.group(1))
                        if target:
                            target_map[entry["file"]] = target

                for filepath, data in cloc_data.items():
                    if filepath in ("header", "SUM"):
                        continue
                    if isinstance(data, dict) and "code" in data:
                        writer.writerow({
                            "source_file": filepath,
                            "cmake_target": target_map.get(filepath, ""),
                            "language": data.get("language", ""),
                            "blank_lines": data.get("blank", 0),
                            "comment_lines": data.get("comment", 0),
                            "code_lines": data.get("code", 0),
                        })
                        count += 1
                print(f"Used cloc. Wrote {count} entries to {output_path}")
                return

        # Fallback: Python-based counting
        for entry in compile_commands:
            source_file = entry["file"]
            command = entry.get("command", "")
            output_match = re.search(r"-o\s+(\S+)", command)
            cmake_target = ""
            if output_match:
                cmake_target = parse_cmake_target_from_object_path(output_match.group(1)) or ""

            ext = Path(source_file).suffix.lower()
            language = "C++" if ext in (".cpp", ".cc", ".cxx", ".hpp", ".hxx") else "C"

            sloc = count_sloc_python(source_file)
            writer.writerow({
                "source_file": source_file,
                "cmake_target": cmake_target,
                "language": language,
                **sloc,
            })
            count += 1

    print(f"Wrote {count} entries to {output_path}")


if __name__ == "__main__":
    main()
