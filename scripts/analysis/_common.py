"""Shared CLI helpers for ad-hoc analysis scripts.

All ad-hoc scripts load a ``BuildDataset`` from either a snapshot directory
(``--snapshot``) or a processed-data directory (``--data-dir``). They all
support the same output options: pretty table (default), CSV, or JSON.

They also share a standard scope vocabulary for narrowing analysis to a
subset of the codebase:

* Tier 1 — identity: ``--target`` / ``--target-glob`` / ``--target-type``
  (with exclusion variants).
* Tier 2 — structural: ``--source-dir`` / ``--module`` / ``--module-category``
  / ``--team`` (teams/modules auto-discover their YAML configs from the
  project root; override with ``--teams-config`` / ``--modules-config``).
* Tier 3 — relationship: ``--build-set TARGET`` (target + transitive deps)
  or ``--impact-set TARGET`` (target + transitive dependants).
* Tier 4 — thresholds: ``--min-target-build-time-ms``,
  ``--min-target-compile-time-ms``, ``--min-target-code-lines``,
  ``--min-target-commits``, ``--min-target-dependants``.
* Tier 5 — file-level (opt-in via ``add_file_filter_args``):
  ``--exclude-generated``, ``--language``, ``--file-path-glob`` (with
  exclusion variant).

All target-level flags accept repeated use AND comma-separated values so
``--target a,b --target c`` is equivalent to ``--target a --target b --target c``.
Flags compose as intersection — more flags ⇒ tighter scope. Excludes apply
last. An empty scope is a hard error.

Pass ``--verbose`` to echo the resolved scope to **stderr** (so the primary
output channel stays clean for piping).
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import networkx as nx
import pandas as pd

from buildanalysis.loading import BuildDataset
from buildanalysis.types import AnalysisScope

# ---------------------------------------------------------------------------
# Dataset / output helpers (unchanged vocabulary)
# ---------------------------------------------------------------------------


def add_dataset_args(parser: argparse.ArgumentParser) -> None:
    """Register ``--data-dir`` / ``--snapshot`` / ``--intermediate-dir``."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/processed"),
        help="Directory containing the processed parquet files (default: data/processed).",
    )
    group.add_argument(
        "--snapshot",
        type=Path,
        default=None,
        help="Snapshot directory containing processed/ (overrides --data-dir).",
    )
    parser.add_argument(
        "--intermediate-dir",
        type=Path,
        default=None,
        help="Directory for notebook-produced intermediate parquet files. Defaults to <data-dir>/intermediate.",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip Pandera schema validation when loading (faster, less safe).",
    )


def add_output_args(parser: argparse.ArgumentParser, default_limit: int = 20) -> None:
    """Register output options: ``--format``, ``--limit``, ``--output``."""
    parser.add_argument(
        "--format",
        choices=["table", "csv", "json"],
        default="table",
        help="Output format (default: table).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=default_limit,
        help=f"Maximum rows to show (default: {default_limit}; 0 = unlimited).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write output to (default: stdout).",
    )


def load_dataset(args: argparse.Namespace) -> BuildDataset:
    """Instantiate a ``BuildDataset`` from parsed CLI arguments."""
    validate = not getattr(args, "no_validate", False)
    if getattr(args, "snapshot", None) is not None:
        return BuildDataset.from_snapshot(
            args.snapshot,
            intermediate_dir=args.intermediate_dir,
            validate=validate,
        )
    return BuildDataset(
        data_dir=args.data_dir,
        intermediate_dir=args.intermediate_dir,
        validate=validate,
    )


def apply_limit(df: pd.DataFrame, limit: int) -> pd.DataFrame:
    """Return ``df`` truncated to ``limit`` rows (``0`` means no limit)."""
    if limit and limit > 0:
        return df.head(limit)
    return df


def emit(df: pd.DataFrame, args: argparse.Namespace, title: str | None = None) -> None:
    """Render ``df`` in the format requested by ``args`` to stdout or a file."""
    df = apply_limit(df, getattr(args, "limit", 0))

    fmt = getattr(args, "format", "table")
    if fmt == "csv":
        text = df.to_csv(index=False)
    elif fmt == "json":
        text = df.to_json(orient="records", date_format="iso", indent=2)
    else:
        lines: list[str] = []
        if title:
            lines.append(title)
            lines.append("=" * len(title))
        if df.empty:
            lines.append("(no rows)")
        else:
            with pd.option_context("display.max_rows", None, "display.width", 200, "display.max_colwidth", 80):
                lines.append(df.to_string(index=False))
        text = "\n".join(lines) + "\n"

    out = getattr(args, "output", None)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    else:
        sys.stdout.write(text)


def emit_kv(pairs: list[tuple[str, object]], args: argparse.Namespace, title: str | None = None) -> None:
    """Render an ordered list of key/value pairs (for summaries)."""
    fmt = getattr(args, "format", "table")
    if fmt == "json":
        text = json.dumps(dict(pairs), indent=2, default=str) + "\n"
    elif fmt == "csv":
        text = "key,value\n" + "\n".join(f"{k},{v}" for k, v in pairs) + "\n"
    else:
        width = max((len(str(k)) for k, _ in pairs), default=0)
        lines: list[str] = []
        if title:
            lines.append(title)
            lines.append("=" * len(title))
        for k, v in pairs:
            lines.append(f"{str(k).ljust(width)}  {v}")
        text = "\n".join(lines) + "\n"

    out = getattr(args, "output", None)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    else:
        sys.stdout.write(text)


def minmax_normalise(series: pd.Series) -> pd.Series:
    """Min-max normalise a numeric series to ``[0, 1]``.

    Constant series (including all-zero) produce zeros. Null values are
    treated as zero.
    """
    s = series.astype(float).fillna(0.0)
    lo, hi = s.min(), s.max()
    if hi <= lo:
        return pd.Series(0.0, index=s.index)
    return (s - lo) / (hi - lo)


# ---------------------------------------------------------------------------
# Scope vocabulary
# ---------------------------------------------------------------------------


_TARGET_TYPES = (
    "executable",
    "static_library",
    "shared_library",
    "module_library",
    "object_library",
    "interface_library",
    "custom_target",
)


def _split_multi(values: list[str] | None) -> list[str]:
    """Flatten ``--flag a,b --flag c`` into ``['a', 'b', 'c']``.

    Empty strings and whitespace-only fragments are dropped. Order is
    preserved and duplicates are removed while keeping first occurrence.
    """
    if not values:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for entry in values:
        for part in str(entry).split(","):
            token = part.strip()
            if token and token not in seen:
                out.append(token)
                seen.add(token)
    return out


def add_scope_args(parser: argparse.ArgumentParser) -> None:
    """Register the standard scope vocabulary (tiers 1-4) on ``parser``.

    Use ``add_file_filter_args`` additionally for scripts that operate on
    ``file_metrics`` and benefit from file-level filters.
    """
    g = parser.add_argument_group(
        "scope",
        "Narrow analysis to a subset of targets. All flags compose (intersection); "
        "excludes apply last. Repeat flags or use comma-separated values.",
    )

    # Tier 1 — identity
    g.add_argument(
        "--target",
        "-t",
        action="append",
        default=None,
        help="Restrict to named target(s). Repeatable or comma-separated.",
    )
    g.add_argument(
        "--target-glob",
        action="append",
        default=None,
        help="Restrict to targets matching a glob pattern (fnmatch). Repeatable.",
    )
    g.add_argument(
        "--target-type",
        action="append",
        default=None,
        choices=list(_TARGET_TYPES),
        help="Restrict to CMake target type(s). Repeatable.",
    )
    g.add_argument(
        "--exclude-target",
        action="append",
        default=None,
        help="Exclude named target(s). Repeatable or comma-separated.",
    )
    g.add_argument(
        "--exclude-target-glob",
        action="append",
        default=None,
        help="Exclude targets matching a glob pattern. Repeatable.",
    )

    # Tier 2 — structural
    g.add_argument(
        "--source-dir",
        action="append",
        default=None,
        help="Restrict to targets whose source_directory begins with this prefix. Repeatable.",
    )
    g.add_argument(
        "--exclude-source-dir",
        action="append",
        default=None,
        help="Exclude targets whose source_directory begins with this prefix. Repeatable.",
    )
    g.add_argument(
        "--module",
        action="append",
        default=None,
        help="Restrict to named module(s) from modules.yaml. Repeatable.",
    )
    g.add_argument(
        "--module-category",
        action="append",
        default=None,
        help="Restrict to module category (shared|domain|infrastructure|test). Repeatable.",
    )
    g.add_argument(
        "--team",
        action="append",
        default=None,
        help="Restrict to targets owned by named team(s) from teams.yaml. Repeatable.",
    )
    g.add_argument(
        "--teams-config",
        type=Path,
        default=None,
        help="Override teams.yaml path (default: auto-discover in project root).",
    )
    g.add_argument(
        "--modules-config",
        type=Path,
        default=None,
        help="Override modules.yaml path (default: auto-discover in project root).",
    )

    # Tier 3 — relationship
    g.add_argument(
        "--build-set",
        action="append",
        default=None,
        help="Include this target plus everything it transitively depends on. Repeatable.",
    )
    g.add_argument(
        "--impact-set",
        action="append",
        default=None,
        help="Include this target plus everything that transitively depends on it. Repeatable.",
    )

    # Tier 4 — thresholds
    g.add_argument(
        "--min-target-build-time-ms",
        type=int,
        default=0,
        help="Only include targets with total_build_time_ms >= this.",
    )
    g.add_argument(
        "--min-target-compile-time-ms",
        type=int,
        default=0,
        help="Only include targets with compile_time_sum_ms >= this.",
    )
    g.add_argument(
        "--min-target-code-lines",
        type=int,
        default=0,
        help="Only include targets with code_lines_total >= this.",
    )
    g.add_argument(
        "--min-target-commits",
        type=int,
        default=0,
        help="Only include targets with git_commit_count_total >= this.",
    )
    g.add_argument(
        "--min-target-dependants",
        type=int,
        default=0,
        help="Only include targets with transitive_dependant_count >= this.",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print the resolved scope to stderr before running the analysis.",
    )


def add_file_filter_args(parser: argparse.ArgumentParser) -> None:
    """Register tier-5 file-level filters (for scripts that operate on files)."""
    g = parser.add_argument_group(
        "file filters",
        "File-level filters applied after target scope (for file/header-centric scripts).",
    )
    g.add_argument(
        "--exclude-generated",
        action="store_true",
        help="Exclude generated files (is_generated == True).",
    )
    g.add_argument(
        "--language",
        action="append",
        default=None,
        help="Restrict to file language(s), e.g. CXX, C. Repeatable.",
    )
    g.add_argument(
        "--file-path-glob",
        action="append",
        default=None,
        help="Restrict to source_file paths matching a glob (fnmatch). Repeatable.",
    )
    g.add_argument(
        "--exclude-file-path-glob",
        action="append",
        default=None,
        help="Exclude source_file paths matching a glob. Repeatable.",
    )


@dataclass
class ResolvedScope:
    """Result of resolving CLI scope flags against a dataset."""

    scope: AnalysisScope
    label_parts: list[str] = field(default_factory=list)

    @property
    def is_global(self) -> bool:
        return self.scope.is_global()


def _any_scope_flag(args: argparse.Namespace) -> bool:
    """True if the user passed any scope-narrowing flag."""
    list_flags = (
        "target",
        "target_glob",
        "target_type",
        "exclude_target",
        "exclude_target_glob",
        "source_dir",
        "exclude_source_dir",
        "module",
        "module_category",
        "team",
        "build_set",
        "impact_set",
    )
    for name in list_flags:
        if getattr(args, name, None):
            return True
    threshold_flags = (
        "min_target_build_time_ms",
        "min_target_compile_time_ms",
        "min_target_code_lines",
        "min_target_commits",
        "min_target_dependants",
    )
    for name in threshold_flags:
        if getattr(args, name, 0):
            return True
    return False


def _load_team_config(args: argparse.Namespace, dataset: BuildDataset):
    """Load a TeamConfig from explicit override or dataset auto-discovery."""
    override = getattr(args, "teams_config", None)
    if override is not None:
        from buildanalysis.teams import TeamConfig

        return TeamConfig.from_yaml(override)
    return dataset.team_config


def _load_module_config(args: argparse.Namespace, dataset: BuildDataset):
    """Load a ModuleConfig from explicit override or dataset auto-discovery."""
    override = getattr(args, "modules_config", None)
    if override is not None:
        from buildanalysis.modules import ModuleConfig

        return ModuleConfig.from_yaml(override)
    return dataset.module_config


def _glob_match(patterns: Iterable[str], names: Iterable[str]) -> set[str]:
    names_list = list(names)
    out: set[str] = set()
    for pat in patterns:
        out.update(n for n in names_list if fnmatch.fnmatch(n, pat))
    return out


def resolve_scope(args: argparse.Namespace, dataset: BuildDataset) -> AnalysisScope:
    """Resolve the scope CLI flags on ``args`` against ``dataset``.

    Returns an ``AnalysisScope`` with a frozen set of target names, or a
    global scope (``targets=None``) when no flags were supplied. Raises
    ``SystemExit`` on an empty or invalid scope, with a descriptive message.
    """
    if not _any_scope_flag(args):
        return AnalysisScope(targets=None, label="global")

    tm = dataset.target_metrics
    all_targets = set(tm["cmake_target"])
    candidates = set(all_targets)
    label_parts: list[str] = []

    # Tier 3 — relationship (widens first, then other filters intersect)
    build_set = _split_multi(getattr(args, "build_set", None))
    impact_set = _split_multi(getattr(args, "impact_set", None))
    if build_set or impact_set:
        from buildanalysis.graph import build_dependency_graph

        bg = build_dependency_graph(tm, dataset.edge_list)
        graph = bg.graph
        rel: set[str] = set()
        for t in build_set:
            if t not in graph:
                raise SystemExit(f"--build-set target '{t}' is not in the dependency graph.")
            rel.add(t)
            rel |= nx.descendants(graph, t)  # A->B means A depends on B
        for t in impact_set:
            if t not in graph:
                raise SystemExit(f"--impact-set target '{t}' is not in the dependency graph.")
            rel.add(t)
            rel |= nx.ancestors(graph, t)
        candidates &= rel
        if build_set:
            label_parts.append("build-set=" + ",".join(build_set))
        if impact_set:
            label_parts.append("impact-set=" + ",".join(impact_set))

    # Tier 1 — identity. Each flag intersects with the running candidates.
    # Within a single flag (e.g. --target a,b,c) values union. Across flags
    # they compose as AND so ``--target libA --target-type executable`` means
    # "libA that is also an executable".
    id_targets = _split_multi(getattr(args, "target", None))
    id_globs = _split_multi(getattr(args, "target_glob", None))
    id_types = _split_multi(getattr(args, "target_type", None))
    if id_targets:
        unknown = set(id_targets) - all_targets
        if unknown:
            raise SystemExit(f"Unknown --target value(s): {', '.join(sorted(unknown))}")
        candidates &= set(id_targets)
        label_parts.append("target=" + ",".join(id_targets))
    if id_globs:
        candidates &= _glob_match(id_globs, all_targets)
        label_parts.append("target-glob=" + ",".join(id_globs))
    if id_types:
        tm_by_name = tm.set_index("cmake_target")
        matched = set(tm_by_name.index[tm_by_name["target_type"].isin(id_types)])
        candidates &= matched
        label_parts.append("target-type=" + ",".join(id_types))

    # Tier 2 — structural
    src_dirs = _split_multi(getattr(args, "source_dir", None))
    if src_dirs:
        if "source_directory" not in tm.columns:
            raise SystemExit("--source-dir requires a 'source_directory' column in target_metrics.")
        sd = tm.set_index("cmake_target")["source_directory"].fillna("").astype(str)
        matched = {t for t, path in sd.items() if any(path.startswith(p) for p in src_dirs)}
        candidates &= matched
        label_parts.append("source-dir=" + ",".join(src_dirs))

    mods = _split_multi(getattr(args, "module", None))
    cats = _split_multi(getattr(args, "module_category", None))
    if mods or cats:
        mc = _load_module_config(args, dataset)
        if mc is None:
            raise SystemExit(
                "--module/--module-category requires modules.yaml (auto-discover failed; "
                "pass --modules-config explicitly)."
            )
        assigned = mc.assign_all_targets(tm)[["cmake_target", "module", "module_category"]]
        if mods:
            in_mod = set(assigned.loc[assigned["module"].isin(mods), "cmake_target"])
            candidates &= in_mod
            label_parts.append("module=" + ",".join(mods))
        if cats:
            in_cat = set(assigned.loc[assigned["module_category"].isin(cats), "cmake_target"])
            candidates &= in_cat
            label_parts.append("module-category=" + ",".join(cats))

    teams = _split_multi(getattr(args, "team", None))
    if teams:
        tc = _load_team_config(args, dataset)
        if tc is None:
            raise SystemExit("--team requires teams.yaml (auto-discover failed; pass --teams-config explicitly).")
        try:
            ownership = dataset.target_ownership
        except FileNotFoundError:
            from buildanalysis.git import compute_file_to_target_map
            from buildanalysis.teams import compute_target_ownership

            file_to_target = compute_file_to_target_map(dataset.file_metrics)
            ownership = compute_target_ownership(dataset.git_commit_log, file_to_target, tc)
        owned = set(ownership.loc[ownership["owning_team"].isin(teams), "cmake_target"])
        candidates &= owned
        label_parts.append("team=" + ",".join(teams))

    # Tier 4 — thresholds
    thresholds = [
        ("min_target_build_time_ms", "total_build_time_ms", "build-time-ms"),
        ("min_target_compile_time_ms", "compile_time_sum_ms", "compile-time-ms"),
        ("min_target_code_lines", "code_lines_total", "code-lines"),
        ("min_target_commits", "git_commit_count_total", "commits"),
        ("min_target_dependants", "transitive_dependant_count", "dependants"),
    ]
    tm_indexed = tm.set_index("cmake_target")
    for attr, col, slug in thresholds:
        thr = int(getattr(args, attr, 0) or 0)
        if thr > 0:
            if col not in tm_indexed.columns:
                raise SystemExit(f"--{attr.replace('_', '-')} requires the '{col}' column in target_metrics.")
            passing = set(tm_indexed.index[tm_indexed[col].fillna(0) >= thr])
            candidates &= passing
            label_parts.append(f"min-{slug}={thr}")

    # Excludes — applied last
    excl_names = _split_multi(getattr(args, "exclude_target", None))
    excl_globs = _split_multi(getattr(args, "exclude_target_glob", None))
    excl_src_dirs = _split_multi(getattr(args, "exclude_source_dir", None))
    excluded: set[str] = set()
    if excl_names:
        excluded |= set(excl_names)
        label_parts.append("exclude-target=" + ",".join(excl_names))
    if excl_globs:
        excluded |= _glob_match(excl_globs, all_targets)
        label_parts.append("exclude-target-glob=" + ",".join(excl_globs))
    if excl_src_dirs:
        if "source_directory" in tm.columns:
            sd = tm.set_index("cmake_target")["source_directory"].fillna("").astype(str)
            excluded |= {t for t, path in sd.items() if any(path.startswith(p) for p in excl_src_dirs)}
        label_parts.append("exclude-source-dir=" + ",".join(excl_src_dirs))
    candidates -= excluded

    if not candidates:
        hints = ", ".join(label_parts) if label_parts else "(no filters parsed)"
        raise SystemExit(f"Scope resolved to zero targets [{hints}]. Relax the filters and try again.")

    label = "scope(" + "; ".join(label_parts) + ")" if label_parts else "global"
    return AnalysisScope(targets=frozenset(candidates), label=label)


def emit_scope_header(scope: AnalysisScope, args: argparse.Namespace) -> None:
    """Write a resolved-scope summary to stderr when ``--verbose`` is set."""
    if not getattr(args, "verbose", False):
        return
    sys.stderr.write(f"# scope: {scope.label}\n")
    if scope.targets is None:
        sys.stderr.write("# targets: <all>\n")
    else:
        targets = sorted(scope.targets)
        preview = ", ".join(targets[:10])
        more = f" … (+{len(targets) - 10} more)" if len(targets) > 10 else ""
        sys.stderr.write(f"# targets: {len(targets)} — {preview}{more}\n")
    sys.stderr.flush()


def apply_file_filters(fm: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    """Apply tier-5 file-level filters (from ``add_file_filter_args``) to ``fm``."""
    df = fm
    if getattr(args, "exclude_generated", False) and "is_generated" in df.columns:
        df = df[~df["is_generated"]]

    langs = _split_multi(getattr(args, "language", None))
    if langs and "language" in df.columns:
        df = df[df["language"].isin(langs)]

    includes = _split_multi(getattr(args, "file_path_glob", None))
    if includes and "source_file" in df.columns:
        mask = pd.Series(False, index=df.index)
        for pat in includes:
            mask |= df["source_file"].astype(str).apply(lambda s, p=pat: fnmatch.fnmatch(s, p))
        df = df[mask]

    excludes = _split_multi(getattr(args, "exclude_file_path_glob", None))
    if excludes and "source_file" in df.columns:
        mask = pd.Series(False, index=df.index)
        for pat in excludes:
            mask |= df["source_file"].astype(str).apply(lambda s, p=pat: fnmatch.fnmatch(s, p))
        df = df[~mask]

    return df
