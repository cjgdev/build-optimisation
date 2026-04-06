"""Tests for buildanalysis.config."""

import os
from pathlib import Path

import pytest
import yaml

from buildanalysis.config import Config, ConfigError


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
    tmpl.write_text('set(CMAKE_C_COMPILER   "@CC@")\nset(CMAKE_CXX_COMPILER "@CXX@")\n@BINUTILS_LINES@\n')
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
        config_path.write_text(
            yaml.dump(
                {
                    "source_dir": "/tmp/src",
                    "cc": "/usr/bin/gcc",
                    "cxx": "/usr/bin/g++",
                    "ninja_jobs": 0,
                }
            )
        )
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
        config_path.write_text(
            yaml.dump(
                {
                    "source_dir": "/tmp/src",
                    "cc": "/usr/bin/gcc",
                    "cxx": "/usr/bin/g++",
                    "preprocess_workers": 0,
                }
            )
        )
        cfg = Config.from_yaml(config_path)
        assert cfg.preprocess_workers >= 1


def _minimal_config(**overrides: object) -> dict[str, object]:
    """Return a minimal valid config dict, with optional overrides merged in."""
    base: dict[str, object] = {"source_dir": "/tmp/src", "cc": "/usr/bin/gcc", "cxx": "/usr/bin/g++"}
    base.update(overrides)
    return base


class TestBinutilsRendering:
    def test_all_binutils_rendered(self, tmp_path: Path, toolchain_template: Path):
        all_binutils = {
            "ar": "/usr/bin/ar",
            "ranlib": "/usr/bin/ranlib",
            "nm": "/usr/bin/nm",
            "strip": "/usr/bin/strip",
            "objdump": "/usr/bin/objdump",
            "objcopy": "/usr/bin/objcopy",
            "readelf": "/usr/bin/readelf",
            "ld": "/usr/bin/ld",
        }
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(_minimal_config(binutils=all_binutils)))
        cfg = Config.from_yaml(config_path)
        output = tmp_path / "rendered.cmake"
        cfg.render_toolchain(output, template_path=toolchain_template)
        content = output.read_text()
        assert 'set(CMAKE_AR "/usr/bin/ar")' in content
        assert 'set(CMAKE_RANLIB "/usr/bin/ranlib")' in content
        assert 'set(CMAKE_NM "/usr/bin/nm")' in content
        assert 'set(CMAKE_STRIP "/usr/bin/strip")' in content
        assert 'set(CMAKE_OBJDUMP "/usr/bin/objdump")' in content
        assert 'set(CMAKE_OBJCOPY "/usr/bin/objcopy")' in content
        assert 'set(CMAKE_READELF "/usr/bin/readelf")' in content
        assert 'set(CMAKE_LINKER "/usr/bin/ld")' in content

    def test_partial_binutils_renders_only_specified(self, tmp_path: Path, toolchain_template: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(_minimal_config(binutils={"ar": "/opt/bin/ar", "strip": "/opt/bin/strip"})))
        cfg = Config.from_yaml(config_path)
        output = tmp_path / "rendered.cmake"
        cfg.render_toolchain(output, template_path=toolchain_template)
        content = output.read_text()
        assert 'set(CMAKE_AR "/opt/bin/ar")' in content
        assert 'set(CMAKE_STRIP "/opt/bin/strip")' in content
        assert "CMAKE_RANLIB" not in content
        assert "CMAKE_NM" not in content
        assert "CMAKE_LINKER" not in content

    def test_no_binutils_key_omits_lines(self, tmp_path: Path, toolchain_template: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(_minimal_config()))
        cfg = Config.from_yaml(config_path)
        output = tmp_path / "rendered.cmake"
        cfg.render_toolchain(output, template_path=toolchain_template)
        content = output.read_text()
        assert "CMAKE_AR" not in content
        assert "CMAKE_LINKER" not in content

    def test_empty_binutils_dict_omits_lines(self, tmp_path: Path, toolchain_template: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(_minimal_config(binutils={})))
        cfg = Config.from_yaml(config_path)
        output = tmp_path / "rendered.cmake"
        cfg.render_toolchain(output, template_path=toolchain_template)
        content = output.read_text()
        assert "CMAKE_AR" not in content

    def test_binutils_property(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(_minimal_config(binutils={"ar": "/usr/bin/ar"})))
        cfg = Config.from_yaml(config_path)
        assert cfg.binutils == {"ar": "/usr/bin/ar"}

    def test_binutils_absent_returns_empty_dict(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(_minimal_config()))
        cfg = Config.from_yaml(config_path)
        assert cfg.binutils == {}


class TestCMakeBinary:
    def test_custom_cmake_binary_in_command(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(_minimal_config(cmake="/opt/cmake/bin/cmake")))
        cfg = Config.from_yaml(config_path)
        cmd = cfg.cmake_configure_command()
        assert cmd[0] == "/opt/cmake/bin/cmake"

    def test_default_cmake_binary_when_absent(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(_minimal_config()))
        cfg = Config.from_yaml(config_path)
        cmd = cfg.cmake_configure_command()
        assert cmd[0] == "cmake"

    def test_cmake_binary_property(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(_minimal_config(cmake="/opt/cmake/bin/cmake")))
        cfg = Config.from_yaml(config_path)
        assert cfg.cmake_binary == "/opt/cmake/bin/cmake"

    def test_cmake_binary_default(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(_minimal_config()))
        cfg = Config.from_yaml(config_path)
        assert cfg.cmake_binary == "cmake"


class TestCMakeEnv:
    def test_path_string_prepended_to_existing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PATH", "/system/bin")
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(_minimal_config(env={"PATH": "/opt/a:/opt/b"})))
        cfg = Config.from_yaml(config_path)
        env = cfg.cmake_env()
        assert env["PATH"].startswith(f"/opt/a:/opt/b{os.pathsep}")
        assert env["PATH"].endswith("/system/bin")

    def test_path_list_prepended_to_existing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PATH", "/system/bin")
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(_minimal_config(env={"PATH": ["/opt/a", "/opt/b"]})))
        cfg = Config.from_yaml(config_path)
        env = cfg.cmake_env()
        assert env["PATH"].startswith(f"/opt/a{os.pathsep}/opt/b{os.pathsep}")
        assert env["PATH"].endswith("/system/bin")

    def test_non_path_var_overrides(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(_minimal_config(env={"AWS_REGION": "eu-west-2"})))
        cfg = Config.from_yaml(config_path)
        env = cfg.cmake_env()
        assert env["AWS_REGION"] == "eu-west-2"

    def test_non_path_var_sets_new(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(_minimal_config(env={"MY_CUSTOM_VAR": "hello"})))
        cfg = Config.from_yaml(config_path)
        env = cfg.cmake_env()
        assert env["MY_CUSTOM_VAR"] == "hello"

    def test_empty_env_unchanged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PATH", "/system/bin")
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(_minimal_config(env={})))
        cfg = Config.from_yaml(config_path)
        env = cfg.cmake_env()
        assert env["PATH"] == "/system/bin"

    def test_absent_env_unchanged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PATH", "/system/bin")
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(_minimal_config()))
        cfg = Config.from_yaml(config_path)
        env = cfg.cmake_env()
        assert env["PATH"] == "/system/bin"

    def test_returns_copy_not_original(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(_minimal_config(env={"FOO": "bar"})))
        cfg = Config.from_yaml(config_path)
        env = cfg.cmake_env()
        env["MUTATED"] = "yes"
        assert "MUTATED" not in os.environ

    def test_env_property(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(_minimal_config(env={"AWS_REGION": "eu-west-2", "PATH": "/opt/bin"})))
        cfg = Config.from_yaml(config_path)
        assert cfg.env == {"AWS_REGION": "eu-west-2", "PATH": "/opt/bin"}

    def test_env_absent_returns_empty_dict(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(_minimal_config()))
        cfg = Config.from_yaml(config_path)
        assert cfg.env == {}

    def test_mixed_path_and_overrides(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PATH", "/system/bin")
        monkeypatch.setenv("OLD_VAR", "old")
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.dump(_minimal_config(env={"PATH": "/opt/tools", "AWS_REGION": "eu-west-2", "OLD_VAR": "new"}))
        )
        cfg = Config.from_yaml(config_path)
        env = cfg.cmake_env()
        assert env["PATH"].startswith(f"/opt/tools{os.pathsep}")
        assert env["AWS_REGION"] == "eu-west-2"
        assert env["OLD_VAR"] == "new"
