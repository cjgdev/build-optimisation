"""Tests for configurable module structure (REQ-02)."""

import textwrap

import networkx as nx
import pandas as pd
import pytest

from buildanalysis.modules import (
    ModuleConfig,
    build_module_dependency_graph,
    build_module_feature_configs,
    compare_communities_to_modules,
    compute_module_metrics,
)
from buildanalysis.types import BuildGraph


@pytest.fixture
def sample_modules_yaml(tmp_path):
    content = textwrap.dedent("""
    modules:
      - name: "Base"
        description: "Foundation"
        category: "shared"
        directories:
          - "src/base"
          - "src/common"
        target_patterns:
          - "base_*"

      - name: "Accounting"
        description: "GL and reporting"
        category: "domain"
        owning_team: "Accounting"
        directories:
          - "src/accounting"
          - "src/gl"

      - name: "Trading"
        description: "Trade lifecycle"
        category: "domain"
        owning_team: "Trade Capture"
        directories:
          - "src/trade"

      - name: "Tests"
        description: "Test infra"
        category: "test"
        directories:
          - "tests/"
    """)
    path = tmp_path / "modules.yaml"
    path.write_text(content)
    return path


@pytest.fixture
def module_config(sample_modules_yaml):
    return ModuleConfig.from_yaml(sample_modules_yaml)


class TestModuleConfigLoading:
    def test_loads_modules(self, module_config):
        assert set(module_config.module_names) == {"Base", "Accounting", "Trading", "Tests"}

    def test_module_categories(self, module_config):
        base = module_config.get_module("Base")
        assert base.category == "shared"

    def test_domain_modules(self, module_config):
        domains = module_config.domain_modules
        assert len(domains) == 2
        assert {m.name for m in domains} == {"Accounting", "Trading"}

    def test_shared_modules(self, module_config):
        shared = module_config.shared_modules
        assert len(shared) == 1
        assert shared[0].name == "Base"

    def test_invalid_category_raises(self, tmp_path):
        content = textwrap.dedent("""
        modules:
          - name: "Bad"
            category: "invalid_category"
            directories: ["src/bad"]
        """)
        path = tmp_path / "bad.yaml"
        path.write_text(content)
        with pytest.raises(ValueError, match="[Cc]ategory"):
            ModuleConfig.from_yaml(path)

    def test_duplicate_module_name_raises(self, tmp_path):
        content = textwrap.dedent("""
        modules:
          - name: "Same"
            category: "shared"
            directories: ["src/a"]
          - name: "Same"
            category: "domain"
            directories: ["src/b"]
        """)
        path = tmp_path / "bad.yaml"
        path.write_text(content)
        with pytest.raises(ValueError, match="[Dd]uplicate"):
            ModuleConfig.from_yaml(path)

    def test_overlapping_directories_raises(self, tmp_path):
        content = textwrap.dedent("""
        modules:
          - name: "A"
            category: "shared"
            directories: ["src/common"]
          - name: "B"
            category: "domain"
            directories: ["src/common/sub"]
        """)
        path = tmp_path / "bad.yaml"
        path.write_text(content)
        with pytest.raises(ValueError, match="[Oo]verlap"):
            ModuleConfig.from_yaml(path)


class TestTargetAssignment:
    def test_directory_match(self, module_config):
        result = module_config.assign_target("some_lib", "src/accounting/ledger")
        assert result == "Accounting"

    def test_pattern_match(self, module_config):
        result = module_config.assign_target("base_utils", "src/unrelated")
        assert result == "Base"

    def test_pattern_takes_priority(self, module_config):
        """Target pattern match should take priority over directory match."""
        result = module_config.assign_target("base_accounting", "src/accounting")
        assert result == "Base"  # Pattern match wins

    def test_longest_prefix_match(self, module_config):
        result = module_config.assign_target("gl_lib", "src/gl/core")
        assert result == "Accounting"  # src/gl matches Accounting

    def test_no_match(self, module_config):
        result = module_config.assign_target("mystery_lib", "src/unknown/path")
        assert result is None

    def test_assign_all_targets(self, module_config):
        tm = pd.DataFrame(
            {
                "cmake_target": ["base_utils", "acc_lib", "trade_srv", "mystery"],
                "source_directory": ["src/base/utils", "src/accounting", "src/trade/server", "src/other"],
            }
        )
        result = module_config.assign_all_targets(tm)
        assert "module" in result.columns
        assert "module_category" in result.columns
        assert result.loc[result["cmake_target"] == "base_utils", "module"].iloc[0] == "Base"
        assert result.loc[result["cmake_target"] == "acc_lib", "module"].iloc[0] == "Accounting"
        assert result.loc[result["cmake_target"] == "trade_srv", "module"].iloc[0] == "Trading"
        assert pd.isna(result.loc[result["cmake_target"] == "mystery", "module"].iloc[0])


class TestModuleDependencyGraph:
    def test_basic_module_graph(self, module_config):
        g = nx.DiGraph()
        g.add_edges_from([("acc_lib", "base_utils"), ("trade_srv", "base_utils")])
        meta = pd.DataFrame(
            {
                "cmake_target": ["acc_lib", "trade_srv", "base_utils"],
                "target_type": ["static_library"] * 3,
                "source_directory": ["src/accounting", "src/trade", "src/base"],
            }
        ).set_index("cmake_target")
        bg = BuildGraph(graph=g, target_metadata=meta)

        assignments = module_config.assign_all_targets(meta.reset_index())
        mod_graph = build_module_dependency_graph(bg, assignments)

        assert mod_graph.has_node("Accounting")
        assert mod_graph.has_node("Trading")
        assert mod_graph.has_node("Base")
        assert mod_graph.has_edge("Accounting", "Base")
        assert mod_graph.has_edge("Trading", "Base")
        # No direct cross-domain edge
        assert not mod_graph.has_edge("Accounting", "Trading")

    def test_cross_category_flag(self, module_config):
        g = nx.DiGraph()
        g.add_edges_from([("acc_lib", "trade_srv")])
        meta = pd.DataFrame(
            {
                "cmake_target": ["acc_lib", "trade_srv"],
                "target_type": ["static_library"] * 2,
                "source_directory": ["src/accounting", "src/trade"],
            }
        ).set_index("cmake_target")
        bg = BuildGraph(graph=g, target_metadata=meta)

        assignments = module_config.assign_all_targets(meta.reset_index())
        mod_graph = build_module_dependency_graph(bg, assignments)

        edge_data = mod_graph.edges["Accounting", "Trading"]
        assert edge_data["is_cross_category"] is True  # domain → domain


class TestModuleMetrics:
    def test_self_containment(self, module_config):
        # Two targets in Accounting depend on each other, one depends on Base
        g = nx.DiGraph()
        g.add_edges_from(
            [
                ("acc_a", "acc_b"),  # Internal
                ("acc_a", "base_utils"),  # External
            ]
        )
        meta = pd.DataFrame(
            {
                "cmake_target": ["acc_a", "acc_b", "base_utils"],
                "target_type": ["static_library"] * 3,
                "source_directory": ["src/accounting", "src/accounting", "src/base"],
            }
        ).set_index("cmake_target")
        bg = BuildGraph(graph=g, target_metadata=meta)

        tm = pd.DataFrame(
            {
                "cmake_target": ["acc_a", "acc_b", "base_utils"],
                "source_directory": ["src/accounting", "src/accounting", "src/base"],
                "total_build_time_ms": [1000, 2000, 3000],
                "code_lines_total": [100, 200, 300],
                "file_count": [5, 10, 15],
                "compile_time_sum_ms": [800, 1600, 2400],
                "link_time_ms": [200, 400, 600],
                "codegen_ratio": [0.0, 0.0, 0.0],
                "target_type": ["static_library"] * 3,
            }
        )

        assignments = module_config.assign_all_targets(tm)
        result = compute_module_metrics(bg, assignments, tm)

        acc_row = result[result["module"] == "Accounting"].iloc[0]
        assert acc_row["target_count"] == 2
        assert acc_row["internal_dep_count"] == 1  # acc_a → acc_b
        assert acc_row["external_dep_count"] == 1  # acc_a → base_utils
        assert acc_row["self_containment"] == pytest.approx(0.5)

    def test_critical_path_target_count(self, module_config):
        g = nx.DiGraph()
        g.add_edges_from([("acc_a", "acc_b"), ("acc_a", "base_utils")])
        meta = pd.DataFrame(
            {
                "cmake_target": ["acc_a", "acc_b", "base_utils"],
                "target_type": ["static_library"] * 3,
                "source_directory": ["src/accounting", "src/accounting", "src/base"],
            }
        ).set_index("cmake_target")
        bg = BuildGraph(graph=g, target_metadata=meta)
        tm = pd.DataFrame(
            {
                "cmake_target": ["acc_a", "acc_b", "base_utils"],
                "source_directory": ["src/accounting", "src/accounting", "src/base"],
                "total_build_time_ms": [1000, 2000, 3000],
                "code_lines_total": [100, 200, 300],
                "file_count": [5, 10, 15],
                "compile_time_sum_ms": [800, 1600, 2400],
                "link_time_ms": [200, 400, 600],
                "codegen_ratio": [0.0, 0.0, 0.0],
                "target_type": ["static_library"] * 3,
            }
        )
        assignments = module_config.assign_all_targets(tm)
        result = compute_module_metrics(bg, assignments, tm, critical_path_targets={"acc_a"})
        acc_row = result[result["module"] == "Accounting"].iloc[0]
        assert acc_row["critical_path_target_count"] == 1

    def test_build_fraction(self, module_config):
        g = nx.DiGraph()
        g.add_edges_from([("acc_a", "acc_b"), ("acc_a", "base_utils")])
        meta = pd.DataFrame(
            {
                "cmake_target": ["acc_a", "acc_b", "base_utils"],
                "target_type": ["static_library"] * 3,
                "source_directory": ["src/accounting", "src/accounting", "src/base"],
            }
        ).set_index("cmake_target")
        bg = BuildGraph(graph=g, target_metadata=meta)
        tm = pd.DataFrame(
            {
                "cmake_target": ["acc_a", "acc_b", "base_utils"],
                "source_directory": ["src/accounting", "src/accounting", "src/base"],
                "total_build_time_ms": [1000, 2000, 3000],
                "code_lines_total": [100, 200, 300],
                "file_count": [5, 10, 15],
                "compile_time_sum_ms": [800, 1600, 2400],
                "link_time_ms": [200, 400, 600],
                "codegen_ratio": [0.0, 0.0, 0.0],
                "target_type": ["static_library"] * 3,
            }
        )
        assignments = module_config.assign_all_targets(tm)
        result = compute_module_metrics(bg, assignments, tm, total_targets=3)
        acc_row = result[result["module"] == "Accounting"].iloc[0]
        assert acc_row["build_fraction"] == pytest.approx(2 / 3)

    def test_placeholders_when_no_optional_args(self, module_config):
        g = nx.DiGraph()
        g.add_edges_from([("acc_a", "acc_b"), ("acc_a", "base_utils")])
        meta = pd.DataFrame(
            {
                "cmake_target": ["acc_a", "acc_b", "base_utils"],
                "target_type": ["static_library"] * 3,
                "source_directory": ["src/accounting", "src/accounting", "src/base"],
            }
        ).set_index("cmake_target")
        bg = BuildGraph(graph=g, target_metadata=meta)
        tm = pd.DataFrame(
            {
                "cmake_target": ["acc_a", "acc_b", "base_utils"],
                "source_directory": ["src/accounting", "src/accounting", "src/base"],
                "total_build_time_ms": [1000, 2000, 3000],
                "code_lines_total": [100, 200, 300],
                "file_count": [5, 10, 15],
                "compile_time_sum_ms": [800, 1600, 2400],
                "link_time_ms": [200, 400, 600],
                "codegen_ratio": [0.0, 0.0, 0.0],
                "target_type": ["static_library"] * 3,
            }
        )
        assignments = module_config.assign_all_targets(tm)
        result = compute_module_metrics(bg, assignments, tm)
        acc_row = result[result["module"] == "Accounting"].iloc[0]
        assert acc_row["critical_path_target_count"] == 0
        assert acc_row["build_fraction"] == pytest.approx(0.0)


class TestFeatureConfigs:
    def test_build_fraction(self, module_config):
        g = nx.DiGraph()
        g.add_edges_from([("acc_a", "base_utils")])
        meta = pd.DataFrame(
            {
                "cmake_target": ["acc_a", "base_utils"],
                "target_type": ["static_library"] * 2,
                "source_directory": ["src/accounting", "src/base"],
            }
        ).set_index("cmake_target")
        bg = BuildGraph(graph=g, target_metadata=meta)

        assignments = module_config.assign_all_targets(meta.reset_index())
        result = build_module_feature_configs(bg, assignments)

        acc_row = result[result["module"] == "Accounting"].iloc[0]
        assert acc_row["own_targets"] == 1
        assert acc_row["transitive_dep_targets"] == 1
        assert acc_row["total_build_set"] == 2
        assert acc_row["build_fraction"] == 1.0  # 2/2 targets


class TestCompareCommunities:
    def test_identical_mapping(self):
        communities = pd.DataFrame(
            {
                "cmake_target": ["a", "b", "c"],
                "community": [0, 0, 1],
            }
        )
        modules = pd.DataFrame(
            {
                "cmake_target": ["a", "b", "c"],
                "module": ["Base", "Base", "Trading"],
            }
        )
        result = compare_communities_to_modules(communities, modules)
        assert result["adjusted_rand_index"] == pytest.approx(1.0)
        assert result["normalized_mutual_info"] == pytest.approx(1.0)
        assert result["n_targets_compared"] == 3

    def test_empty_overlap(self):
        communities = pd.DataFrame({"cmake_target": ["a"], "community": [0]})
        modules = pd.DataFrame({"cmake_target": ["b"], "module": ["X"]})
        result = compare_communities_to_modules(communities, modules)
        assert result["n_targets_compared"] == 0
        assert result["adjusted_rand_index"] == 0.0

    def test_fragmented_modules_detected(self):
        communities = pd.DataFrame(
            {
                "cmake_target": ["a", "b", "c", "d"],
                "community": [0, 1, 2, 3],  # all separate
            }
        )
        modules = pd.DataFrame(
            {
                "cmake_target": ["a", "b", "c", "d"],
                "module": ["Base", "Base", "Base", "Base"],  # all in one module
            }
        )
        result = compare_communities_to_modules(communities, modules)
        assert "Base" in result["fragmented_modules"]
