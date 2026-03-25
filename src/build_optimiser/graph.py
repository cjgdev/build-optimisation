"""Graph loading and analysis utilities for CMake dependency DAGs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd


def load_graph(dot_dir: str) -> nx.DiGraph:
    """Read the main dot file from a directory and return a NetworkX DiGraph.

    CMake's --graphviz generates a main file (typically named 'dependencies'
    or 'dependencies.dot') and per-target files. This loads the main one.
    """
    dot_path = Path(dot_dir)

    # Find the main dot file (the one without a '.' prefix in the stem,
    # and typically the shortest name or named 'dependencies')
    candidates = sorted(dot_path.glob("*.dot"), key=lambda p: len(p.name))
    main_file = None
    for c in candidates:
        # The main file is usually 'dependencies' or 'dependencies.dot'
        # Per-target files are 'dependencies.target_name' or similar
        if c.stem == "dependencies" or "." not in c.stem:
            main_file = c
            break
    if main_file is None and candidates:
        main_file = candidates[0]
    if main_file is None:
        raise FileNotFoundError(f"No .dot files found in {dot_dir}")

    # pydot-based parsing
    import pydot

    graphs = pydot.graph_from_dot_file(str(main_file))
    if not graphs:
        raise ValueError(f"Failed to parse {main_file}")
    dot_graph = graphs[0]

    G = nx.DiGraph()

    # Add nodes
    for node in dot_graph.get_nodes():
        name = node.get_name().strip('"')
        if name in ("node", "edge", "graph"):
            continue
        label = node.get_label()
        if label:
            label = label.strip('"')
        G.add_node(name, label=label or name)

    # Add edges
    for edge in dot_graph.get_edges():
        src = edge.get_source().strip('"')
        dst = edge.get_destination().strip('"')
        attrs: dict[str, Any] = {}
        label = edge.get_label()
        if label:
            attrs["scope"] = label.strip('"')
        G.add_edge(src, dst, **attrs)

    return G


def direct_dependencies(G: nx.DiGraph, target: str) -> list[str]:
    """Return direct dependencies (successors) of a target."""
    return list(G.successors(target))


def transitive_dependencies(G: nx.DiGraph, target: str) -> set[str]:
    """Return all transitive dependencies of a target."""
    return nx.descendants(G, target)


def direct_dependants(G: nx.DiGraph, target: str) -> list[str]:
    """Return targets that directly depend on this target (predecessors)."""
    return list(G.predecessors(target))


def transitive_dependants(G: nx.DiGraph, target: str) -> set[str]:
    """Return all targets that transitively depend on this target."""
    return nx.ancestors(G, target)


def topological_depth(G: nx.DiGraph, target: str) -> int:
    """Compute the longest path from any root to this target.

    Roots are nodes with no predecessors (in-degree 0).
    """
    # Use longest path lengths from all sources
    if target not in G:
        raise KeyError(f"Target {target!r} not in graph")

    max_depth = 0
    for pred in nx.ancestors(G, target):
        try:
            length = nx.dag_longest_path_length(
                G.subgraph(nx.ancestors(G, target) | {target, pred})
            )
            max_depth = max(max_depth, length)
        except nx.NetworkXError:
            continue

    # Simpler approach: BFS/DFS from roots
    # Actually, compute longest path to each node via dynamic programming
    if not nx.is_directed_acyclic_graph(G):
        raise nx.NetworkXError("Graph contains cycles")

    topo_order = list(nx.topological_sort(G))
    depths: dict[str, int] = {}
    for node in topo_order:
        preds = list(G.predecessors(node))
        if not preds:
            depths[node] = 0
        else:
            depths[node] = max(depths.get(p, 0) for p in preds) + 1

    return depths.get(target, 0)


def all_topological_depths(G: nx.DiGraph) -> dict[str, int]:
    """Compute topological depth for all nodes efficiently."""
    if not nx.is_directed_acyclic_graph(G):
        raise nx.NetworkXError("Graph contains cycles")

    topo_order = list(nx.topological_sort(G))
    depths: dict[str, int] = {}
    for node in topo_order:
        preds = list(G.predecessors(node))
        if not preds:
            depths[node] = 0
        else:
            depths[node] = max(depths[p] for p in preds) + 1
    return depths


def critical_path(G: nx.DiGraph, weight_attr: str = "weight") -> list[str]:
    """Find the longest weighted path through the DAG (critical path).

    Args:
        G: Directed acyclic graph with numeric node or edge weights.
        weight_attr: Node attribute name containing the weight (e.g. compile time).

    Returns:
        List of node names along the critical path.
    """
    if not nx.is_directed_acyclic_graph(G):
        raise nx.NetworkXError("Graph contains cycles")

    # Create a weighted edge graph from node weights
    # Edge weight = weight of the destination node
    weighted = G.copy()
    for u, v in weighted.edges():
        node_weight = weighted.nodes[v].get(weight_attr, 0)
        weighted[u][v]["_cp_weight"] = node_weight

    # For source nodes, we need to account for their own weight
    # Use nx.dag_longest_path with edge weights
    # But we need node weights as edge weights
    # Alternative: use the node-weighted longest path approach
    topo_order = list(nx.topological_sort(G))
    dist: dict[str, float] = {}
    pred: dict[str, str | None] = {}

    for node in topo_order:
        node_weight = G.nodes[node].get(weight_attr, 0)
        predecessors = list(G.predecessors(node))
        if not predecessors:
            dist[node] = node_weight
            pred[node] = None
        else:
            best_pred = max(predecessors, key=lambda p: dist.get(p, 0))
            dist[node] = dist[best_pred] + node_weight
            pred[node] = best_pred

    # Find the end of the critical path
    if not dist:
        return []
    end_node = max(dist, key=lambda n: dist[n])

    # Trace back
    path = []
    current: str | None = end_node
    while current is not None:
        path.append(current)
        current = pred[current]
    path.reverse()
    return path


def critical_path_length(G: nx.DiGraph, weight_attr: str = "weight") -> float:
    """Return the total weight of the critical path."""
    path = critical_path(G, weight_attr)
    return sum(G.nodes[n].get(weight_attr, 0) for n in path)


def node_centrality(G: nx.DiGraph) -> dict[str, float]:
    """Compute betweenness centrality for all nodes."""
    return nx.betweenness_centrality(G)


def attach_metrics(G: nx.DiGraph, df: pd.DataFrame, key_column: str = "cmake_target") -> None:
    """Set target-level metrics as node attributes from a DataFrame.

    Args:
        G: The dependency graph.
        df: DataFrame with target metrics.
        key_column: Column name containing target names matching graph nodes.
    """
    metrics = df.set_index(key_column).to_dict("index")
    for node in G.nodes:
        if node in metrics:
            for attr, value in metrics[node].items():
                G.nodes[node][attr] = value
