"""Tests for build_optimiser.graph module."""

from __future__ import annotations

import tempfile
from pathlib import Path

import networkx as nx
import pandas as pd
import pytest

from build_optimiser.graph import (
    direct_dependencies,
    transitive_dependencies,
    direct_dependants,
    transitive_dependants,
    topological_depth,
    all_topological_depths,
    critical_path,
    critical_path_length,
    node_centrality,
    attach_metrics,
)


@pytest.fixture
def sample_dag():
    """Create a simple DAG for testing.

    Structure: A -> B -> D
               A -> C -> D
    """
    G = nx.DiGraph()
    G.add_edges_from([("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")])
    return G


@pytest.fixture
def weighted_dag():
    """DAG with compile time weights on nodes."""
    G = nx.DiGraph()
    G.add_edges_from([("A", "B"), ("B", "C"), ("A", "D"), ("D", "C")])
    nx.set_node_attributes(G, {"A": 10, "B": 20, "C": 5, "D": 15}, "weight")
    return G


class TestDirectDependencies:
    def test_returns_successors(self, sample_dag):
        deps = direct_dependencies(sample_dag, "A")
        assert set(deps) == {"B", "C"}

    def test_leaf_node(self, sample_dag):
        deps = direct_dependencies(sample_dag, "D")
        assert deps == []


class TestTransitiveDependencies:
    def test_all_descendants(self, sample_dag):
        deps = transitive_dependencies(sample_dag, "A")
        assert deps == {"B", "C", "D"}

    def test_leaf_node(self, sample_dag):
        deps = transitive_dependencies(sample_dag, "D")
        assert deps == set()


class TestDirectDependants:
    def test_returns_predecessors(self, sample_dag):
        deps = direct_dependants(sample_dag, "D")
        assert set(deps) == {"B", "C"}


class TestTransitiveDependants:
    def test_all_ancestors(self, sample_dag):
        deps = transitive_dependants(sample_dag, "D")
        assert deps == {"A", "B", "C"}


class TestTopologicalDepth:
    def test_root_depth(self, sample_dag):
        assert topological_depth(sample_dag, "A") == 0

    def test_leaf_depth(self, sample_dag):
        assert topological_depth(sample_dag, "D") == 2

    def test_middle_depth(self, sample_dag):
        assert topological_depth(sample_dag, "B") == 1


class TestAllTopologicalDepths:
    def test_all_depths(self, sample_dag):
        depths = all_topological_depths(sample_dag)
        assert depths["A"] == 0
        assert depths["B"] == 1
        assert depths["C"] == 1
        assert depths["D"] == 2


class TestCriticalPath:
    def test_finds_longest_path(self, weighted_dag):
        cp = critical_path(weighted_dag, "weight")
        assert len(cp) > 0
        # The critical path should include the heaviest nodes
        total = sum(weighted_dag.nodes[n]["weight"] for n in cp)
        assert total > 0

    def test_length(self, weighted_dag):
        length = critical_path_length(weighted_dag, "weight")
        assert length > 0


class TestNodeCentrality:
    def test_returns_dict(self, sample_dag):
        centrality = node_centrality(sample_dag)
        assert isinstance(centrality, dict)
        assert len(centrality) == 4


class TestAttachMetrics:
    def test_attaches_attributes(self, sample_dag):
        df = pd.DataFrame({
            "cmake_target": ["A", "B", "C", "D"],
            "compile_time": [100, 200, 150, 50],
        })
        attach_metrics(sample_dag, df)
        assert sample_dag.nodes["A"]["compile_time"] == 100
        assert sample_dag.nodes["B"]["compile_time"] == 200
