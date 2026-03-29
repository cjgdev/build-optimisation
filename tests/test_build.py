import pytest

from buildanalysis.build import (
    compute_critical_path,
    simulate_build,
    whatif_reduce_target_time,
    whatif_remove_edge,
)


class TestCriticalPath:
    def test_diamond(self, diamond_graph, diamond_timing):
        result = compute_critical_path(diamond_graph, diamond_timing)
        # Critical path: D(5s) → B(30s) → A(10s) = 45s
        # (B is slower than C, so the path goes through B)
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
        # All sequential: 5 × 10s = 50s
        assert result.total_time_s == pytest.approx(50.0, rel=0.01)
        assert result.parallelism_ratio == pytest.approx(1.0, rel=0.01)
        # All targets on critical path
        assert result.target_slack["on_critical_path"].all()

    def test_wide_max_parallelism(self, wide_graph, wide_timing):
        result = compute_critical_path(wide_graph, wide_timing)
        # Critical path: any leaf(10s) + root(1s) = 11s
        assert result.total_time_s == pytest.approx(11.0, rel=0.01)
        # Total work: 20×10s + 1s = 201s
        assert result.total_work_s == pytest.approx(201.0, rel=0.01)
        # Parallelism ratio: 201/11 ≈ 18.27
        assert result.parallelism_ratio == pytest.approx(201.0 / 11.0, rel=0.01)


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
        # With enough cores, wall time ≈ critical path
        assert total == pytest.approx(cp.total_time_s * 1000, rel=0.01)

    def test_schedule_respects_dependencies(self, diamond_graph, diamond_timing):
        schedule = simulate_build(diamond_graph, diamond_timing, n_cores=4)
        sched_map = schedule.set_index("cmake_target")
        # A depends on B: A must start after B finishes
        assert sched_map.loc["A", "start_ms"] >= sched_map.loc["B", "end_ms"]
        # B depends on D: B must start after D finishes
        assert sched_map.loc["B", "start_ms"] >= sched_map.loc["D", "end_ms"]

    def test_all_targets_scheduled(self, diamond_graph, diamond_timing):
        schedule = simulate_build(diamond_graph, diamond_timing, n_cores=4)
        assert set(schedule["cmake_target"]) == set(diamond_graph.graph.nodes())


class TestWhatIf:
    def test_remove_non_critical_edge(self, diamond_graph, diamond_timing):
        # Removing A→C should not change critical path (C is not on it)
        result = whatif_remove_edge(diamond_graph, diamond_timing, "A", "C")
        assert result["delta_ms"] == 0  # No improvement

    def test_reduce_critical_target(self, diamond_graph, diamond_timing):
        # Reduce B (on critical path) by 50%
        result = whatif_reduce_target_time(
            diamond_graph, diamond_timing, "B", reduction_pct=50
        )
        assert result["on_original_critical_path"] is True
        # B goes from 30s to 15s. New critical path: D(5)+B(15)+A(10)=30s
        # But check if C path (5+20+10=35) becomes the new critical path
        assert result["new_critical_path_ms"] == pytest.approx(35_000, rel=0.01)
        assert result["delta_ms"] == pytest.approx(10_000, rel=0.01)
