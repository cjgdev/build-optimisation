"""Shared pytest fixtures and markers."""

from pathlib import Path

import pytest


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
