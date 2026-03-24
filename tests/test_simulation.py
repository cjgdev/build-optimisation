"""Tests for build_optimiser.simulation module."""

from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd
import pytest

from build_optimiser.simulation import (
    rebuild_cost,
    expected_daily_cost,
    simulate_merge,
    simulate_split,
    monte_carlo_rebuild_cost,
)


@pytest.fixture
def sim_graph():
    """Graph: A -> B -> C, A -> D"""
    G = nx.DiGraph()
    G.add_edges_from([("A", "B"), ("B", "C"), ("A", "D")])
    return G


@pytest.fixture
def sim_metrics():
    return pd.DataFrame({
        "cmake_target": ["A", "B", "C", "D"],
        "compile_time_sum_ms": [100, 200, 300, 50],
        "git_commit_count_total": [10, 5, 3, 2],
    })


@pytest.fixture
def sim_file_metrics():
    return pd.DataFrame({
        "source_file": ["a1.cpp", "a2.cpp", "b1.cpp", "c1.cpp", "d1.cpp"],
        "cmake_target": ["A", "A", "B", "C", "D"],
        "compile_time_ms": [50, 50, 200, 300, 50],
    })


class TestRebuildCost:
    def test_leaf_target(self, sim_graph, sim_metrics):
        # D is a leaf with only A depending on it
        # ancestors of D = {A}, so affected = {A, D} => 100 + 50
        cost = rebuild_cost(sim_graph, "D", sim_metrics)
        assert cost == 150

    def test_with_dependants(self, sim_graph, sim_metrics):
        # B is depended on by A, so changing B rebuilds A + B
        # ancestors of B = {A}, so affected = {A, B}
        cost = rebuild_cost(sim_graph, "B", sim_metrics)
        assert cost == 100 + 200  # A + B


class TestExpectedDailyCost:
    def test_computes_weighted_cost(self, sim_graph, sim_metrics):
        cost = expected_daily_cost(
            sim_graph, "B", sim_metrics, sim_metrics
        )
        assert cost > 0


class TestSimulateMerge:
    def test_merge_result(self, sim_graph, sim_metrics):
        result = simulate_merge(sim_graph, ["C", "D"], sim_metrics)
        assert "merged_target" in result
        assert "delta" in result
        assert result["merged_target"] == "C+D"


class TestSimulateSplit:
    def test_split_result(self, sim_graph, sim_metrics, sim_file_metrics):
        result = simulate_split(
            sim_graph, "A", [["a1.cpp"], ["a2.cpp"]],
            sim_metrics, sim_file_metrics,
        )
        assert len(result["new_targets"]) == 2
        assert "delta" in result


class TestMonteCarloRebuildCost:
    def test_returns_stats(self, sim_graph, sim_metrics):
        result = monte_carlo_rebuild_cost(
            sim_graph, sim_metrics, n_simulations=100, seed=42
        )
        assert "mean" in result
        assert "median" in result
        assert "std" in result
        assert "p95" in result
        assert result["mean"] >= 0
