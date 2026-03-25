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
        "compiler": {
            "cc":      "/usr/local/bin/gcc-12",
            "cxx":     "/usr/local/bin/g++-12",
            "ar":      "/usr/local/bin/ar",
            "ranlib":  "/usr/local/bin/ranlib",
            "nm":      "/usr/local/bin/nm",
            "objdump": "/usr/local/bin/objdump",
            "strip":   "/usr/local/bin/strip",
            "linker":  "/usr/local/bin/ld",
        },
        "environment": {
            "path_prefix": [
                "/usr/local/bin",
                "/opt/extra/bin",
            ],
            "env": {
                "LD_LIBRARY_PATH": "/usr/local/lib64:/usr/local/lib",
            },
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
        assert cfg["compiler"]["cc"] == "/usr/local/bin/gcc-12"
        assert cfg["git_history_months"] == 12

    def test_preserves_absolute_paths(self, sample_config):
        config_path, _ = sample_config
        cfg = load_config(config_path)
        # build_dir was already absolute in the fixture
        assert Path(cfg["build_dir"]).is_absolute()


class TestRenderToolchain:
    def test_substitutes_compiler_paths(self, sample_config, tmp_path, monkeypatch):
        config_path, _ = sample_config
        cfg = load_config(config_path)

        import build_optimiser.config as config_mod
        monkeypatch.setattr(config_mod, "_PROJECT_ROOT", tmp_path)

        template = tmp_path / "toolchain.cmake"
        template.write_text(
            'set(CMAKE_C_COMPILER   "@CC@")\n'
            'set(CMAKE_CXX_COMPILER "@CXX@")\n'
            'set(CMAKE_AR           "@AR@")\n'
        )

        output = render_toolchain(cfg)
        content = output.read_text()
        assert "/usr/local/bin/gcc-12" in content
        assert "/usr/local/bin/g++-12" in content
        assert "/usr/local/bin/ar" in content
        assert "@CC@" not in content
        assert "@CXX@" not in content
        assert "@AR@" not in content


class TestBuildEnvironment:
    def test_prepends_path_prefix(self, sample_config):
        config_path, _ = sample_config
        cfg = load_config(config_path)
        env = build_environment(cfg)
        assert env["PATH"].startswith("/usr/local/bin:/opt/extra/bin:")

    def test_sets_ld_library_path(self, sample_config):
        config_path, _ = sample_config
        cfg = load_config(config_path)
        env = build_environment(cfg)
        assert "/usr/local/lib64" in env["LD_LIBRARY_PATH"]
        assert "/usr/local/lib" in env["LD_LIBRARY_PATH"]

    def test_preserves_existing_path(self, sample_config, monkeypatch):
        config_path, _ = sample_config
        cfg = load_config(config_path)
        monkeypatch.setenv("PATH", "/usr/bin:/usr/sbin")
        env = build_environment(cfg)
        assert "/usr/bin" in env["PATH"]
        assert "/usr/sbin" in env["PATH"]

    def test_preserves_existing_ld_library_path(self, sample_config, monkeypatch):
        config_path, _ = sample_config
        cfg = load_config(config_path)
        monkeypatch.setenv("LD_LIBRARY_PATH", "/existing/lib")
        env = build_environment(cfg)
        assert "/existing/lib" in env["LD_LIBRARY_PATH"]

    def test_no_environment_section(self, sample_config):
        config_path, _ = sample_config
        cfg = load_config(config_path)
        del cfg["environment"]
        env = build_environment(cfg)
        # Should still work, just no modifications beyond os.environ
        assert "PATH" in env


class TestBuildCmakeCommand:
    def test_basic_command(self, sample_config, tmp_path, monkeypatch):
        config_path, _ = sample_config
        cfg = load_config(config_path)

        import build_optimiser.config as config_mod
        monkeypatch.setattr(config_mod, "_PROJECT_ROOT", tmp_path)
        template = tmp_path / "toolchain.cmake"
        template.write_text('set(CMAKE_C_COMPILER "@CC@")\n')

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
        template.write_text('set(CMAKE_C_COMPILER "@CC@")\n')

        cmd = build_cmake_command(cfg, pass_flags={"CMAKE_CXX_FLAGS": "-ftime-report"})
        assert "-DCMAKE_CXX_FLAGS=-ftime-report" in cmd

    def test_extra_args(self, sample_config, tmp_path, monkeypatch):
        config_path, _ = sample_config
        cfg = load_config(config_path)

        import build_optimiser.config as config_mod
        monkeypatch.setattr(config_mod, "_PROJECT_ROOT", tmp_path)
        template = tmp_path / "toolchain.cmake"
        template.write_text('set(CMAKE_C_COMPILER "@CC@")\n')

        cmd = build_cmake_command(cfg, extra_args=["--graphviz=/tmp/graph"])
        assert "--graphviz=/tmp/graph" in cmd

    def test_prefix_path(self, sample_config, tmp_path, monkeypatch):
        config_path, _ = sample_config
        cfg = load_config(config_path)

        import build_optimiser.config as config_mod
        monkeypatch.setattr(config_mod, "_PROJECT_ROOT", tmp_path)
        template = tmp_path / "toolchain.cmake"
        template.write_text('set(CMAKE_C_COMPILER "@CC@")\n')

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
