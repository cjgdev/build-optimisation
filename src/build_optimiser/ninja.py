"""Ninja build system utilities: compdb, log parsing, and build metrics."""

from __future__ import annotations

import json
import re
import struct
import subprocess
from pathlib import Path

from build_optimiser.codegen import _SOURCE_EXTENSIONS


# ── MurmurHash64A ────────────────────────────────────────────────────


def murmurhash64a(data: bytes) -> int:
    """MurmurHash64A — exact reimplementation of Ninja's command hash.

    Uses seed ``0xDECAFBADDECAFBAD`` and processes bytes in little-endian
    order, matching the C++ implementation in ``src/build_log.cc``.
    """
    SEED = 0xDECAFBADDECAFBAD
    M = 0xC6A4A7935BD1E995
    R = 47
    MASK = 0xFFFFFFFFFFFFFFFF

    length = len(data)
    h = (SEED ^ ((length * M) & MASK)) & MASK

    # Process 8-byte chunks (little-endian)
    off = 0
    while off + 8 <= length:
        k = struct.unpack_from("<Q", data, off)[0]
        k = (k * M) & MASK
        k ^= k >> R
        k = (k * M) & MASK
        h = (h ^ k) & MASK
        h = (h * M) & MASK
        off += 8

    # Handle remaining bytes (C switch fallthrough)
    remaining = length - off
    if remaining >= 7:
        h = (h ^ (data[off + 6] << 48)) & MASK
    if remaining >= 6:
        h = (h ^ (data[off + 5] << 40)) & MASK
    if remaining >= 5:
        h = (h ^ (data[off + 4] << 32)) & MASK
    if remaining >= 4:
        h = (h ^ (data[off + 3] << 24)) & MASK
    if remaining >= 3:
        h = (h ^ (data[off + 2] << 16)) & MASK
    if remaining >= 2:
        h = (h ^ (data[off + 1] << 8)) & MASK
    if remaining >= 1:
        h = (h ^ data[off]) & MASK
        h = (h * M) & MASK

    h = (h ^ (h >> R)) & MASK
    h = (h * M) & MASK
    h = (h ^ (h >> R)) & MASK

    return h


# ── Path normalisation ───────────────────────────────────────────────


def _normalise_output_path(path: str) -> str:
    """Strip leading ``./`` for consistent path matching."""
    while path.startswith("./"):
        path = path[2:]
    return path


# ── .ninja_log parsing ───────────────────────────────────────────────


def parse_ninja_log(path: str) -> dict[str, dict]:
    """Parse a ``.ninja_log`` v5 file into a dict keyed by output path.

    The v5 format is five tab-separated fields per line::

        start_time \\t end_time \\t restat_mtime \\t output \\t command_hash

    Because the log is append-only, the same output may appear multiple
    times; only the **last** entry for each output is kept (matching
    Ninja's own semantics).  Running ``ninja -t recompact`` beforehand
    removes duplicates at the source.

    Returns a dict mapping *normalised* output path to a dict with keys:
    ``start_ms``, ``end_ms``, ``wall_clock_ms``, ``restat_mtime``,
    ``command_hash``, and ``output`` (original path from the log).
    """
    log = Path(path)
    if not log.exists():
        return {}

    entries: dict[str, dict] = {}

    with open(log, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 5:
                continue
            try:
                start_ms = int(parts[0])
                end_ms = int(parts[1])
                restat_mtime = int(parts[2])
            except ValueError:
                continue
            output = parts[3]
            command_hash = parts[4]
            key = _normalise_output_path(output)
            entries[key] = {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "wall_clock_ms": end_ms - start_ms,
                "restat_mtime": restat_mtime,
                "command_hash": command_hash,
                "output": output,
            }

    return entries


# ── ninja -t recompact ───────────────────────────────────────────────


def run_recompact(build_dir: str) -> None:
    """Run ``ninja -t recompact`` to deduplicate ``.ninja_log``.

    Silently does nothing if ninja is not available or the command fails.
    """
    try:
        subprocess.run(
            ["ninja", "-C", build_dir, "-t", "recompact"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


# ── ninja -t compdb ──────────────────────────────────────────────────


def run_compdb(build_dir: str, expand_rspfile: bool = False) -> list[dict]:
    """Extract the compilation database via ``ninja -t compdb``.

    Falls back to reading ``compile_commands.json`` if the ninja tool
    returns no entries (older Ninja versions require explicit rule names).

    When *expand_rspfile* is ``True``, passes ``-x`` so response-file
    content is inlined — useful for hash verification.

    Each returned entry is guaranteed to have an ``output`` key (inferred
    from the ``-o`` flag in the command when not provided natively).
    """
    entries = _run_ninja_compdb(build_dir, expand_rspfile)

    if not entries:
        cc_path = Path(build_dir) / "compile_commands.json"
        if cc_path.exists():
            with open(cc_path) as f:
                entries = json.load(f)

    # Ensure every entry has an 'output' field
    for entry in entries:
        if "output" not in entry:
            m = re.search(r"-o\s+(\S+)", entry.get("command", ""))
            if m:
                entry["output"] = m.group(1)

    return entries


def _run_ninja_compdb(build_dir: str, expand_rspfile: bool) -> list[dict]:
    """Low-level wrapper around ``ninja -t compdb``."""
    args = ["ninja", "-C", build_dir, "-t", "compdb"]
    if expand_rspfile:
        args.append("-x")

    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    if result.returncode != 0 or not result.stdout.strip():
        return []

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


# ── compdb → target mapping ──────────────────────────────────────────


def _parse_cmake_target(output_path: str) -> str | None:
    """Extract CMake target name from ``CMakeFiles/<target>.dir/`` in a path."""
    m = re.search(r"CMakeFiles/([^/]+)\.dir/", output_path)
    return m.group(1) if m else None


def map_compdb_to_targets(entries: list[dict]) -> dict[str, str]:
    """Build a *source_file → cmake_target* mapping from compdb entries.

    The target is derived from the ``CMakeFiles/<target>.dir/`` prefix in
    the object-file output path.
    """
    mapping: dict[str, str] = {}
    for entry in entries:
        source = entry.get("file", "")
        output = entry.get("output", "")
        if not source or not output:
            continue
        target = _parse_cmake_target(output)
        if target:
            mapping[_normalise_output_path(source)] = target
            mapping[source] = target
    return mapping


# ── compdb + ninja_log join ──────────────────────────────────────────


def join_compdb_with_log(
    compdb_entries: list[dict],
    log_entries: dict[str, dict],
) -> list[dict]:
    """Join compilation-database entries with ``.ninja_log`` timing data.

    The **output path** is the primary join key.  The command hash from
    the log is preserved for optional verification.

    Returns a list of dicts with keys: ``target_path``, ``source_file``,
    ``cmake_target``, ``start_ms``, ``end_ms``, ``wall_clock_ms``.
    """
    results: list[dict] = []

    for entry in compdb_entries:
        output = entry.get("output", "")
        if not output:
            continue

        key = _normalise_output_path(output)
        log_entry = log_entries.get(key)

        source_file = entry.get("file", "")
        cmake_target = _parse_cmake_target(output) or ""

        row: dict = {
            "target_path": output,
            "source_file": source_file,
            "cmake_target": cmake_target,
        }

        if log_entry:
            row["start_ms"] = log_entry["start_ms"]
            row["end_ms"] = log_entry["end_ms"]
            row["wall_clock_ms"] = log_entry["wall_clock_ms"]
        else:
            row["start_ms"] = ""
            row["end_ms"] = ""
            row["wall_clock_ms"] = ""

        results.append(row)

    return results


# ── Ninja CLI helpers (moved from codegen.py) ────────────────────────


def ninja_query_target(build_dir: str, output_path: str) -> dict | None:
    """Use ``ninja -t query`` to get inputs/outputs for a specific target.

    Returns a dict with ``rule``, ``inputs``, ``outputs`` or *None* on failure.
    """
    try:
        result = subprocess.run(
            ["ninja", "-t", "query", output_path],
            capture_output=True,
            text=True,
            cwd=build_dir,
            timeout=30,
        )
        if result.returncode != 0:
            return None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    info: dict = {"rule": "", "inputs": [], "outputs": []}
    section = None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("input:"):
            info["rule"] = stripped.split(":", 1)[1].strip()
            section = "inputs"
        elif stripped == "outputs:":
            section = "outputs"
        elif section and stripped:
            info[section].append(stripped)

    return info


def ninja_list_targets(build_dir: str) -> dict[str, str]:
    """Use ``ninja -t targets all`` to list all targets and their rule names.

    Returns a mapping of output path → rule name.
    """
    try:
        result = subprocess.run(
            ["ninja", "-t", "targets", "all"],
            capture_output=True,
            text=True,
            cwd=build_dir,
            timeout=60,
        )
        if result.returncode != 0:
            return {}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}

    targets: dict[str, str] = {}
    for line in result.stdout.splitlines():
        colon_pos = line.rfind(": ")
        if colon_pos > 0:
            targets[line[:colon_pos]] = line[colon_pos + 2:]
    return targets


def ninja_map_outputs_to_targets(
    build_dir: str, output_paths: list[str],
) -> dict[str, str]:
    """Use ``ninja -t query`` to map generated outputs to CMake targets.

    For each generated source file, queries ninja to find what consumes it,
    then extracts the CMake target name from ``CMakeFiles/<target>.dir/``.
    """
    mapping: dict[str, str] = {}
    for out_path in output_paths:
        suffix = Path(out_path).suffix.lower()
        if suffix not in _SOURCE_EXTENSIONS:
            continue
        info = ninja_query_target(build_dir, out_path)
        if not info:
            continue
        for consumer_out in info.get("outputs", []):
            target = _parse_cmake_target(consumer_out)
            if target:
                mapping[out_path] = target
                break
    return mapping
