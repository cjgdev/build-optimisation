"""Code generation inventory: parse build.ninja, classify generators, map outputs."""

from __future__ import annotations

import re
from pathlib import Path

# Extensions that indicate generated *source* code (compiled into .o)
_SOURCE_EXTENSIONS = frozenset({
    ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hxx",
})

# Built-in generator classification patterns.
# Each key is a generator name; values are regex patterns matched against
# the COMMAND string (case-insensitive).  Order matters — first match wins.
_BUILTIN_PATTERNS: list[tuple[str, list[re.Pattern]]] = [
    ("flex", [re.compile(r"(?:^|/)flex(?:\s|$)")]),
    ("bison", [re.compile(r"(?:^|/)bison(?:\s|$)")]),
    ("protoc", [re.compile(r"(?:^|/)protoc(?:\s|$)")]),
    ("xsdcxx", [re.compile(r"(?:^|/)(?:xsd|xsdcxx)(?:\s|$)")]),
    ("swagger_codegen", [re.compile(r"swagger-codegen|openapi-generator")]),
    ("gsoap", [re.compile(r"(?:^|/)(?:soapcpp2|wsdl2h)(?:\s|$)")]),
    ("MessageCompiler", [re.compile(r"MessageCompiler")]),
    ("DbAutoGen", [re.compile(r"DbAutoGen")]),
    ("TemplateCompiler", [re.compile(r"TemplateCompiler")]),
]


def _compile_user_patterns(
    codegen_patterns: dict[str, list[str]] | None,
) -> list[tuple[str, list[re.Pattern]]]:
    """Merge user-supplied patterns with built-in ones.

    User patterns for a given generator name *replace* the built-in entry
    for that name.  New names are appended.
    """
    if not codegen_patterns:
        return list(_BUILTIN_PATTERNS)

    builtin_names = {name for name, _ in _BUILTIN_PATTERNS}
    result: list[tuple[str, list[re.Pattern]]] = []

    for name, patterns in _BUILTIN_PATTERNS:
        if name in codegen_patterns:
            # User override
            result.append((
                name,
                [re.compile(p) for p in codegen_patterns[name]],
            ))
        else:
            result.append((name, patterns))

    # Append user-only entries
    for name, raw_patterns in codegen_patterns.items():
        if name not in builtin_names:
            result.append((
                name,
                [re.compile(p) for p in raw_patterns],
            ))

    return result


# ── build.ninja parser ────────────────────────────────────────────────

def parse_build_ninja(build_dir: str) -> list[dict]:
    """Parse build.ninja and extract all build edges.

    Each returned dict has keys:
        rule        — Ninja rule name (e.g. ``CUSTOM_COMMAND``, ``CXX_COMPILER__<target>``)
        outputs     — list[str] of output paths
        inputs      — list[str] of explicit input paths
        implicit    — list[str] of implicit input paths (after ``|``)
        order_only  — list[str] of order-only deps (after ``||``)
        variables   — dict[str, str] of indented variable assignments (COMMAND, DESC, …)
    """
    ninja_path = Path(build_dir) / "build.ninja"
    if not ninja_path.exists():
        raise FileNotFoundError(f"build.ninja not found in {build_dir}")

    edges: list[dict] = []
    current_edge: dict | None = None

    with open(ninja_path, encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n")

            # Indented lines are variable assignments for the current edge
            if line.startswith("  ") and current_edge is not None:
                stripped = line.strip()
                eq_pos = stripped.find("=")
                if eq_pos > 0:
                    var_name = stripped[:eq_pos].strip()
                    var_value = stripped[eq_pos + 1:].strip()
                    current_edge["variables"][var_name] = var_value
                continue

            # Non-indented line — flush previous edge
            if current_edge is not None:
                edges.append(current_edge)
                current_edge = None

            # Parse build statement
            if line.startswith("build "):
                current_edge = _parse_build_line(line)

    # Flush last edge
    if current_edge is not None:
        edges.append(current_edge)

    return edges


def _parse_build_line(line: str) -> dict:
    """Parse a single ``build …`` line into its components."""
    # Format: build output1 output2 : rule_name input1 | implicit1 || order_only1
    rest = line[len("build "):]

    # Split on colon separating outputs from rule+inputs
    colon_pos = rest.find(":")
    if colon_pos < 0:
        return {
            "rule": "",
            "outputs": rest.split(),
            "inputs": [],
            "implicit": [],
            "order_only": [],
            "variables": {},
        }

    outputs_str = rest[:colon_pos].strip()
    rule_inputs_str = rest[colon_pos + 1:].strip()

    # First token after colon is the rule name
    tokens = rule_inputs_str.split()
    rule = tokens[0] if tokens else ""
    remaining = tokens[1:] if len(tokens) > 1 else []

    # Split remaining into explicit, implicit (|), order-only (||)
    explicit: list[str] = []
    implicit: list[str] = []
    order_only: list[str] = []
    current = explicit

    for tok in remaining:
        if tok == "||":
            current = order_only
        elif tok == "|":
            current = implicit
        else:
            current.append(tok)

    return {
        "rule": rule,
        "outputs": outputs_str.split(),
        "inputs": explicit,
        "implicit": implicit,
        "order_only": order_only,
        "variables": {},
    }


# ── Command classification ────────────────────────────────────────────

def classify_command(
    command: str,
    outputs: list[str],
    codegen_patterns: dict[str, list[str]] | None = None,
) -> str:
    """Classify a custom command by matching against known generator patterns.

    Returns the generator name (e.g. ``protoc``), ``unknown_codegen`` if the
    command produces source-code outputs but doesn't match a known generator,
    or ``non_codegen`` if no source-code outputs are produced.
    """
    patterns = _compile_user_patterns(codegen_patterns)

    # Check known generators first
    for gen_name, pats in patterns:
        for pat in pats:
            if pat.search(command):
                return gen_name

    # Not a known generator — does it produce source code?
    for out in outputs:
        suffix = Path(out).suffix.lower()
        if suffix in _SOURCE_EXTENSIONS:
            return "unknown_codegen"

    return "non_codegen"


# ── Output-to-target mapping ──────────────────────────────────────────

def map_outputs_to_targets(build_ninja_edges: list[dict]) -> dict[str, str]:
    """Follow dependency chains to map generated source files to CMake targets.

    Walk the build edges: a generated ``.cpp`` appears as input to a compile
    edge producing a ``.o`` under ``CMakeFiles/<target>.dir/``.

    Returns a dict mapping output file path → CMake target name.
    """
    # Build a lookup: input_file -> list of edges that consume it
    input_to_edges: dict[str, list[dict]] = {}
    for edge in build_ninja_edges:
        for inp in edge["inputs"]:
            input_to_edges.setdefault(inp, []).append(edge)
        for imp in edge["implicit"]:
            input_to_edges.setdefault(imp, []).append(edge)

    mapping: dict[str, str] = {}

    for edge in build_ninja_edges:
        if edge["rule"] != "CUSTOM_COMMAND":
            continue
        for out in edge["outputs"]:
            suffix = Path(out).suffix.lower()
            if suffix not in _SOURCE_EXTENSIONS:
                continue
            # Find a compile edge that consumes this output
            target = _find_owning_target(out, input_to_edges)
            if target:
                mapping[out] = target

    return mapping


def _find_owning_target(
    source_path: str,
    input_to_edges: dict[str, list[dict]],
) -> str | None:
    """Find the CMake target that compiles a given source file."""
    consumers = input_to_edges.get(source_path, [])
    for consumer in consumers:
        for obj_out in consumer["outputs"]:
            match = re.search(r"CMakeFiles/([^/]+)\.dir/", obj_out)
            if match:
                return match.group(1)
    return None


# ── Ninja log timing extraction ───────────────────────────────────────

def parse_ninja_log_for_commands(
    ninja_log_path: str,
    known_outputs: set[str],
) -> dict[str, int]:
    """Extract execution times from ``.ninja_log`` for known generated outputs.

    The ``.ninja_log`` format is tab-separated:
    ``start_ms  end_ms  mtime_ms  command_hash  output_path``

    Returns a mapping of output file path → execution time in milliseconds.
    """
    log = Path(ninja_log_path)
    if not log.exists():
        return {}

    timings: dict[str, int] = {}

    with open(log, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            start_ms = int(parts[0])
            end_ms = int(parts[1])
            output_path = parts[4]
            if output_path in known_outputs:
                timings[output_path] = end_ms - start_ms

    return timings
