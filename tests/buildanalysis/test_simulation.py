"""Tests for buildanalysis.simulation."""

import networkx as nx
import pandas as pd

from buildanalysis.simulation import (
    expected_daily_cost,
    rebuild_cost,
    replay_git_history,
    simulate_incremental_build,
    simulate_merge,
    simulate_split,
)


def make_chain_graph() -> nx.DiGraph:
    """A -> B -> C (A depends on B, B depends on C)."""
    G = nx.DiGraph()
    G.add_edge("A", "B", is_direct=True, dependency_type="link")
    G.add_edge("B", "C", is_direct=True, dependency_type="link")
    return G


def make_metrics_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "cmake_target": ["A", "B", "C"],
            "total_build_time_ms": [100, 200, 50],
            "compile_time_sum_ms": [80, 150, 40],
            "archive_time_ms": [10, 20, 5],
            "link_time_ms": [10, 30, 5],
            "codegen_file_count": [0, 0, 0],
            "git_commit_count_total": [20, 10, 5],
        }
    )


class TestRebuildCost:
    def test_leaf_only_rebuilds_self(self):
        G = make_chain_graph()
        df = make_metrics_df()
        # A is a leaf in build terms — nothing depends on A (it has no predecessors)
        cost = rebuild_cost(G, "A", df)
        assert cost == 100  # only A itself

    def test_root_rebuilds_chain(self):
        G = make_chain_graph()
        df = make_metrics_df()
        # If C changes, B depends on C, A depends on B
        # So changing C forces rebuild of C + B + A = 50 + 200 + 100 = 350
        cost = rebuild_cost(G, "C", df)
        # Actually: ancestors in reversed graph of C = {B, A}
        # In the original graph A->B->C, reversing gives C->B->A
        # descendants of C in reversed = {B, A}
        # So rebuild_cost(C) = C + B + A = 350
        # Wait, let me re-check the graph convention:
        # A->B means A depends on B. So in the reverse graph, B->A.
        # rev = G.reverse() gives C->B->A
        # nx.descendants(rev, C) = {B, A}
        # So changing C rebuilds A, B, C = 350
        assert cost == 350

    def test_middle_node(self):
        G = make_chain_graph()
        df = make_metrics_df()
        # B depends on C. A depends on B.
        # Changing B: descendants in rev = {A}
        # Cost = B + A = 300
        cost = rebuild_cost(G, "B", df)
        assert cost == 300


class TestExpectedDailyCost:
    def test_basic(self):
        G = make_chain_graph()
        df = make_metrics_df()
        # C has 5 commits in 12 months = 5/(12*20) = 0.0208... changes/day
        # rebuild_cost(C) = 350
        cost = expected_daily_cost(G, "C", df, df, git_history_months=12)
        expected = (5 / 240) * 350
        assert abs(cost - expected) < 1.0


class TestSimulateMerge:
    def test_savings_non_negative(self):
        G = make_chain_graph()
        df = make_metrics_df()
        result = simulate_merge(G, ["A", "B"], df)
        assert result["savings_ms"] >= 0

    def test_before_equals_sum(self):
        G = make_chain_graph()
        df = make_metrics_df()
        result = simulate_merge(G, ["A", "B"], df)
        assert result["before_ms"] == 300  # A=100 + B=200

    def test_inter_target_edges_noted(self):
        G = make_chain_graph()
        df = make_metrics_df()
        result = simulate_merge(G, ["A", "B"], df)
        notes = " ".join(result["notes"])
        assert "inter-target" in notes.lower() or "dependencies" in notes.lower()


class TestSimulateSplit:
    def test_returns_partitions(self):
        G = make_chain_graph()
        df = make_metrics_df()
        result = simulate_split(G, "B", [["b1.cpp"], ["b2.cpp"]], df)
        assert len(result["partitions"]) == 2
        assert result["partitions"][0]["file_count"] == 1

    def test_notes_codegen_warning(self):
        G = make_chain_graph()
        df = make_metrics_df().copy()
        df.loc[df["cmake_target"] == "B", "codegen_file_count"] = 3
        result = simulate_split(G, "B", [["b1.cpp"], ["b2.cpp"]], df)
        notes = " ".join(result["notes"])
        assert "generated" in notes.lower()


class TestSimulateIncrementalBuild:
    def test_no_modifications(self):
        G = make_chain_graph()
        times = {"A": 100, "B": 200, "C": 50}
        assert simulate_incremental_build(G, [], times, n_cores=4) == 0.0

    def test_leaf_change(self):
        G = make_chain_graph()
        times = {"A": 100, "B": 200, "C": 50}
        # Changing A (no dependants) should only rebuild A
        result = simulate_incremental_build(G, ["A"], times, n_cores=4)
        assert result == 100

    def test_root_change_rebuilds_chain(self):
        G = make_chain_graph()
        times = {"A": 100, "B": 200, "C": 50}
        # Changing C forces rebuild of C, B, A
        result = simulate_incremental_build(G, ["C"], times, n_cores=4)
        # With 4 cores on a chain: C(50) -> B(200) -> A(100) = 350 sequential
        assert result == 350

    def test_enabled_targets_filter(self):
        G = make_chain_graph()
        times = {"A": 100, "B": 200, "C": 50}
        # Changing C, but only B and C are enabled
        result = simulate_incremental_build(G, ["C"], times, n_cores=4, enabled_targets={"B", "C"})
        # Only rebuilds B and C (A is not enabled)
        assert result == 250

    def test_unlimited_cores(self):
        # Diamond: A depends on B and C, B and C depend on D
        G = nx.DiGraph()
        G.add_edge("A", "B", is_direct=True)
        G.add_edge("A", "C", is_direct=True)
        G.add_edge("B", "D", is_direct=True)
        G.add_edge("C", "D", is_direct=True)
        times = {"A": 100, "B": 200, "C": 150, "D": 50}
        # Changing D: rebuild D, B, C, A
        # With unlimited cores: D(50) -> B,C parallel(200) -> A(100) = 350
        result = simulate_incremental_build(G, ["D"], times, n_cores=0)
        assert result == 350


class TestReplayGitHistory:
    def test_basic_replay(self):
        G = make_chain_graph()
        times = {"A": 100, "B": 200, "C": 50}
        file_to_target = {"/src/a.cpp": "A", "/src/c.cpp": "C"}
        commits = pd.DataFrame(
            {
                "commit_hash": ["h1", "h2"],
                "author_email": ["alice@co.com", "bob@co.com"],
                "source_file": ["/src/a.cpp", "/src/c.cpp"],
            }
        )
        result = replay_git_history(G, commits, file_to_target, times, n_cores=4)
        assert len(result) == 2
        # Commit h1 modifies A (leaf), rebuild only A
        h1 = result[result["commit_hash"] == "h1"].iloc[0]
        assert h1["build_time_ms"] == 100
        assert h1["modified_targets"] == 1

    def test_unknown_file_skipped(self):
        G = make_chain_graph()
        times = {"A": 100, "B": 200, "C": 50}
        file_to_target = {}
        commits = pd.DataFrame(
            {
                "commit_hash": ["h1"],
                "author_email": ["alice@co.com"],
                "source_file": ["/src/unknown.cpp"],
            }
        )
        result = replay_git_history(G, commits, file_to_target, times, n_cores=4)
        assert result.iloc[0]["build_time_ms"] == 0.0
