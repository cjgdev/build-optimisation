"""Tests for build_optimiser.config module."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from build_optimiser.config import (
    load_config,
    render_toolchain,
    build_cmake_command,
    build_ninja_command,
    build_environment,
)


@pytest.fixture
def sample_config(tmp_path):
    """Create a sample config.yaml for testing."""
    config = {
        "source_dir": "/tmp/source",
        "build_dir": str(tmp_path / "build"),
        "raw_data_dir": str(tmp_path / "raw"),
        "processed_data_dir": str(tmp_path / "processed"),
        "gcc_toolset": {
            "root": "/opt/rh/gcc-toolset-12/root",
            "ld_library_path": [
                "/opt/rh/gcc-toolset-12/root/usr/lib64",
                "/opt/rh/gcc-toolset-12/root/usr/lib",
            ],
        },
        "cmake_prefix_path": ["/opt/boost", "/opt/protobuf"],
        "cmake_cache_variables": {
            "CMAKE_EXE_LINKER_FLAGS": "-fuse-ld=mold",
            "CMAKE_SHARED_LINKER_FLAGS": "-fuse-ld=mold",
            "CMAKE_EXPORT_COMPILE_COMMANDS": "ON",
        },
        "git_history_months": 12,
        "ninja_jobs": 4,
    }
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)
    return config_path, config


class TestLoadConfig:
    def test_loads_yaml(self, sample_config):
        config_path, expected = sample_config
        cfg = load_config(config_path)
        assert cfg["source_dir"] == expected["source_dir"]
        assert cfg["gcc_toolset"]["root"] == "/opt/rh/gcc-toolset-12/root"
        assert cfg["git_history_months"] == 12

    def test_preserves_absolute_paths(self, sample_config):
        config_path, _ = sample_config
        cfg = load_config(config_path)
        # build_dir was already absolute in the fixture
        assert Path(cfg["build_dir"]).is_absolute()


class TestRenderToolchain:
    def test_substitutes_devtoolset_root(self, sample_config, tmp_path, monkeypatch):
        config_path, _ = sample_config
        cfg = load_config(config_path)

        # Create a toolchain template at the project root location
        import build_optimiser.config as config_mod
        monkeypatch.setattr(config_mod, "_PROJECT_ROOT", tmp_path)

        template = tmp_path / "toolchain.cmake"
        template.write_text(
            'set(DEVTOOLSET_ROOT "@GCC_TOOLSET_ROOT@")\n'
            'set(CMAKE_C_COMPILER "${DEVTOOLSET_ROOT}/usr/bin/gcc")\n'
            'set(CMAKE_CXX_COMPILER "${DEVTOOLSET_ROOT}/usr/bin/g++")\n'
        )

        output = render_toolchain(cfg)
        content = output.read_text()
        assert "/opt/rh/gcc-toolset-12/root" in content
        assert "@GCC_TOOLSET_ROOT@" not in content


class TestBuildEnvironment:
    def test_prepends_bin_dir_to_path(self, sample_config):
        config_path, _ = sample_config
        cfg = load_config(config_path)
        env = build_environment(cfg)
        assert env["PATH"].startswith("/opt/rh/gcc-toolset-12/root/usr/bin:")

    def test_sets_ld_library_path(self, sample_config):
        config_path, _ = sample_config
        cfg = load_config(config_path)
        env = build_environment(cfg)
        assert "/opt/rh/gcc-toolset-12/root/usr/lib64" in env["LD_LIBRARY_PATH"]
        assert "/opt/rh/gcc-toolset-12/root/usr/lib" in env["LD_LIBRARY_PATH"]

    def test_preserves_existing_path(self, sample_config, monkeypatch):
        config_path, _ = sample_config
        cfg = load_config(config_path)
        monkeypatch.setenv("PATH", "/usr/bin:/usr/local/bin")
        env = build_environment(cfg)
        assert "/usr/bin" in env["PATH"]
        assert "/usr/local/bin" in env["PATH"]

    def test_preserves_existing_ld_library_path(self, sample_config, monkeypatch):
        config_path, _ = sample_config
        cfg = load_config(config_path)
        monkeypatch.setenv("LD_LIBRARY_PATH", "/existing/lib")
        env = build_environment(cfg)
        assert "/existing/lib" in env["LD_LIBRARY_PATH"]


class TestBuildCmakeCommand:
    def test_basic_command(self, sample_config, tmp_path, monkeypatch):
        config_path, _ = sample_config
        cfg = load_config(config_path)

        import build_optimiser.config as config_mod
        monkeypatch.setattr(config_mod, "_PROJECT_ROOT", tmp_path)
        template = tmp_path / "toolchain.cmake"
        template.write_text('set(DEVTOOLSET_ROOT "@GCC_TOOLSET_ROOT@")\n')

        cmd = build_cmake_command(cfg)
        assert cmd[0] == "cmake"
        assert "-S" in cmd
        assert "-G" in cmd
        assert "Ninja" in cmd

    def test_pass_flags(self, sample_config, tmp_path, monkeypatch):
        config_path, _ = sample_config
        cfg = load_config(config_path)

        import build_optimiser.config as config_mod
        monkeypatch.setattr(config_mod, "_PROJECT_ROOT", tmp_path)
        template = tmp_path / "toolchain.cmake"
        template.write_text('set(DEVTOOLSET_ROOT "@GCC_TOOLSET_ROOT@")\n')

        cmd = build_cmake_command(cfg, pass_flags={"CMAKE_CXX_FLAGS": "-ftime-report"})
        assert "-DCMAKE_CXX_FLAGS=-ftime-report" in cmd

    def test_extra_args(self, sample_config, tmp_path, monkeypatch):
        config_path, _ = sample_config
        cfg = load_config(config_path)

        import build_optimiser.config as config_mod
        monkeypatch.setattr(config_mod, "_PROJECT_ROOT", tmp_path)
        template = tmp_path / "toolchain.cmake"
        template.write_text('set(DEVTOOLSET_ROOT "@GCC_TOOLSET_ROOT@")\n')

        cmd = build_cmake_command(cfg, extra_args=["--graphviz=/tmp/graph"])
        assert "--graphviz=/tmp/graph" in cmd

    def test_prefix_path(self, sample_config, tmp_path, monkeypatch):
        config_path, _ = sample_config
        cfg = load_config(config_path)

        import build_optimiser.config as config_mod
        monkeypatch.setattr(config_mod, "_PROJECT_ROOT", tmp_path)
        template = tmp_path / "toolchain.cmake"
        template.write_text('set(DEVTOOLSET_ROOT "@GCC_TOOLSET_ROOT@")\n')

        cmd = build_cmake_command(cfg)
        prefix_arg = [a for a in cmd if a.startswith("-DCMAKE_PREFIX_PATH=")]
        assert len(prefix_arg) == 1
        assert "/opt/boost" in prefix_arg[0]
        assert "/opt/protobuf" in prefix_arg[0]


class TestBuildNinjaCommand:
    def test_basic_command(self, sample_config):
        config_path, _ = sample_config
        cfg = load_config(config_path)
        cmd = build_ninja_command(cfg)
        assert cmd[0] == "ninja"
        assert "-C" in cmd

    def test_with_jobs(self, sample_config):
        config_path, _ = sample_config
        cfg = load_config(config_path)
        cmd = build_ninja_command(cfg)
        assert "-j" in cmd
        idx = cmd.index("-j")
        assert cmd[idx + 1] == "4"

    def test_with_target(self, sample_config):
        config_path, _ = sample_config
        cfg = load_config(config_path)
        cmd = build_ninja_command(cfg, target="my_lib")
        assert "my_lib" in cmd

    def test_zero_jobs(self, sample_config):
        config_path, _ = sample_config
        cfg = load_config(config_path)
        cfg["ninja_jobs"] = 0
        cmd = build_ninja_command(cfg)
        assert "-j" not in cmd
