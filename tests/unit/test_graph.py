"""Tests for build_optimiser.graph."""

import networkx as nx
import pandas as pd

from build_optimiser.graph import (
    attach_metrics,
    critical_path,
    direct_dependants,
    direct_dependencies,
    node_centrality,
    subgraph_for_target,
    topological_depth,
    transitive_dependants,
    transitive_dependencies,
)


def make_diamond_graph() -> nx.DiGraph:
    """Build a diamond dependency graph: A -> B, A -> C, B -> D, C -> D.

    A depends on B and C. B and C both depend on D.
    """
    G = nx.DiGraph()
    G.add_edge("A", "B", is_direct=True, dependency_type="link")
    G.add_edge("A", "C", is_direct=True, dependency_type="link")
    G.add_edge("B", "D", is_direct=True, dependency_type="link")
    G.add_edge("C", "D", is_direct=True, dependency_type="link")
    # A also has a transitive edge to D
    G.add_edge("A", "D", is_direct=False, dependency_type="transitive")
    return G


def make_linear_graph() -> nx.DiGraph:
    """Build a linear chain: A -> B -> C -> D."""
    G = nx.DiGraph()
    G.add_edge("A", "B", is_direct=True, dependency_type="link")
    G.add_edge("B", "C", is_direct=True, dependency_type="link")
    G.add_edge("C", "D", is_direct=True, dependency_type="link")
    return G


class TestDirectDependencies:
    def test_diamond(self):
        G = make_diamond_graph()
        deps = direct_dependencies(G, "A")
        assert set(deps) == {"B", "C"}

    def test_excludes_transitive(self):
        G = make_diamond_graph()
        deps = direct_dependencies(G, "A")
        assert "D" not in deps  # D is transitive-only for A

    def test_leaf_has_no_deps(self):
        G = make_diamond_graph()
        deps = direct_dependencies(G, "D")
        assert deps == []


class TestTransitiveDependencies:
    def test_diamond(self):
        G = make_diamond_graph()
        trans = transitive_dependencies(G, "A")
        assert "D" in trans

    def test_leaf_has_no_transitive(self):
        G = make_diamond_graph()
        trans = transitive_dependencies(G, "D")
        assert trans == set()


class TestDirectDependants:
    def test_diamond(self):
        G = make_diamond_graph()
        deps = direct_dependants(G, "D")
        assert set(deps) == {"B", "C"}

    def test_root_has_no_dependants(self):
        G = make_diamond_graph()
        deps = direct_dependants(G, "A")
        assert deps == []


class TestTransitiveDependants:
    def test_diamond(self):
        G = make_diamond_graph()
        deps = transitive_dependants(G, "D")
        assert "A" in deps
        assert "B" in deps
        assert "C" in deps


class TestTopologicalDepth:
    def test_linear_chain(self):
        G = make_linear_graph()
        assert topological_depth(G, "A") == 0  # root
        assert topological_depth(G, "D") == 3  # deepest

    def test_diamond_depth(self):
        G = make_diamond_graph()
        assert topological_depth(G, "D") == 2  # A->B->D or A->C->D


class TestCriticalPath:
    def test_linear_chain(self):
        G = make_linear_graph()
        for n in G:
            G.nodes[n]["weight"] = 10
        path = critical_path(G, weight_attr="weight")
        assert path == ["A", "B", "C", "D"]

    def test_weighted_path(self):
        G = make_diamond_graph()
        G.nodes["A"]["weight"] = 1
        G.nodes["B"]["weight"] = 100  # heavy
        G.nodes["C"]["weight"] = 1
        G.nodes["D"]["weight"] = 1
        path = critical_path(G, weight_attr="weight")
        assert "B" in path  # should go through B


class TestAttachMetrics:
    def test_sets_node_attributes(self):
        G = make_diamond_graph()
        df = pd.DataFrame({
            "cmake_target": ["A", "B", "C", "D"],
            "total_build_time_ms": [100, 200, 150, 50],
        })
        attach_metrics(G, df)
        assert G.nodes["A"]["total_build_time_ms"] == 100
        assert G.nodes["B"]["total_build_time_ms"] == 200


class TestNodeCentrality:
    def test_returns_all_nodes(self):
        G = make_diamond_graph()
        cent = node_centrality(G)
        assert set(cent.keys()) == {"A", "B", "C", "D"}


class TestSubgraph:
    def test_depth_1(self):
        G = make_linear_graph()
        sub = subgraph_for_target(G, "B", depth=1)
        assert "B" in sub
        assert "A" in sub or "C" in sub
