"""Feature group discovery: thin dependency detection.

Provides functions to detect thin dependencies where a target uses only
a small fraction of a depended-on target's public headers.
"""

from __future__ import annotations

import json

import networkx as nx
import pandas as pd


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
            rows.append(
                {
                    "depending_target": src,
                    "depended_target": dst,
                    "used_headers": used,
                    "total_headers": total,
                    "thinness_ratio": ratio,
                }
            )

    columns = ["depending_target", "depended_target", "used_headers", "total_headers", "thinness_ratio"]
    return pd.DataFrame(rows, columns=columns)
