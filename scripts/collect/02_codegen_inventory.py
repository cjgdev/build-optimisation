#!/usr/bin/env python3
"""Inventory all code generation steps using ninja compdb and log."""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from build_optimiser.codegen import classify_command, parse_build_ninja
from build_optimiser.config import load_config
from build_optimiser.ninja import (
    map_compdb_to_targets,
    ninja_map_outputs_to_targets,
    parse_ninja_log,
    run_compdb,
    run_recompact,
)


def main() -> None:
    cfg = load_config()
    build_dir = Path(cfg["build_dir"])
    raw_dir = Path(cfg["raw_data_dir"])
    raw_dir.mkdir(parents=True, exist_ok=True)

    codegen_patterns = cfg.get("codegen_patterns")

    # Step 1 — Parse build.ninja for CUSTOM_COMMAND edges
    print(f"Parsing {build_dir / 'build.ninja'} ...")
    edges = parse_build_ninja(str(build_dir))
    custom_edges = [e for e in edges if e["rule"] == "CUSTOM_COMMAND"]
    print(f"  Found {len(edges)} build edges, {len(custom_edges)} CUSTOM_COMMAND")

    # Step 2 — Classify each custom command
    codegen_rows: list[dict] = []
    non_codegen_rows: list[dict] = []

    for edge in custom_edges:
        command = edge["variables"].get("COMMAND", "")
        description = edge["variables"].get("DESC", "")
        outputs = edge["outputs"]
        inputs = edge["inputs"]

        generator = classify_command(command, outputs, codegen_patterns)

        row = {
            "generator": generator,
            "command": command,
            "input_files": ";".join(inputs),
            "output_files": ";".join(outputs),
            "cmake_target": "",
            "gen_time_ms": "",
            "description": description,
        }

        if generator == "non_codegen":
            non_codegen_rows.append(row)
        else:
            codegen_rows.append(row)

    print(f"  Classified: {len(codegen_rows)} codegen, {len(non_codegen_rows)} non-codegen")

    # Step 3 — Map generated outputs to CMake targets via compdb
    compdb_entries = run_compdb(str(build_dir))
    source_to_target = map_compdb_to_targets(compdb_entries)

    unmapped_outputs: list[str] = []
    for row in codegen_rows:
        out_files = row["output_files"].split(";") if row["output_files"] else []
        targets = set()
        for out in out_files:
            t = source_to_target.get(out)
            if t:
                targets.add(t)
        row["cmake_target"] = ",".join(sorted(targets)) if targets else ""
        if not row["cmake_target"]:
            unmapped_outputs.extend(out_files)

    # Fallback: use ninja -t query for unmapped outputs
    if unmapped_outputs:
        print(f"  Using ninja -t query to resolve {len(unmapped_outputs)} unmapped outputs...")
        ninja_mapping = ninja_map_outputs_to_targets(str(build_dir), unmapped_outputs)
        if ninja_mapping:
            for row in codegen_rows:
                if row["cmake_target"]:
                    continue
                out_files = row["output_files"].split(";") if row["output_files"] else []
                targets = set()
                for out in out_files:
                    t = ninja_mapping.get(out)
                    if t:
                        targets.add(t)
                if targets:
                    row["cmake_target"] = ",".join(sorted(targets))

    # Step 4 — Extract timing from .ninja_log (after recompact)
    run_recompact(str(build_dir))
    log_entries = parse_ninja_log(str(build_dir / ".ninja_log"))

    for row in codegen_rows:
        out_files = row["output_files"].split(";") if row["output_files"] else []
        for out in out_files:
            key = out.lstrip("./") if out.startswith("./") else out
            entry = log_entries.get(key)
            if entry:
                row["gen_time_ms"] = entry["wall_clock_ms"]
                break

    # Write primary output
    fieldnames = [
        "generator", "command", "input_files", "output_files",
        "cmake_target", "gen_time_ms", "description",
    ]

    codegen_path = raw_dir / "codegen_inventory.csv"
    with open(codegen_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(codegen_rows)
    print(f"Wrote {len(codegen_rows)} codegen entries to {codegen_path}")

    # Write secondary output (non-codegen custom commands)
    non_codegen_path = raw_dir / "codegen_non_source.csv"
    with open(non_codegen_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(non_codegen_rows)
    print(f"Wrote {len(non_codegen_rows)} non-codegen entries to {non_codegen_path}")

    # Summary
    if codegen_rows:
        gen_counts = Counter(r["generator"] for r in codegen_rows)
        print("\nGenerator summary:")
        for gen, count in gen_counts.most_common():
            print(f"  {gen}: {count} invocations")


if __name__ == "__main__":
    main()
