"""Tests for build_optimiser.config."""

from pathlib import Path

import pytest
import yaml

from build_optimiser.config import Config, ConfigError


@pytest.fixture
def valid_config(tmp_path: Path) -> Path:
    """Write a minimal valid config.yaml and return its path."""
    cfg = {
        "source_dir": "/tmp/source",
        "cc": "/usr/bin/gcc-12",
        "cxx": "/usr/bin/g++-12",
        "build_dir": "./data/builds/main",
        "raw_data_dir": "./data/raw",
        "processed_data_dir": "./data/processed",
        "cmake_prefix_path": ["/opt/boost", "/opt/protobuf"],
        "cmake_cache_variables": {
            "CMAKE_EXE_LINKER_FLAGS": "-fuse-ld=mold",
            "CMAKE_EXPORT_COMPILE_COMMANDS": "ON",
        },
        "ninja_jobs": 8,
        "preprocess_workers": 4,
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(cfg))
    return config_path


@pytest.fixture
def toolchain_template(tmp_path: Path) -> Path:
    """Write a toolchain template and return its path."""
    tmpl = tmp_path / "toolchain.cmake"
    tmpl.write_text('set(CMAKE_C_COMPILER   "@CC@")\nset(CMAKE_CXX_COMPILER "@CXX@")\n')
    return tmpl


class TestConfigLoading:
    def test_loads_valid_config(self, valid_config: Path):
        cfg = Config.from_yaml(valid_config)
        assert cfg.cc == "/usr/bin/gcc-12"
        assert cfg.cxx == "/usr/bin/g++-12"
        assert cfg.source_dir == Path("/tmp/source").resolve()

    def test_missing_required_keys_raises(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"source_dir": "/tmp/src"}))
        with pytest.raises(ConfigError, match="cc"):
            Config.from_yaml(config_path)

    def test_missing_source_dir_raises(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"cc": "/usr/bin/gcc", "cxx": "/usr/bin/g++"}))
        with pytest.raises(ConfigError, match="source_dir"):
            Config.from_yaml(config_path)

    def test_empty_config_raises(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("")
        with pytest.raises(ConfigError):
            Config.from_yaml(config_path)


class TestPathResolution:
    def test_relative_build_dir_resolved_from_config_dir(self, valid_config: Path):
        cfg = Config.from_yaml(valid_config)
        assert cfg.build_dir.is_absolute()
        assert str(cfg.build_dir).startswith(str(valid_config.parent.resolve()))

    def test_absolute_source_dir_unchanged(self, valid_config: Path):
        cfg = Config.from_yaml(valid_config)
        assert cfg.source_dir == Path("/tmp/source").resolve()


class TestToolchainRendering:
    def test_substitutes_compiler_paths(self, valid_config: Path, toolchain_template: Path, tmp_path: Path):
        cfg = Config.from_yaml(valid_config)
        output = tmp_path / "rendered_toolchain.cmake"
        cfg.render_toolchain(output, template_path=toolchain_template)
        content = output.read_text()
        assert "/usr/bin/gcc-12" in content
        assert "/usr/bin/g++-12" in content
        assert "@CC@" not in content
        assert "@CXX@" not in content


class TestCMakeCommand:
    def test_includes_prefix_path_semicolon_joined(self, valid_config: Path):
        cfg = Config.from_yaml(valid_config)
        cmd = cfg.cmake_configure_command()
        joined = [arg for arg in cmd if "CMAKE_PREFIX_PATH" in arg]
        assert len(joined) == 1
        assert "/opt/boost;/opt/protobuf" in joined[0]

    def test_includes_cache_variables(self, valid_config: Path):
        cfg = Config.from_yaml(valid_config)
        cmd = cfg.cmake_configure_command()
        cmd_str = " ".join(cmd)
        assert "-DCMAKE_EXE_LINKER_FLAGS=-fuse-ld=mold" in cmd_str
        assert "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON" in cmd_str

    def test_extra_cache_vars_override(self, valid_config: Path):
        cfg = Config.from_yaml(valid_config)
        cmd = cfg.cmake_configure_command(extra_cache_vars={"CMAKE_EXPORT_COMPILE_COMMANDS": "OFF"})
        # The extra var should win
        assert "-DCMAKE_EXPORT_COMPILE_COMMANDS=OFF" in cmd

    def test_compiler_launcher_injected(self, valid_config: Path):
        cfg = Config.from_yaml(valid_config)
        cmd = cfg.cmake_configure_command(capture_stderr_script=Path("/opt/wrapper.sh"))
        assert "-DCMAKE_CXX_COMPILER_LAUNCHER=/opt/wrapper.sh" in cmd

    def test_generator_is_ninja(self, valid_config: Path):
        cfg = Config.from_yaml(valid_config)
        cmd = cfg.cmake_configure_command()
        idx = cmd.index("-G")
        assert cmd[idx + 1] == "Ninja"


class TestNinjaCommand:
    def test_with_jobs(self, valid_config: Path):
        cfg = Config.from_yaml(valid_config)
        cmd = cfg.ninja_command()
        assert "-j" in cmd
        assert "8" in cmd

    def test_without_jobs(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "source_dir": "/tmp/src",
            "cc": "/usr/bin/gcc",
            "cxx": "/usr/bin/g++",
            "ninja_jobs": 0,
        }))
        cfg = Config.from_yaml(config_path)
        cmd = cfg.ninja_command()
        assert "-j" not in cmd

    def test_with_targets(self, valid_config: Path):
        cfg = Config.from_yaml(valid_config)
        cmd = cfg.ninja_command(targets=["clean"])
        assert "clean" in cmd


class TestPreprocessWorkers:
    def test_explicit_value(self, valid_config: Path):
        cfg = Config.from_yaml(valid_config)
        assert cfg.preprocess_workers == 4

    def test_zero_uses_cpu_count(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "source_dir": "/tmp/src",
            "cc": "/usr/bin/gcc",
            "cxx": "/usr/bin/g++",
            "preprocess_workers": 0,
        }))
        cfg = Config.from_yaml(config_path)
        assert cfg.preprocess_workers >= 1
