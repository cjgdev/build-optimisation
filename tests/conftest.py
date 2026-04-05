"""Shared pytest fixtures and markers."""

from pathlib import Path

import networkx as nx
import pandas as pd
import pytest

from buildanalysis.graph import build_dependency_graph
from buildanalysis.types import BuildGraph


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: marks tests requiring CMake, GCC, and Ninja")


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixture"


@pytest.fixture
def config_template(fixture_dir: Path, tmp_path: Path) -> dict:
    """Return a valid config dict pointing at the fixture project."""
    return {
        "source_dir": str(fixture_dir),
        "build_dir": str(tmp_path / "build"),
        "raw_data_dir": str(tmp_path / "raw"),
        "processed_data_dir": str(tmp_path / "processed"),
        "cc": "/usr/bin/gcc",
        "cxx": "/usr/bin/g++",
        "cmake_prefix_path": [],
        "cmake_cache_variables": {
            "CMAKE_EXPORT_COMPILE_COMMANDS": "ON",
        },
        "cmake_file_api_client": "build-optimiser",
        "git_history_months": 12,
        "ninja_jobs": 0,
        "preprocess_workers": 0,
    }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_build_graph(edges: list[tuple[str, str]], target_types: dict[str, str]) -> BuildGraph:
    """Construct a BuildGraph from edges and type assignments."""
    g = nx.DiGraph()
    g.add_edges_from(edges)
    targets = list(g.nodes())
    meta = pd.DataFrame(
        {
            "cmake_target": targets,
            "target_type": [target_types.get(t, "static_library") for t in targets],
            "source_directory": [f"/src/{t.lower()}" for t in targets],
            "directory_depth": [2] * len(targets),
        }
    ).set_index("cmake_target")
    return BuildGraph(graph=g, target_metadata=meta)


# ---------------------------------------------------------------------------
# Diamond graph: A → B → D, A → C → D
# ---------------------------------------------------------------------------


@pytest.fixture
def diamond_targets() -> pd.DataFrame:
    """Target metrics DataFrame for diamond graph."""
    return pd.DataFrame(
        {
            "cmake_target": ["A", "B", "C", "D"],
            "target_type": ["executable", "static_library", "static_library", "static_library"],
        }
    )


@pytest.fixture
def diamond_edges() -> pd.DataFrame:
    """Edge list DataFrame for diamond graph."""
    return pd.DataFrame(
        {
            "source_target": ["A", "A", "B", "C"],
            "dest_target": ["B", "C", "D", "D"],
            "is_direct": [True, True, True, True],
            "dependency_type": ["link", "link", "link", "link"],
        }
    )


@pytest.fixture
def diamond_graph(diamond_targets, diamond_edges) -> BuildGraph:
    return build_dependency_graph(diamond_targets, diamond_edges)


@pytest.fixture
def diamond_timing() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "cmake_target": ["A", "B", "C", "D"],
            "total_build_time_ms": [10_000, 30_000, 20_000, 5_000],
        }
    )


# ---------------------------------------------------------------------------
# Chain graph: A → B → C → D → E
# ---------------------------------------------------------------------------


@pytest.fixture
def chain_targets() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "cmake_target": ["A", "B", "C", "D", "E"],
            "target_type": ["executable", "static_library", "static_library", "static_library", "static_library"],
        }
    )


@pytest.fixture
def chain_edges() -> pd.DataFrame:
    """A → B → C → D → E."""
    return pd.DataFrame(
        {
            "source_target": ["A", "B", "C", "D"],
            "dest_target": ["B", "C", "D", "E"],
            "is_direct": [True, True, True, True],
            "dependency_type": ["link", "link", "link", "link"],
        }
    )


@pytest.fixture
def chain_graph(chain_targets, chain_edges) -> BuildGraph:
    return build_dependency_graph(chain_targets, chain_edges)


@pytest.fixture
def chain_timing() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "cmake_target": list("ABCDE"),
            "total_build_time_ms": [10_000] * 5,
        }
    )


# ---------------------------------------------------------------------------
# Wide graph: root → leaf_0 .. leaf_19
# ---------------------------------------------------------------------------


@pytest.fixture
def wide_graph() -> BuildGraph:
    leaves = [f"leaf_{i}" for i in range(20)]
    edges = [("root", leaf) for leaf in leaves]
    return _make_build_graph(edges=edges, target_types={"root": "executable"})


@pytest.fixture
def wide_timing() -> pd.DataFrame:
    leaves = [f"leaf_{i}" for i in range(20)]
    targets = ["root"] + leaves
    times = [1_000] + [10_000] * 20
    return pd.DataFrame(
        {
            "cmake_target": targets,
            "total_build_time_ms": times,
        }
    )


# ---------------------------------------------------------------------------
# Two-community graph: two diamonds connected by a bridge
# ---------------------------------------------------------------------------


@pytest.fixture
def two_community_graph() -> BuildGraph:
    edges = [
        # Community 1 (diamond)
        ("A1", "B1"),
        ("A1", "C1"),
        ("B1", "D1"),
        ("C1", "D1"),
        # Community 2 (diamond)
        ("A2", "B2"),
        ("A2", "C2"),
        ("B2", "D2"),
        ("C2", "D2"),
        # Bridge
        ("A1", "D2"),
    ]
    return _make_build_graph(edges=edges, target_types={"A1": "executable", "A2": "executable"})


# ---------------------------------------------------------------------------
# Synthetic git log
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_git_log() -> pd.DataFrame:
    """Small git log for testing co-change analysis."""
    return pd.DataFrame(
        {
            "commit_hash": ["c1", "c1", "c2", "c2", "c2", "c3", "c3", "c4"],
            "timestamp": pd.to_datetime(
                [
                    "2024-01-01",
                    "2024-01-01",
                    "2024-01-02",
                    "2024-01-02",
                    "2024-01-02",
                    "2024-01-03",
                    "2024-01-03",
                    "2024-01-04",
                ]
            ),
            "contributor": ["alice", "alice", "bob", "bob", "bob", "alice", "alice", "carol"],
            "source_file": [
                "/src/a.cpp",
                "/src/b.cpp",
                "/src/a.cpp",
                "/src/b.cpp",
                "/src/c.cpp",
                "/src/a.cpp",
                "/src/b.cpp",
                "/src/d.cpp",
            ],
            "lines_added": [10, 5, 20, 8, 3, 15, 7, 50],
            "lines_deleted": [2, 1, 5, 2, 0, 3, 1, 10],
        }
    )


# ---------------------------------------------------------------------------
# Synthetic include graph
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_include_edges() -> pd.DataFrame:
    """Small include graph for testing header analysis."""
    return pd.DataFrame(
        {
            "includer": [
                "/src/main.cpp",
                "/src/main.cpp",
                "/src/foo.h",
                "/src/foo.h",
                "/src/bar.h",
                "/src/utils.cpp",
                "/src/utils.cpp",
            ],
            "included": [
                "/src/foo.h",
                "/src/bar.h",
                "/src/types.h",
                "/src/utils.h",
                "/src/types.h",
                "/src/bar.h",
                "/src/types.h",
            ],
            "depth": [1, 1, 2, 2, 2, 1, 1],
            "source_file": [
                "/src/main.cpp",
                "/src/main.cpp",
                "/src/main.cpp",
                "/src/main.cpp",
                "/src/main.cpp",
                "/src/utils.cpp",
                "/src/utils.cpp",
            ],
            "is_system": [False] * 7,
        }
    )
