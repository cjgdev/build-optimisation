"""Feature group discovery: executable-library analysis, core identification, and thin dependencies.

Provides functions to build executable-library dependency matrices,
identify core libraries, compute Jaccard similarity, and detect thin dependencies.
"""

from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd


def compute_exe_library_matrix(
    G: nx.DiGraph,
    target_types: pd.DataFrame,
) -> pd.DataFrame:
    """Compute the executable-library dependency matrix.

    For each executable target, computes the full transitive dependency closure
    and records which library targets it depends on.

    Args:
        G: Dependency DAG where A -> B means A depends on B.
        target_types: DataFrame with columns (cmake_target, target_type).

    Returns:
        DataFrame in long format with columns (executable, library, is_direct).
    """
    type_map = dict(zip(target_types["cmake_target"], target_types["target_type"]))
    executables = [t for t in G.nodes() if type_map.get(t) == "executable"]
    library_types = {"static_library", "shared_library", "module_library", "object_library", "interface_library"}

    rows = []
    for exe in executables:
        # Direct dependencies
        direct_deps = set(G.successors(exe))
        # Full transitive closure
        all_deps = nx.descendants(G, exe)

        for dep in all_deps:
            if type_map.get(dep) in library_types:
                rows.append({
                    "executable": exe,
                    "library": dep,
                    "is_direct": dep in direct_deps,
                })

    return pd.DataFrame(rows, columns=["executable", "library", "is_direct"])


def identify_core_libraries(
    exe_lib_matrix: pd.DataFrame,
    threshold: float = 0.8,
) -> list[str]:
    """Identify libraries that appear in most executable dependency closures.

    Args:
        exe_lib_matrix: Long-format DataFrame with (executable, library, is_direct).
        threshold: Fraction of executables a library must appear in to be core.

    Returns:
        Sorted list of core library names.
    """
    n_executables = exe_lib_matrix["executable"].nunique()
    if n_executables == 0:
        return []

    lib_counts = exe_lib_matrix.groupby("library")["executable"].nunique()
    lib_freq = lib_counts / n_executables

    core = lib_freq[lib_freq >= threshold].index.tolist()
    return sorted(core)


def expand_core(
    G: nx.DiGraph,
    core: list[str],
    max_fraction: float = 0.4,
    cross_group_threshold: int = 3,
    feature_groups: pd.DataFrame | None = None,
) -> list[str]:
    """Expand core library set to be self-contained.

    Step 1: Add transitive dependencies of core libraries.
    Step 2: Add libraries with high cross-group dependency counts.
    Step 3: Enforce maximum core size.

    Args:
        G: Dependency DAG.
        core: Initial core library list.
        max_fraction: Maximum fraction of total targets that core can be.
        cross_group_threshold: Libraries depended on by this many non-core groups get added.
        feature_groups: Optional DataFrame with (cmake_target, feature_group) for cross-group analysis.

    Returns:
        Expanded and sorted core library list.
    """
    total_targets = len(G.nodes())
    max_core_size = int(total_targets * max_fraction)
    expanded = set(core)

    # Step 1: Add transitive dependencies of current core
    for lib in list(expanded):
        if lib in G:
            deps = nx.descendants(G, lib)
            expanded |= deps

    # Step 2: Add high-cross-group libraries if feature groups provided
    if feature_groups is not None and not feature_groups.empty:
        group_map = dict(zip(feature_groups["cmake_target"], feature_groups["feature_group"]))
        for node in G.nodes():
            if node in expanded:
                continue
            # Count how many non-core feature groups depend on this node
            dependants = nx.ancestors(G, node)  # nodes that depend on this one
            groups_needing = set()
            for dep in dependants:
                grp = group_map.get(dep)
                if grp and grp != "core":
                    groups_needing.add(grp)
            if len(groups_needing) >= cross_group_threshold:
                expanded.add(node)

    # Step 3: Enforce max size by removing lowest-impact additions
    if len(expanded) > max_core_size:
        original = set(core)
        additions = expanded - original
        # Keep original core, trim additions by dependant count (keep most-depended-on)
        addition_scores = {}
        for node in additions:
            addition_scores[node] = len(nx.ancestors(G, node))
        sorted_additions = sorted(addition_scores, key=addition_scores.get, reverse=True)
        allowed = max_core_size - len(original)
        expanded = original | set(sorted_additions[:allowed])

    return sorted(expanded)


def compute_jaccard_matrix(exe_lib_matrix: pd.DataFrame) -> pd.DataFrame:
    """Compute pairwise Jaccard similarity between executable dependency closures.

    Args:
        exe_lib_matrix: Long-format DataFrame with (executable, library, is_direct).

    Returns:
        Square DataFrame with executables as both index and columns, values are Jaccard similarity.
    """
    # Build sets of libraries per executable
    exe_libs: dict[str, set[str]] = {}
    for exe, group in exe_lib_matrix.groupby("executable"):
        exe_libs[exe] = set(group["library"])

    executables = sorted(exe_libs.keys())
    n = len(executables)
    matrix = np.zeros((n, n))

    for i in range(n):
        set_i = exe_libs[executables[i]]
        matrix[i, i] = 1.0
        for j in range(i + 1, n):
            set_j = exe_libs[executables[j]]
            union = len(set_i | set_j)
            if union == 0:
                sim = 0.0
            else:
                sim = len(set_i & set_j) / union
            matrix[i, j] = sim
            matrix[j, i] = sim

    return pd.DataFrame(matrix, index=executables, columns=executables)


def detect_thin_dependencies(
    G: nx.DiGraph,
    header_data: pd.DataFrame,
    thinness_threshold: float = 0.1,
) -> pd.DataFrame:
    """Identify thin dependencies using header inclusion data.

    A dependency is "thin" if the depending target uses only a small fraction
    of the depended-on target's public headers.

    Args:
        G: Dependency DAG.
        header_data: DataFrame with columns (source_file, cmake_target, header_tree)
                    where header_tree is a JSON string of included headers.
        thinness_threshold: Maximum used/total header ratio to consider thin.

    Returns:
        DataFrame with columns (depending_target, depended_target, used_headers,
        total_headers, thinness_ratio).
    """
    import json

    # Build per-target header sets from header_data
    target_headers: dict[str, set[str]] = {}
    target_included: dict[str, set[str]] = {}

    for _, row in header_data.iterrows():
        target = row["cmake_target"]
        if target not in target_headers:
            target_headers[target] = set()
            target_included[target] = set()

        # Collect headers that belong to this target
        target_headers[target].add(row["source_file"])

        # Parse header tree to find what this target includes
        tree_str = row.get("header_tree", "[]")
        if pd.notna(tree_str) and tree_str:
            try:
                tree = json.loads(tree_str) if isinstance(tree_str, str) else tree_str
                if isinstance(tree, list):
                    for entry in tree:
                        if isinstance(entry, list) and len(entry) >= 2:
                            target_included[target].add(entry[1])
                        elif isinstance(entry, str):
                            target_included[target].add(entry)
            except (json.JSONDecodeError, TypeError):
                pass

    rows = []
    for edge in G.edges():
        src, dst = edge  # src depends on dst
        src_includes = target_included.get(src, set())
        dst_headers = target_headers.get(dst, set())

        if not dst_headers:
            continue

        used = len(src_includes & dst_headers)
        total = len(dst_headers)
        ratio = used / total if total > 0 else 0.0

        if ratio <= thinness_threshold:
            rows.append({
                "depending_target": src,
                "depended_target": dst,
                "used_headers": used,
                "total_headers": total,
                "thinness_ratio": ratio,
            })

    columns = ["depending_target", "depended_target", "used_headers", "total_headers", "thinness_ratio"]
    return pd.DataFrame(rows, columns=columns)
