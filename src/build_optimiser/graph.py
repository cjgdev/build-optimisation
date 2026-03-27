"""Graph loading and analysis utilities for the dependency DAG.

Convention: edge A -> B means "A depends on B" (A builds after B).
- nx.descendants(G, t) = things t depends on
- nx.descendants(G.reverse(), t) = things that depend on t (dependants)
"""

from __future__ import annotations

from pathlib import Path

import networkx as nx
import pandas as pd
import pyarrow.parquet as pq

from build_optimiser.cmake_file_api import CodeModel


def load_graph(edge_list_path: str | Path) -> nx.DiGraph:
    """Load the dependency graph from an edge_list.parquet file.

    Edge attributes: is_direct (bool), dependency_type (str).
    """
    df = pd.read_parquet(edge_list_path)
    G = nx.DiGraph()

    # Add all unique nodes
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


def load_graph_from_codemodel(codemodel: CodeModel) -> nx.DiGraph:
    """Build the graph directly from parsed File API data."""
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


def direct_dependencies(G: nx.DiGraph, target: str) -> list[str]:
    """Return direct dependencies (successors where is_direct == True)."""
    return [
        n for n in G.successors(target)
        if G[target][n].get("is_direct", False)
    ]


def transitive_dependencies(G: nx.DiGraph, target: str) -> set[str]:
    """Return transitive-only dependencies (all descendants minus direct)."""
    return nx.descendants(G, target) - set(direct_dependencies(G, target))


def direct_dependants(G: nx.DiGraph, target: str) -> list[str]:
    """Return targets that directly depend on this target."""
    return [
        n for n in G.predecessors(target)
        if G[n][target].get("is_direct", False)
    ]


def transitive_dependants(G: nx.DiGraph, target: str) -> set[str]:
    """Return all targets that depend on this target (directly or transitively)."""
    return nx.ancestors(G, target)


def topological_depth(G: nx.DiGraph, target: str) -> int:
    """Longest path from any root (in-degree 0) to this node."""
    ancestors = nx.ancestors(G, target)
    if not ancestors:
        return 0
    max_depth = 0
    for ancestor in ancestors:
        if G.in_degree(ancestor) == 0:  # root node
            try:
                paths = list(nx.all_simple_paths(G, ancestor, target))
                for path in paths:
                    max_depth = max(max_depth, len(path) - 1)
            except nx.NetworkXError:
                pass
    return max_depth


def critical_path(G: nx.DiGraph, weight_attr: str = "total_build_time_ms") -> list[str]:
    """Find the longest weighted path through the DAG (the critical path).

    Requires node attributes to be set first via attach_metrics().
    """
    return nx.dag_longest_path(G, weight=weight_attr)


def critical_path_length(G: nx.DiGraph, weight_attr: str = "total_build_time_ms") -> int:
    """Total weight of the critical path."""
    return nx.dag_longest_path_length(G, weight=weight_attr)


def node_centrality(G: nx.DiGraph) -> dict[str, float]:
    """Betweenness centrality for all nodes."""
    return nx.betweenness_centrality(G)


def attach_metrics(G: nx.DiGraph, df: pd.DataFrame, key_col: str = "cmake_target") -> None:
    """Set target-level metrics as node attributes from a DataFrame.

    Mutates G in place.
    """
    metrics_dict = df.set_index(key_col).to_dict(orient="index")
    for node in G.nodes:
        if node in metrics_dict:
            G.nodes[node].update(metrics_dict[node])


def subgraph_for_target(G: nx.DiGraph, target: str, depth: int = 1) -> nx.DiGraph:
    """Extract the local neighbourhood for visualisation."""
    return nx.ego_graph(G, target, radius=depth, undirected=False)
