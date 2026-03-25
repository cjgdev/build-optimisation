"""File-to-target mapping, path canonicalisation, and aggregation functions."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


def parse_cmake_target_from_object_path(object_path: str) -> str | None:
    """Extract CMake target name from a build-tree object file path.

    Object files live under <build_dir>/CMakeFiles/<target>.dir/...
    Returns the target name, or None if the path doesn't match.
    """
    match = re.search(r"CMakeFiles/([^/]+)\.dir/", object_path)
    if match:
        return match.group(1)
    return None


def canonicalise_path(path: str, source_dir: str) -> str:
    """Convert a path to a canonical absolute form.

    If the path is relative, it is resolved against source_dir.
    """
    p = Path(path)
    if not p.is_absolute():
        p = Path(source_dir) / p
    return str(p.resolve())


def align_git_paths(
    git_df: pd.DataFrame,
    source_dir: str,
    path_column: str = "source_file",
) -> pd.DataFrame:
    """Convert relative git paths to absolute paths matching compile_commands.

    Args:
        git_df: DataFrame with a path column containing repo-relative paths.
        source_dir: Absolute path to the git repo root.
        path_column: Name of the column containing file paths.

    Returns:
        DataFrame with paths converted to absolute canonical form.
    """
    df = git_df.copy()
    df[path_column] = df[path_column].apply(
        lambda p: canonicalise_path(p, source_dir)
    )
    return df


def map_files_to_targets(
    build_dir: str,
) -> dict[str, str]:
    """Walk the build tree and map object file source paths to CMake targets.

    Returns a dict mapping source file absolute path -> cmake target name.
    """
    cmake_files_dir = Path(build_dir) / "CMakeFiles"
    mapping: dict[str, str] = {}

    if not cmake_files_dir.exists():
        return mapping

    for target_dir in cmake_files_dir.iterdir():
        if not target_dir.is_dir() or not target_dir.name.endswith(".dir"):
            continue
        target_name = target_dir.name[: -len(".dir")]
        # Find depend.make or depend.internal for source->object mapping
        depend_file = target_dir / "depend.make"
        if not depend_file.exists():
            depend_file = target_dir / "depend.internal"
        if depend_file.exists():
            _parse_depend_file(depend_file, target_name, mapping)
        else:
            # Fallback: walk for .o files and infer source from path structure
            for obj in target_dir.rglob("*.o"):
                rel = obj.relative_to(target_dir)
                # The .o path mirrors the source tree structure
                source_stem = str(rel.with_suffix(""))
                mapping[source_stem] = target_name

    return mapping


def _parse_depend_file(
    depend_file: Path, target_name: str, mapping: dict[str, str]
) -> None:
    """Parse a CMake depend.make file to extract source file paths."""
    with open(depend_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Lines look like: CMakeFiles/target.dir/path/to/file.cpp.o: /abs/path/to/file.cpp
            if ":" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    deps = parts[1].strip().split()
                    for dep in deps:
                        dep = dep.strip()
                        if dep and (
                            dep.endswith(".cpp")
                            or dep.endswith(".cc")
                            or dep.endswith(".cxx")
                            or dep.endswith(".c")
                        ):
                            mapping[str(Path(dep).resolve())] = target_name


def map_compile_commands_to_targets(
    compile_commands_path: str,
) -> dict[str, str]:
    """Parse compile_commands.json and map source files to targets.

    Uses the output file path in the command to determine the target
    via the CMakeFiles/<target>.dir/ pattern.
    """
    import json

    with open(compile_commands_path) as f:
        entries = json.load(f)

    mapping: dict[str, str] = {}
    for entry in entries:
        source_file = entry.get("file", "")
        command = entry.get("command", "")
        # Try to find target from -o flag in command
        output_match = re.search(r"-o\s+(\S+)", command)
        if output_match:
            output_path = output_match.group(1)
            target = parse_cmake_target_from_object_path(output_path)
            if target:
                mapping[str(Path(source_file).resolve())] = target
    return mapping


def aggregate_file_to_target(
    file_df: pd.DataFrame,
    target_column: str = "cmake_target",
) -> pd.DataFrame:
    """Aggregate file-level metrics to target-level metrics.

    Args:
        file_df: DataFrame with file-level metrics and a target column.
        target_column: Name of the column identifying the CMake target.

    Returns:
        DataFrame with one row per target containing aggregated metrics.
    """
    agg_spec: dict[str, list[str | tuple]] = {}
    numeric_cols = file_df.select_dtypes(include="number").columns
    numeric_cols = [c for c in numeric_cols if c != target_column]

    aggs = []
    for col in numeric_cols:
        if "time" in col or "bytes" in col or "size" in col or "lines" in col or "count" in col:
            aggs.append((f"{col}_sum", col, "sum"))
            aggs.append((f"{col}_max", col, "max"))
            aggs.append((f"{col}_mean", col, "mean"))
        elif "depth" in col:
            aggs.append((f"{col}_mean", col, "mean"))
            aggs.append((f"{col}_max", col, "max"))
        else:
            aggs.append((f"{col}_sum", col, "sum"))

    # Build aggregation
    result = file_df.groupby(target_column).agg(
        file_count=(target_column, "size"),
        **{
            name: pd.NamedAgg(column=source_col, aggfunc=func)
            for name, source_col, func in aggs
        },
    )
    return result.reset_index()


def merge_codegen_into_file_metrics(
    file_df: pd.DataFrame,
    codegen_df: pd.DataFrame,
    source_dir: str = "",
) -> pd.DataFrame:
    """Join codegen inventory data onto the file-level DataFrame.

    Explodes semicolon-separated ``output_files`` from the codegen inventory
    into individual rows, canonicalises paths, and left-joins onto *file_df*
    by ``source_file``.

    Adds columns: ``is_generated``, ``generator``, ``generator_input``,
    ``gen_time_ms``.
    """
    if codegen_df.empty:
        file_df = file_df.copy()
        file_df["is_generated"] = False
        file_df["generator"] = None
        file_df["generator_input"] = None
        file_df["gen_time_ms"] = None
        return file_df

    # Explode output_files into one row per generated file
    cg = codegen_df.copy()
    cg["output_file"] = cg["output_files"].str.split(";")
    cg = cg.explode("output_file")
    cg = cg[cg["output_file"].str.strip().astype(bool)].copy()

    # Derive primary input from input_files (first entry)
    cg["generator_input"] = cg["input_files"].str.split(";").str[0]

    # Canonicalise paths
    if source_dir:
        cg["output_file"] = cg["output_file"].apply(
            lambda p: canonicalise_path(p, source_dir)
        )

    # Build lookup: output_file -> (generator, generator_input, gen_time_ms)
    lookup = cg[["output_file", "generator", "generator_input", "gen_time_ms"]].copy()
    lookup = lookup.drop_duplicates(subset=["output_file"], keep="first")
    lookup = lookup.rename(columns={"output_file": "source_file"})

    # Left-join
    result = file_df.merge(lookup, on="source_file", how="left", suffixes=("", "_cg"))
    result["is_generated"] = result["generator"].notna()
    return result


def aggregate_codegen_to_target(
    file_df: pd.DataFrame,
    target_column: str = "cmake_target",
) -> pd.DataFrame:
    """Compute codegen-specific aggregates per target.

    Requires columns ``is_generated``, ``generator``, ``compile_time_ms``,
    and ``gen_time_ms`` in *file_df*.

    Returns a DataFrame with one row per target and columns:
    ``generated_file_count``, ``generated_file_fraction``,
    ``generated_compile_time_ms``, ``generated_compile_fraction``,
    ``generator_types``, ``generator_count``, ``gen_step_time_total_ms``.
    """
    if "is_generated" not in file_df.columns:
        return pd.DataFrame(columns=[target_column])

    groups = file_df.groupby(target_column)

    rows = []
    for target, group in groups:
        total_files = len(group)
        gen_mask = group["is_generated"].fillna(False)
        gen_files = gen_mask.sum()

        compile_col = "compile_time_ms" if "compile_time_ms" in group.columns else None
        total_compile = int(group[compile_col].sum()) if compile_col else 0
        gen_compile = int(group.loc[gen_mask, compile_col].sum()) if compile_col else 0

        gen_group = group[gen_mask]
        generator_types = sorted(gen_group["generator"].dropna().unique()) if not gen_group.empty else []

        gen_time_total = None
        if "gen_time_ms" in gen_group.columns and not gen_group.empty:
            valid_times = pd.to_numeric(gen_group["gen_time_ms"], errors="coerce").dropna()
            if not valid_times.empty:
                gen_time_total = int(valid_times.sum())

        rows.append({
            target_column: target,
            "generated_file_count": int(gen_files),
            "generated_file_fraction": gen_files / total_files if total_files > 0 else 0.0,
            "generated_compile_time_ms": gen_compile,
            "generated_compile_fraction": gen_compile / total_compile if total_compile > 0 else 0.0,
            "generator_types": ",".join(generator_types),
            "generator_count": len(generator_types),
            "gen_step_time_total_ms": gen_time_total,
        })

    return pd.DataFrame(rows)
