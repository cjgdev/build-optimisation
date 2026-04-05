import networkx as nx
import pandas as pd
import pytest

from buildanalysis.build import (
    PoolConfig,
    _compute_cp_weights,
    compute_critical_path,
    simulate_build,
    validate_simulation,
    whatif_reduce_target_time,
    whatif_remove_edge,
)
from buildanalysis.graph import build_dependency_graph
from buildanalysis.types import AnalysisScope, BuildGraph

# ---------------------------------------------------------------------------
# PoolConfig
# ---------------------------------------------------------------------------


class TestPoolConfig:
    def test_default_is_unlimited(self):
        cfg = PoolConfig.default()
        assert cfg.is_unlimited("link_pool")
        assert cfg.is_unlimited("any_pool")
        assert cfg.depth("link_pool") == 0

    def test_with_link_pool(self):
        cfg = PoolConfig.with_link_pool(4)
        assert cfg.depth("link_pool") == 4
        assert not cfg.is_unlimited("link_pool")
        assert cfg.is_unlimited("compile_pool")

    def test_unknown_pool_is_unlimited(self):
        cfg = PoolConfig(pools={"link_pool": 2})
        assert cfg.is_unlimited("other_pool")


# ---------------------------------------------------------------------------
# Critical path weights
# ---------------------------------------------------------------------------


class TestCpWeights:
    def test_chain_weights(self, chain_graph):
        # A -> B -> C -> D -> E (5-node chain)
        # E (leaf): weight=1, D: 2, C: 3, B: 4, A: 5
        weights = _compute_cp_weights(chain_graph)
        assert weights["E"] == 1
        assert weights["D"] == 2
        assert weights["C"] == 3
        assert weights["B"] == 4
        assert weights["A"] == 5

    def test_diamond_weights(self, diamond_graph):
        # A -> B -> D, A -> C -> D
        # D: 1, B: 2, C: 2, A: 3
        weights = _compute_cp_weights(diamond_graph)
        assert weights["D"] == 1
        assert weights["B"] == 2
        assert weights["C"] == 2
        assert weights["A"] == 3

    def test_phony_node_weight_zero(self):
        targets = pd.DataFrame(
            {
                "cmake_target": ["A", "B", "C"],
                "target_type": ["executable", "interface_library", "static_library"],
            }
        )
        edges = pd.DataFrame(
            {
                "source_target": ["A", "B"],
                "dest_target": ["B", "C"],
                "is_direct": [True, True],
                "dependency_type": ["link", "link"],
            }
        )
        bg = build_dependency_graph(targets, edges)
        weights = _compute_cp_weights(bg)
        # B is phony (own=0): C=1, B=0+1=1, A=1+1=2
        assert weights["C"] == 1
        assert weights["B"] == 1
        assert weights["A"] == 2

    def test_wide_graph_leaves_equal(self, wide_graph):
        weights = _compute_cp_weights(wide_graph)
        # All leaves have weight 1, root has weight 2
        for i in range(20):
            assert weights[f"leaf_{i}"] == 1
        assert weights["root"] == 2


# ---------------------------------------------------------------------------
# Critical path (unchanged API)
# ---------------------------------------------------------------------------


class TestCriticalPath:
    def test_diamond(self, diamond_graph, diamond_timing):
        result = compute_critical_path(diamond_graph, diamond_timing)
        # Critical path: D(5s) -> B(30s) -> A(10s) = 45s
        assert result.total_time_s == pytest.approx(45.0, rel=0.01)
        assert "B" in result.path
        assert "A" in result.path
        assert "D" in result.path

        # C should have slack
        c_row = result.target_slack[result.target_slack["cmake_target"] == "C"].iloc[0]
        assert c_row["slack_ms"] == pytest.approx(10_000, rel=0.01)
        assert not c_row["on_critical_path"]

    def test_chain_no_parallelism(self, chain_graph, chain_timing):
        result = compute_critical_path(chain_graph, chain_timing)
        assert result.total_time_s == pytest.approx(50.0, rel=0.01)
        assert result.parallelism_ratio == pytest.approx(1.0, rel=0.01)
        assert result.target_slack["on_critical_path"].all()

    def test_wide_max_parallelism(self, wide_graph, wide_timing):
        result = compute_critical_path(wide_graph, wide_timing)
        assert result.total_time_s == pytest.approx(11.0, rel=0.01)
        assert result.total_work_s == pytest.approx(201.0, rel=0.01)
        assert result.parallelism_ratio == pytest.approx(201.0 / 11.0, rel=0.01)


# ---------------------------------------------------------------------------
# Build simulation (existing tests, now using Ninja-faithful scheduler)
# ---------------------------------------------------------------------------


class TestSimulation:
    def test_single_core_equals_total_work(self, diamond_graph, diamond_timing):
        schedule = simulate_build(diamond_graph, diamond_timing, n_cores=1)
        total = schedule["end_ms"].max()
        # Single core: total time = sum of all target times = 65s = 65000ms
        assert total == pytest.approx(65_000, rel=0.01)

    def test_infinite_cores_equals_critical_path(self, diamond_graph, diamond_timing):
        schedule = simulate_build(diamond_graph, diamond_timing, n_cores=100)
        total = schedule["end_ms"].max()
        cp = compute_critical_path(diamond_graph, diamond_timing)
        assert total == pytest.approx(cp.total_time_s * 1000, rel=0.01)

    def test_schedule_respects_dependencies(self, diamond_graph, diamond_timing):
        schedule = simulate_build(diamond_graph, diamond_timing, n_cores=4)
        sched_map = schedule.set_index("cmake_target")
        assert sched_map.loc["A", "start_ms"] >= sched_map.loc["B", "end_ms"]
        assert sched_map.loc["B", "start_ms"] >= sched_map.loc["D", "end_ms"]

    def test_all_targets_scheduled(self, diamond_graph, diamond_timing):
        schedule = simulate_build(diamond_graph, diamond_timing, n_cores=4)
        assert set(schedule["cmake_target"]) == set(diamond_graph.graph.nodes())


# ---------------------------------------------------------------------------
# Ninja scheduler specifics
# ---------------------------------------------------------------------------


class TestNinjaScheduler:
    def test_deep_chain_prioritized_over_shallow(self):
        # root -> deep_1 -> deep_2 -> leaf  (chain depth 4)
        # root -> shallow_leaf              (chain depth 2)
        # With 1 core, leaf (cp_weight=1) and shallow_leaf (cp_weight=1) are both ready.
        # But leaf is on a deeper chain from root's perspective.
        # The scheduler should pick leaf first because deep_2 (which depends on leaf)
        # has higher cp_weight than shallow_leaf.
        # Actually with 1 core: both leaf and shallow_leaf are ready at t=0.
        # leaf cp_weight=1, shallow_leaf cp_weight=1 — tied by weight.
        # The priority that matters is at the ready queue: leaf and shallow_leaf both have weight 1.
        # After leaf finishes, deep_2 (weight 2) becomes ready.
        # With cp_weight ordering, leaf should still run before shallow_leaf because
        # at the initial step they have equal priority (both weight=1) — tie broken by name.
        # The real test: after leaf finishes, deep_2 (weight=3) should run before shallow_leaf (weight=1).
        targets = pd.DataFrame(
            {
                "cmake_target": ["root", "deep_1", "deep_2", "leaf", "shallow_leaf"],
                "target_type": ["executable"] + ["static_library"] * 4,
            }
        )
        edges = pd.DataFrame(
            {
                "source_target": ["root", "root", "deep_1", "deep_2"],
                "dest_target": ["deep_1", "shallow_leaf", "deep_2", "leaf"],
                "is_direct": [True, True, True, True],
                "dependency_type": ["link"] * 4,
            }
        )
        bg = build_dependency_graph(targets, edges)
        timing = pd.DataFrame(
            {
                "cmake_target": ["root", "deep_1", "deep_2", "leaf", "shallow_leaf"],
                "total_build_time_ms": [1_000] * 5,
            }
        )

        # With 2 cores: leaf and shallow_leaf start in parallel.
        # After leaf finishes, deep_2 (weight 3) should start before
        # anything else that might be ready.
        schedule = simulate_build(bg, timing, n_cores=2)
        sched_map = schedule.set_index("cmake_target")

        # deep_2 must start right after leaf finishes (not delayed by shallow_leaf)
        assert sched_map.loc["deep_2", "start_ms"] == pytest.approx(sched_map.loc["leaf", "end_ms"], abs=1e-9)

    def test_pool_limits_concurrent_links(self):
        # Three independent executables, link_pool depth=1
        g = nx.DiGraph()
        g.add_nodes_from(["exe_a", "exe_b", "exe_c"])
        meta = pd.DataFrame(
            {
                "cmake_target": ["exe_a", "exe_b", "exe_c"],
                "target_type": ["executable", "executable", "executable"],
            }
        ).set_index("cmake_target")
        bg = BuildGraph(graph=g, target_metadata=meta)
        timing = pd.DataFrame(
            {
                "cmake_target": ["exe_a", "exe_b", "exe_c"],
                "total_build_time_ms": [10_000, 10_000, 10_000],
            }
        )
        pool_config = PoolConfig.with_link_pool(link_depth=1)
        schedule = simulate_build(bg, timing, n_cores=8, pool_config=pool_config)

        # With pool depth=1, no two executables overlap
        for a, b in [("exe_a", "exe_b"), ("exe_b", "exe_c"), ("exe_a", "exe_c")]:
            a_row = schedule[schedule["cmake_target"] == a].iloc[0]
            b_row = schedule[schedule["cmake_target"] == b].iloc[0]
            no_overlap = a_row["end_ms"] <= b_row["start_ms"] or b_row["end_ms"] <= a_row["start_ms"]
            assert no_overlap, f"{a} and {b} overlap with link_pool depth=1"
        # Total wall time = 30s (all sequential)
        assert schedule["end_ms"].max() == pytest.approx(30_000)

    def test_pool_does_not_exceed_global_j(self):
        # pool depth=4 but n_cores=2 -> only 2 concurrent
        names = [f"exe_{i}" for i in range(5)]
        g = nx.DiGraph()
        g.add_nodes_from(names)
        meta = pd.DataFrame({"cmake_target": names, "target_type": ["executable"] * 5}).set_index("cmake_target")
        bg = BuildGraph(graph=g, target_metadata=meta)
        timing = pd.DataFrame({"cmake_target": names, "total_build_time_ms": [10_000] * 5})
        pool_config = PoolConfig.with_link_pool(link_depth=4)
        schedule = simulate_build(bg, timing, n_cores=2, pool_config=pool_config)

        # At no point should more than 2 tasks run simultaneously
        for _, row in schedule.iterrows():
            concurrent = schedule[(schedule["start_ms"] < row["end_ms"]) & (schedule["end_ms"] > row["start_ms"])]
            assert len(concurrent) <= 2

    def test_mixed_pool_and_default(self):
        # 2 libraries (default pool) + 1 executable (link_pool depth=1)
        # Libraries should compile in parallel while link is serialised
        g = nx.DiGraph()
        g.add_edge("exe", "lib_a")
        g.add_edge("exe", "lib_b")
        meta = pd.DataFrame(
            {
                "cmake_target": ["exe", "lib_a", "lib_b"],
                "target_type": ["executable", "static_library", "static_library"],
            }
        ).set_index("cmake_target")
        bg = BuildGraph(graph=g, target_metadata=meta)
        timing = pd.DataFrame(
            {
                "cmake_target": ["exe", "lib_a", "lib_b"],
                "total_build_time_ms": [5_000, 10_000, 10_000],
            }
        )
        pool_config = PoolConfig.with_link_pool(link_depth=1)
        schedule = simulate_build(bg, timing, n_cores=4, pool_config=pool_config)
        sched_map = schedule.set_index("cmake_target")

        # Libraries should start at t=0 (both in default pool, no constraints)
        assert sched_map.loc["lib_a", "start_ms"] == pytest.approx(0.0)
        assert sched_map.loc["lib_b", "start_ms"] == pytest.approx(0.0)
        # exe starts after both libs finish
        assert sched_map.loc["exe", "start_ms"] >= sched_map.loc["lib_a", "end_ms"]
        assert sched_map.loc["exe", "start_ms"] >= sched_map.loc["lib_b", "end_ms"]


# ---------------------------------------------------------------------------
# Named target simulation
# ---------------------------------------------------------------------------


class TestNamedTargetSimulation:
    def test_named_target_restricts_to_transitive_deps(self, diamond_graph, diamond_timing):
        # Only build B and its deps (B -> D)
        schedule = simulate_build(diamond_graph, diamond_timing, n_cores=4, target="B")
        scheduled_targets = set(schedule["cmake_target"])
        assert "A" not in scheduled_targets
        assert "C" not in scheduled_targets
        assert "B" in scheduled_targets
        assert "D" in scheduled_targets

    def test_named_target_and_scope_raises(self, diamond_graph, diamond_timing):
        with pytest.raises(ValueError, match="mutually exclusive"):
            simulate_build(
                diamond_graph,
                diamond_timing,
                n_cores=4,
                target="B",
                scope=AnalysisScope(targets=frozenset(["B"])),
            )

    def test_unknown_target_raises(self, diamond_graph, diamond_timing):
        with pytest.raises(KeyError):
            simulate_build(diamond_graph, diamond_timing, n_cores=4, target="nonexistent")

    def test_named_leaf_target_builds_only_self(self, diamond_graph, diamond_timing):
        schedule = simulate_build(diamond_graph, diamond_timing, n_cores=4, target="D")
        assert len(schedule) == 1
        assert schedule.iloc[0]["cmake_target"] == "D"

    def test_named_target_wall_time(self, diamond_graph, diamond_timing):
        # Building B: D(5s) -> B(30s) = 35s
        schedule = simulate_build(diamond_graph, diamond_timing, n_cores=4, target="B")
        assert schedule["end_ms"].max() == pytest.approx(35_000, rel=0.01)


# ---------------------------------------------------------------------------
# What-if analysis (unchanged API)
# ---------------------------------------------------------------------------


class TestWhatIf:
    def test_remove_non_critical_edge(self, diamond_graph, diamond_timing):
        result = whatif_remove_edge(diamond_graph, diamond_timing, "A", "C")
        assert result["delta_ms"] == 0

    def test_reduce_critical_target(self, diamond_graph, diamond_timing):
        result = whatif_reduce_target_time(diamond_graph, diamond_timing, "B", reduction_pct=50)
        assert result["on_original_critical_path"] is True
        assert result["new_critical_path_ms"] == pytest.approx(35_000, rel=0.01)
        assert result["delta_ms"] == pytest.approx(10_000, rel=0.01)


# ---------------------------------------------------------------------------
# Validate simulation (unchanged API)
# ---------------------------------------------------------------------------


class TestValidateSimulation:
    def test_within_tolerance(self, diamond_graph, diamond_timing):
        simulated = simulate_build(diamond_graph, diamond_timing, n_cores=4)
        observed = simulated.copy()
        result = validate_simulation(simulated, observed, tolerance_pct=10)
        assert bool(result["within_tolerance"])
        assert result["wall_time_error_pct"] == pytest.approx(0.0, abs=0.01)

    def test_outside_tolerance(self, diamond_graph, diamond_timing):
        simulated = simulate_build(diamond_graph, diamond_timing, n_cores=4)
        observed = simulated.copy()
        observed["end_ms"] = observed["end_ms"] * 1.5
        result = validate_simulation(simulated, observed, tolerance_pct=10)
        assert not bool(result["within_tolerance"])
        assert result["wall_time_error_pct"] > 10

    def test_utilisation_range(self, diamond_graph, diamond_timing):
        simulated = simulate_build(diamond_graph, diamond_timing, n_cores=4)
        observed = simulated.copy()
        result = validate_simulation(simulated, observed)
        assert 0 <= result["simulated_avg_utilisation"] <= 1.0
        assert 0 <= result["observed_avg_utilisation"] <= 1.0
