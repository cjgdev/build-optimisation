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


# ── Ninja escape / path helpers ───────────────────────────────────────


def _resolve_continuations(raw_lines: list[str]) -> list[str]:
    """Join Ninja ``$\\n`` line continuations into logical lines.

    A line ending with ``$`` (but not ``$$``) continues on the next line.
    Leading whitespace on the continuation line is stripped.
    """
    logical: list[str] = []
    buf: list[str] = []

    for raw in raw_lines:
        line = raw.rstrip("\n").rstrip("\r")
        if line.endswith("$") and not line.endswith("$$"):
            # Continuation — strip trailing '$' and accumulate
            if buf:
                # Intermediate continuation: strip leading whitespace
                buf.append(line.lstrip()[:-1])
            else:
                # First line of continuation
                buf.append(line[:-1])
        else:
            if buf:
                buf.append(line.lstrip())
                logical.append("".join(buf))
                buf = []
            else:
                logical.append(line)

    # Flush any remaining buffer
    if buf:
        logical.append("".join(buf))

    return logical


def _unescape_ninja_path(token: str) -> str:
    """Resolve Ninja path escapes: ``$$`` → ``$``, ``$ `` → `` ``, ``$:`` → ``:``."""
    result: list[str] = []
    i = 0
    while i < len(token):
        if token[i] == "$" and i + 1 < len(token):
            nxt = token[i + 1]
            if nxt == "$":
                result.append("$")
                i += 2
            elif nxt == " ":
                result.append(" ")
                i += 2
            elif nxt == ":":
                result.append(":")
                i += 2
            else:
                # ${var} or $var — leave as-is for now
                result.append(token[i])
                i += 1
        else:
            result.append(token[i])
            i += 1
    return "".join(result)


def _split_ninja_paths(s: str) -> list[str]:
    """Split a Ninja path list respecting ``$ `` (escaped space) and ``$:`` (escaped colon).

    Returns a list of raw (still-escaped) tokens split only on *unescaped* whitespace.
    """
    tokens: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "$" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == " " or nxt == ":" or nxt == "$":
                # Escaped char — part of the current token
                current.append(ch)
                current.append(nxt)
                i += 2
                continue
            elif nxt == "\n":
                # Should already be resolved, but handle gracefully
                i += 2
                continue
            else:
                current.append(ch)
                i += 1
                continue
        if ch in (" ", "\t"):
            if current:
                tokens.append("".join(current))
                current = []
            i += 1
        else:
            current.append(ch)
            i += 1
    if current:
        tokens.append("".join(current))
    return tokens


def _find_unescaped_colon(s: str) -> int:
    """Find the position of the first unescaped ``:`` in *s*.

    ``$:`` is an escaped colon and should be skipped.  Returns -1 if not found.
    """
    i = 0
    while i < len(s):
        if s[i] == "$" and i + 1 < len(s):
            # Skip escaped character
            i += 2
            continue
        if s[i] == ":":
            return i
        i += 1
    return -1


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
        raw_lines = fh.readlines()

    logical_lines = _resolve_continuations(raw_lines)

    for line in logical_lines:
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
    """Parse a single ``build …`` line into its components.

    Handles Ninja escapes (``$ ``, ``$:``, ``$$``), implicit outputs
    (``|`` before the colon), implicit deps (``|`` after the colon),
    and order-only deps (``||``).
    """
    rest = line[len("build "):]

    # Find the colon that separates outputs from rule+inputs, skipping $:
    colon_pos = _find_unescaped_colon(rest)
    if colon_pos < 0:
        paths = _split_ninja_paths(rest)
        return {
            "rule": "",
            "outputs": [_unescape_ninja_path(p) for p in paths],
            "inputs": [],
            "implicit": [],
            "order_only": [],
            "variables": {},
        }

    outputs_str = rest[:colon_pos].strip()
    rule_inputs_str = rest[colon_pos + 1:].strip()

    # Parse outputs — split on unescaped '|' for implicit outputs
    output_tokens = _split_ninja_paths(outputs_str)
    explicit_outputs: list[str] = []
    implicit_outputs: list[str] = []
    current_out = explicit_outputs
    for tok in output_tokens:
        if tok == "|":
            current_out = implicit_outputs
        else:
            current_out.append(_unescape_ninja_path(tok))

    # First token after colon is the rule name
    tokens = _split_ninja_paths(rule_inputs_str)
    rule = _unescape_ninja_path(tokens[0]) if tokens else ""
    remaining = tokens[1:] if len(tokens) > 1 else []

    # Split remaining into explicit, implicit (|), order-only (||)
    explicit: list[str] = []
    implicit: list[str] = []
    order_only: list[str] = []
    current: list[str] = explicit

    i = 0
    while i < len(remaining):
        tok = remaining[i]
        if tok == "||":
            current = order_only
        elif tok == "|":
            current = implicit
        else:
            current.append(_unescape_ninja_path(tok))
        i += 1

    return {
        "rule": rule,
        "outputs": explicit_outputs,
        "implicit_outputs": implicit_outputs,
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
        # Check both explicit and implicit outputs
        all_outputs = list(edge["outputs"])
        all_outputs.extend(edge.get("implicit_outputs", []))
        for out in all_outputs:
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


