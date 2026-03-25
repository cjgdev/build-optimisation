#!/usr/bin/env python3
"""Inventory all code generation steps by parsing build.ninja."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from build_optimiser.codegen import (
    classify_command,
    map_outputs_to_targets,
    parse_build_ninja,
    parse_ninja_log_for_commands,
)
from build_optimiser.config import load_config


def main() -> None:
    cfg = load_config()
    build_dir = Path(cfg["build_dir"])
    raw_dir = Path(cfg["raw_data_dir"])
    raw_dir.mkdir(parents=True, exist_ok=True)

    codegen_patterns = cfg.get("codegen_patterns")

    # Step 1 — Parse build.ninja
    print(f"Parsing {build_dir / 'build.ninja'} ...")
    edges = parse_build_ninja(str(build_dir))
    print(f"  Found {len(edges)} build edges")

    # Filter to CUSTOM_COMMAND edges only
    custom_edges = [e for e in edges if e["rule"] == "CUSTOM_COMMAND"]
    print(f"  Of which {len(custom_edges)} are CUSTOM_COMMAND")

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
            "cmake_target": "",  # filled in step 3
            "gen_time_ms": "",   # filled in step 4
            "description": description,
        }

        if generator == "non_codegen":
            non_codegen_rows.append(row)
        else:
            codegen_rows.append(row)

    print(f"  Classified: {len(codegen_rows)} codegen, {len(non_codegen_rows)} non-codegen")

    # Step 3 — Map generated outputs to owning CMake targets
    output_to_target = map_outputs_to_targets(edges)
    for row in codegen_rows:
        out_files = row["output_files"].split(";") if row["output_files"] else []
        targets = set()
        for out in out_files:
            t = output_to_target.get(out)
            if t:
                targets.add(t)
        row["cmake_target"] = ",".join(sorted(targets)) if targets else ""

    # Step 4 — Capture generator execution times from .ninja_log (if available)
    ninja_log_path = build_dir / ".ninja_log"
    all_generated_outputs: set[str] = set()
    for row in codegen_rows:
        if row["output_files"]:
            all_generated_outputs.update(row["output_files"].split(";"))

    timings = parse_ninja_log_for_commands(str(ninja_log_path), all_generated_outputs)

    for row in codegen_rows:
        out_files = row["output_files"].split(";") if row["output_files"] else []
        # Use the timing of the first output that has a log entry
        gen_time = None
        for out in out_files:
            if out in timings:
                gen_time = timings[out]
                break
        row["gen_time_ms"] = gen_time if gen_time is not None else ""

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
        from collections import Counter
        gen_counts = Counter(r["generator"] for r in codegen_rows)
        print("\nGenerator summary:")
        for gen, count in gen_counts.most_common():
            print(f"  {gen}: {count} invocations")


if __name__ == "__main__":
    main()
