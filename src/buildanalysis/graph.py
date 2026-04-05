"""Graph loading, construction, and analysis utilities for build dependency DAGs.

Convention: edge A -> B means "A depends on B" (A builds after B).
- nx.descendants(G, t) = things t depends on (transitive dependencies)
- nx.ancestors(G, t) = things that depend on t (transitive dependants)

This module consolidates both low-level (raw nx.DiGraph) and high-level
(BuildGraph) graph operations into a single API.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import networkx as nx
import pandas as pd

from buildanalysis.cmake_file_api import CodeModel
from buildanalysis.types import BuildGraph, TargetType

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_graph(g: BuildGraph | nx.DiGraph) -> nx.DiGraph:
    """Extract the raw DiGraph from a BuildGraph or pass through."""
    return g.graph if isinstance(g, BuildGraph) else g


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


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
        cycles = list(itertools.islice(nx.simple_cycles(g), 5))
        raise ValueError(f"Graph contains cycles: {cycles}")

    meta = targets.set_index("cmake_target") if targets.index.name != "cmake_target" else targets
    return BuildGraph(graph=g, target_metadata=meta)


def build_include_graph(header_edges: pd.DataFrame) -> nx.DiGraph:
    """Construct the header inclusion graph from header_edges.parquet.

    Edge (A, B) means "A includes B". Edges are deduplicated across TUs,
    with ``weight`` counting how many TUs exhibit each inclusion.
    """
    # Count TU occurrences per (includer, included) pair
    counts = (
        header_edges.groupby(["includer", "included"])
        .agg(
            weight=("source_file", "nunique"),
            is_system=("is_system", "all"),
        )
        .reset_index()
    )

    g = nx.DiGraph()

    for _, row in counts.iterrows():
        g.add_edge(row["includer"], row["included"], weight=row["weight"])

    # Mark system headers as node attributes
    system_status = counts.groupby("included")["is_system"].all()
    for node, is_sys in system_status.items():
        if node in g:
            g.nodes[node]["is_system"] = bool(is_sys)

    return g


def load_raw_graph(edge_list_path: str | Path) -> nx.DiGraph:
    """Load the dependency graph from an edge_list.parquet file.

    Returns a raw nx.DiGraph (not a BuildGraph). Edge attributes:
    is_direct (bool), dependency_type (str).
    """
    df = pd.read_parquet(edge_list_path)
    G = nx.DiGraph()

    all_nodes = set(df["source_target"]) | set(df["dest_target"])
    G.add_nodes_from(all_nodes)

    for _, row in df.iterrows():
        G.add_edge(
            row["source_target"],
            row["dest_target"],
            is_direct=bool(row["is_direct"]),
            dependency_type=row["dependency_type"],
        )

    return G


def load_raw_graph_from_codemodel(codemodel: CodeModel) -> nx.DiGraph:
    """Build a raw nx.DiGraph directly from parsed File API data."""
    G = nx.DiGraph()
    G.add_nodes_from(codemodel.targets.keys())

    for edge in codemodel.edges:
        G.add_edge(
            edge.source_target,
            edge.dest_target,
            is_direct=edge.is_direct,
            dependency_type=edge.dependency_type,
        )

    return G


# ---------------------------------------------------------------------------
# Node-level queries (accept BuildGraph | nx.DiGraph)
# ---------------------------------------------------------------------------


def direct_dependencies(g: BuildGraph | nx.DiGraph, target: str) -> list[str]:
    """Return direct dependencies (successors where is_direct == True).

    If the ``is_direct`` edge attribute is absent (e.g. graph built with
    ``build_dependency_graph(direct_only=True)``), all edges are assumed direct.
    """
    _g = _resolve_graph(g)
    return [n for n in _g.successors(target) if _g[target][n].get("is_direct", True)]


def transitive_dependencies(g: BuildGraph | nx.DiGraph, target: str) -> set[str]:
    """Return transitive-only dependencies (all descendants minus direct)."""
    _g = _resolve_graph(g)
    return nx.descendants(_g, target) - set(direct_dependencies(_g, target))


def direct_dependants(g: BuildGraph | nx.DiGraph, target: str) -> list[str]:
    """Return targets that directly depend on this target.

    If the ``is_direct`` edge attribute is absent, all edges are assumed direct.
    """
    _g = _resolve_graph(g)
    return [n for n in _g.predecessors(target) if _g[n][target].get("is_direct", True)]


def transitive_dependants(g: BuildGraph | nx.DiGraph, target: str) -> set[str]:
    """Return all targets that depend on this target (directly or transitively)."""
    _g = _resolve_graph(g)
    return nx.ancestors(_g, target)


def topological_depth(g: BuildGraph | nx.DiGraph, target: str) -> int:
    """Longest path from any root (in-degree 0) to this node.

    Uses O(V+E) dynamic programming over a topological sort rather than
    enumerating all simple paths.
    """
    _g = _resolve_graph(g)
    depth: dict[str, int] = {}
    for node in nx.topological_sort(_g):
        predecessors = list(_g.predecessors(node))
        if not predecessors:
            depth[node] = 0
        else:
            depth[node] = max(depth[p] for p in predecessors if p in depth) + 1
        if node == target:
            break
    return depth.get(target, 0)


def subgraph_for_target(g: BuildGraph | nx.DiGraph, target: str, depth: int = 1) -> nx.DiGraph:
    """Extract the local neighbourhood for visualisation."""
    _g = _resolve_graph(g)
    return nx.ego_graph(_g, target, radius=depth, undirected=True)


def attach_metrics(g: nx.DiGraph, df: pd.DataFrame, key_col: str = "cmake_target") -> None:
    """Set target-level metrics as node attributes from a DataFrame.

    Mutates g in place.
    """
    metrics_dict = df.set_index(key_col).to_dict(orient="index")
    for node in g.nodes:
        if node in metrics_dict:
            g.nodes[node].update(metrics_dict[node])


# ---------------------------------------------------------------------------
# DataFrame-returning analyses (require BuildGraph)
# ---------------------------------------------------------------------------


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
        rows.append(
            {
                "cmake_target": node,
                "n_direct_deps": n_direct,
                "n_transitive_deps": n_trans,
                "transitive_fraction": n_trans / total if total > 0 else 0.0,
            }
        )
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
        rows.append(
            {
                "cmake_target": node,
                "in_degree": g.in_degree(node),
                "out_degree": g.out_degree(node),
                "betweenness": betweenness[node],
                "pagerank": pagerank[node],
            }
        )
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

    return pd.DataFrame([{"cmake_target": node, "layer": layer} for node, layer in layer_map.items()])


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
            violations.append(
                {
                    "source": source,
                    "dependency": dep,
                    "source_layer": src_layer,
                    "dep_layer": dep_layer,
                    "violation_type": vtype,
                }
            )

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
