"""Graph construction and core algorithms for build dependency analysis."""

from __future__ import annotations

import networkx as nx
import pandas as pd

from buildanalysis.types import BuildGraph, TargetType


def build_dependency_graph(
    targets: pd.DataFrame,
    edges: pd.DataFrame,
    direct_only: bool = True,
) -> BuildGraph:
    """Construct the target dependency DAG from target_metrics and edge_list.

    Edge convention: (A, B) means "A depends on B".

    Parameters
    ----------
    targets:
        DataFrame with at least ``cmake_target`` and ``target_type`` columns.
    edges:
        DataFrame with ``source_target``, ``dest_target``, ``is_direct`` columns.
    direct_only:
        If True, use only direct edges (``is_direct == True``).
    """
    if direct_only:
        edges = edges[edges["is_direct"]].copy()

    g = nx.DiGraph()

    # Add all targets as nodes with their metadata
    for _, row in targets.iterrows():
        g.add_node(row["cmake_target"], **row.to_dict())

    # Add edges with available attributes
    edge_attrs = ["dependency_type"]
    if "cmake_visibility" in edges.columns:
        edge_attrs.append("cmake_visibility")

    for _, row in edges.iterrows():
        attrs = {k: row[k] for k in edge_attrs if k in row.index and pd.notna(row[k])}
        g.add_edge(row["source_target"], row["dest_target"], **attrs)

    if not nx.is_directed_acyclic_graph(g):
        cycles = list(nx.simple_cycles(g))
        raise ValueError(f"Graph contains cycles: {cycles}")

    meta = targets.set_index("cmake_target") if targets.index.name != "cmake_target" else targets
    return BuildGraph(graph=g, target_metadata=meta)


def build_include_graph(header_edges: pd.DataFrame) -> nx.DiGraph:
    """Construct the header inclusion graph from header_edges.parquet.

    Edge (A, B) means "A includes B". Edges are deduplicated across TUs,
    with ``weight`` counting how many TUs exhibit each inclusion.
    """
    # Count TU occurrences per (includer, included) pair
    counts = header_edges.groupby(["includer", "included"]).agg(
        weight=("source_file", "nunique"),
        is_system=("is_system", "all"),
    ).reset_index()

    g = nx.DiGraph()

    for _, row in counts.iterrows():
        g.add_edge(row["includer"], row["included"], weight=row["weight"])

    # Mark system headers as node attributes
    system_status = counts.groupby("included")["is_system"].all()
    for node, is_sys in system_status.items():
        if node in g:
            g.nodes[node]["is_system"] = bool(is_sys)

    return g


def compute_transitive_deps(bg: BuildGraph) -> pd.DataFrame:
    """Compute transitive dependency counts for each target.

    Returns a DataFrame with columns: cmake_target, n_direct_deps,
    n_transitive_deps, transitive_fraction.
    """
    g = bg.graph
    total = g.number_of_nodes()
    rows = []
    for node in g.nodes():
        n_direct = g.out_degree(node)
        n_trans = len(nx.descendants(g, node))
        rows.append({
            "cmake_target": node,
            "n_direct_deps": n_direct,
            "n_transitive_deps": n_trans,
            "transitive_fraction": n_trans / total if total > 0 else 0.0,
        })
    return pd.DataFrame(rows)


def compute_centrality_metrics(bg: BuildGraph) -> pd.DataFrame:
    """Compute centrality measures for the dependency graph.

    Returns a DataFrame indexed by cmake_target with columns:
    in_degree, out_degree, betweenness, pagerank.
    """
    g = bg.graph
    betweenness = nx.betweenness_centrality(g)
    pagerank = nx.pagerank(g)

    rows = []
    for node in g.nodes():
        rows.append({
            "cmake_target": node,
            "in_degree": g.in_degree(node),
            "out_degree": g.out_degree(node),
            "betweenness": betweenness[node],
            "pagerank": pagerank[node],
        })
    return pd.DataFrame(rows).set_index("cmake_target")


def compute_layer_assignments(bg: BuildGraph) -> pd.DataFrame:
    """Assign each target to an architectural layer.

    Layer 0 = leaf targets with no dependencies (out-degree 0).
    Layer N = max(dependency layers) + 1.
    """
    g = bg.graph
    layer_map: dict[str, int] = {}

    # Process in reverse topological order (leaves first)
    for node in reversed(list(nx.topological_sort(g))):
        successors = list(g.successors(node))
        if not successors:
            layer_map[node] = 0
        else:
            layer_map[node] = max(layer_map[s] for s in successors) + 1

    return pd.DataFrame([
        {"cmake_target": node, "layer": layer}
        for node, layer in layer_map.items()
    ])


def find_layer_violations(bg: BuildGraph, layers: pd.DataFrame) -> pd.DataFrame:
    """Identify dependency edges that violate strict layering.

    A violation occurs when a target depends on something at the same
    layer (lateral) or a higher layer (upward).
    """
    layer_map = layers.set_index("cmake_target")["layer"].to_dict()
    violations = []

    for source, dep in bg.graph.edges():
        src_layer = layer_map.get(source)
        dep_layer = layer_map.get(dep)
        if src_layer is None or dep_layer is None:
            continue
        if dep_layer >= src_layer:
            vtype = "lateral" if dep_layer == src_layer else "upward"
            violations.append({
                "source": source,
                "dependency": dep,
                "source_layer": src_layer,
                "dep_layer": dep_layer,
                "violation_type": vtype,
            })

    return pd.DataFrame(violations, columns=["source", "dependency", "source_layer", "dep_layer", "violation_type"])


def compute_graph_summary(bg: BuildGraph) -> dict:
    """Compute high-level graph statistics."""
    g = bg.graph
    meta = bg.target_metadata

    library_types = {t.value for t in TargetType if "library" in t.value.lower()}
    n_executables = (meta["target_type"] == TargetType.EXECUTABLE.value).sum()
    n_libraries = meta["target_type"].isin(library_types).sum()

    layers = compute_layer_assignments(bg)
    max_depth = int(layers["layer"].max()) if len(layers) > 0 else 0

    out_degrees = [g.out_degree(n) for n in g.nodes()]
    in_degrees = [g.in_degree(n) for n in g.nodes()]

    return {
        "n_targets": g.number_of_nodes(),
        "n_edges": g.number_of_edges(),
        "density": nx.density(g),
        "n_executables": int(n_executables),
        "n_libraries": int(n_libraries),
        "max_depth": max_depth,
        "avg_out_degree": sum(out_degrees) / len(out_degrees) if out_degrees else 0.0,
        "max_out_degree": max(out_degrees) if out_degrees else 0,
        "avg_in_degree": sum(in_degrees) / len(in_degrees) if in_degrees else 0.0,
        "max_in_degree": max(in_degrees) if in_degrees else 0,
        "is_dag": nx.is_directed_acyclic_graph(g),
    }
