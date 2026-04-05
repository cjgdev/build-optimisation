#!/usr/bin/env python3
"""Step 1: Configure the build tree via CMake File API and extract the project model.

Creates query files, runs cmake configure, and parses the codemodel-v2 reply
into structured JSON outputs.

Outputs to data/raw/cmake_file_api/:
    - targets.json
    - files.json
    - dependencies.json
    - compile_commands_enriched.json
    - codegen_inventory.json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from buildanalysis.cmake_file_api import (
    build_codegen_inventory,
    create_query_files,
    parse_reply,
    reconstruct_compile_command,
)
from buildanalysis.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def configure(cfg: Config, *, force: bool = False) -> None:
    """Create query files, render toolchain, and run cmake configure."""
    reply_dir = cfg.build_dir / ".cmake" / "api" / "v1" / "reply"
    if not force and reply_dir.is_dir() and list(reply_dir.glob("index-*.json")):
        logger.info("File API reply already exists, skipping configure (use --force to reconfigure)")
        return

    logger.info("Creating File API query files...")
    create_query_files(cfg.build_dir, cfg.cmake_file_api_client)

    logger.info("Rendering toolchain...")
    toolchain_path = cfg.build_dir / "toolchain.cmake"
    cfg.render_toolchain(toolchain_path)

    # Build the cmake command with instrumentation flags
    capture_script = Path(__file__).resolve().parent / "wrappers" / "capture_stderr.sh"
    cmd = cfg.cmake_configure_command(
        extra_cache_vars={
            "CMAKE_CXX_FLAGS": "-ftime-report -H",
        },
        toolchain_path=toolchain_path,
        capture_stderr_script=capture_script if capture_script.exists() else None,
    )

    logger.info("Running cmake configure...")
    logger.info("  %s", " ".join(cmd))
    start = time.monotonic()
    result = subprocess.run(cmd, check=False)
    elapsed = time.monotonic() - start
    logger.info("Configure completed in %.1fs (exit code %d)", elapsed, result.returncode)

    if result.returncode != 0:
        raise RuntimeError(f"cmake configure failed with exit code {result.returncode}")


def extract_and_write(cfg: Config) -> None:
    """Parse the File API reply and write JSON outputs."""
    logger.info("Parsing File API reply...")
    codemodel = parse_reply(cfg.build_dir, cfg.source_dir)
    logger.info(
        "Found %d targets, codemodel %d.%d (CMake %s)",
        len(codemodel.targets),
        *codemodel.codemodel_version,
        codemodel.cmake_version,
    )

    output_dir = cfg.raw_data_dir / "cmake_file_api"
    output_dir.mkdir(parents=True, exist_ok=True)

    # targets.json
    targets_data = []
    for target in codemodel.targets.values():
        td = dataclasses.asdict(target)
        targets_data.append(td)
    _write_json(output_dir / "targets.json", targets_data)
    logger.info("  wrote targets.json (%d targets)", len(targets_data))

    # files.json
    files_data = []
    for target in codemodel.targets.values():
        for src in target.sources:
            files_data.append(dataclasses.asdict(src))
    _write_json(output_dir / "files.json", files_data)
    logger.info("  wrote files.json (%d files)", len(files_data))

    # dependencies.json
    deps_data = [dataclasses.asdict(e) for e in codemodel.edges]
    _write_json(output_dir / "dependencies.json", deps_data)
    logger.info("  wrote dependencies.json (%d edges)", len(deps_data))

    # compile_commands_enriched.json
    enriched = []
    for target in codemodel.targets.values():
        compiler = cfg.cxx if any(cg.language == "CXX" for cg in target.compile_groups) else cfg.cc
        for src in target.sources:
            cmd = reconstruct_compile_command(src, target, compiler)
            if cmd:
                enriched.append(
                    {
                        "directory": target.build_dir,
                        "command": cmd,
                        "file": src.path,
                        "cmake_target": src.cmake_target,
                        "is_generated": src.is_generated,
                    }
                )
    _write_json(output_dir / "compile_commands_enriched.json", enriched)
    logger.info("  wrote compile_commands_enriched.json (%d entries)", len(enriched))

    # codegen_inventory.json
    inventory = build_codegen_inventory(codemodel)
    _write_json(output_dir / "codegen_inventory.json", inventory)
    logger.info("  wrote codegen_inventory.json (%d targets with codegen)", len(inventory))


def _write_json(path: Path, data: object) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def main() -> None:
    parser = argparse.ArgumentParser(description="Step 1: CMake File API configure + extract")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--force", action="store_true", help="Force reconfigure even if reply exists")
    args = parser.parse_args()

    cfg = Config.from_yaml(args.config)
    configure(cfg, force=args.force)
    extract_and_write(cfg)
    logger.info("Step 1 complete.")


if __name__ == "__main__":
    main()
