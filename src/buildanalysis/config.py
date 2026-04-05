"""Configuration loading, toolchain rendering, and command building."""

from __future__ import annotations

import os
import string
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when config.yaml is missing required fields or has invalid values."""


class Config:
    """Central configuration object loaded from config.yaml.

    All relative paths are resolved relative to the config file's parent directory.
    """

    REQUIRED_KEYS = ("source_dir", "cc", "cxx")

    def __init__(self, data: dict[str, Any], config_dir: Path) -> None:
        self._data = data
        self._config_dir = config_dir.resolve()
        self._validate()

    @classmethod
    def from_yaml(cls, path: str | Path) -> Config:
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls(data, path.parent)

    def _validate(self) -> None:
        missing = [k for k in self.REQUIRED_KEYS if not self._data.get(k)]
        if missing:
            raise ConfigError(f"Missing required config keys: {', '.join(missing)}")

    def _resolve_path(self, value: str | None) -> Path | None:
        if value is None:
            return None
        p = Path(value)
        if not p.is_absolute():
            p = self._config_dir / p
        return p.resolve()

    @property
    def source_dir(self) -> Path:
        return self._resolve_path(self._data["source_dir"])  # type: ignore[return-value]

    @property
    def build_dir(self) -> Path:
        return self._resolve_path(self._data.get("build_dir", "./data/builds/main"))  # type: ignore[return-value]

    @property
    def raw_data_dir(self) -> Path:
        return self._resolve_path(self._data.get("raw_data_dir", "./data/raw"))  # type: ignore[return-value]

    @property
    def processed_data_dir(self) -> Path:
        return self._resolve_path(self._data.get("processed_data_dir", "./data/processed"))  # type: ignore[return-value]

    @property
    def cc(self) -> str:
        return self._data["cc"]

    @property
    def cxx(self) -> str:
        return self._data["cxx"]

    @property
    def cmake_prefix_path(self) -> list[str]:
        return self._data.get("cmake_prefix_path") or []

    @property
    def cmake_cache_variables(self) -> dict[str, str]:
        return self._data.get("cmake_cache_variables") or {}

    @property
    def cmake_file_api_client(self) -> str:
        return self._data.get("cmake_file_api_client", "build-optimiser")

    @property
    def git_history_months(self) -> int:
        return int(self._data.get("git_history_months", 12))

    @property
    def ninja_jobs(self) -> int:
        return int(self._data.get("ninja_jobs", 0))

    @property
    def preprocess_workers(self) -> int:
        val = int(self._data.get("preprocess_workers", 0))
        return val if val > 0 else os.cpu_count() or 1

    def render_toolchain(self, output_path: Path, template_path: Path | None = None) -> None:
        """Render toolchain.cmake with substituted compiler paths.

        The template is read from template_path (defaults to toolchain.cmake next to config).
        The rendered file is written to output_path (typically inside the build tree).
        """
        if template_path is None:
            template_path = self._config_dir / "toolchain.cmake"
        tmpl = template_path.read_text()
        rendered = string.Template(tmpl.replace("@CC@", "${CC}").replace("@CXX@", "${CXX}")).safe_substitute(
            CC=self.cc, CXX=self.cxx
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered)

    def cmake_configure_command(
        self,
        extra_cache_vars: dict[str, str] | None = None,
        toolchain_path: Path | None = None,
        capture_stderr_script: Path | None = None,
    ) -> list[str]:
        """Assemble the full cmake configure command."""
        if toolchain_path is None:
            toolchain_path = self.build_dir / "toolchain.cmake"

        cmd = [
            "cmake",
            "-S",
            str(self.source_dir),
            "-B",
            str(self.build_dir),
            "-G",
            "Ninja",
            f"-DCMAKE_TOOLCHAIN_FILE={toolchain_path}",
        ]

        if self.cmake_prefix_path:
            joined = ";".join(self.cmake_prefix_path)
            cmd.append(f"-DCMAKE_PREFIX_PATH={joined}")

        # Merge config cache variables with extra overrides
        all_vars = dict(self.cmake_cache_variables)
        if extra_cache_vars:
            all_vars.update(extra_cache_vars)

        for key, value in all_vars.items():
            cmd.append(f"-D{key}={value}")

        # Inject compiler launcher for stderr capture
        if capture_stderr_script:
            cmd.append(f"-DCMAKE_CXX_COMPILER_LAUNCHER={capture_stderr_script}")

        return cmd

    def ninja_command(self, targets: list[str] | None = None) -> list[str]:
        """Assemble a ninja build command."""
        cmd = ["ninja", "-C", str(self.build_dir)]
        if self.ninja_jobs > 0:
            cmd.extend(["-j", str(self.ninja_jobs)])
        if targets:
            cmd.extend(targets)
        return cmd
