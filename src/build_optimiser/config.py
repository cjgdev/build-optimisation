"""Configuration loading and CMake command building."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load config.yaml and return as dict."""
    if config_path is None:
        config_path = _PROJECT_ROOT / "config.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    # Resolve relative paths against project root
    for key in ("build_dir", "raw_data_dir", "processed_data_dir"):
        p = Path(cfg[key])
        if not p.is_absolute():
            cfg[key] = str(_PROJECT_ROOT / p)
    return cfg


def render_toolchain(cfg: dict[str, Any], output_path: Path | None = None) -> Path:
    """Render toolchain.cmake from template, substituting devtoolset root.

    Returns the path to the rendered toolchain file.
    """
    toolset_root = cfg["gcc_toolset"]["root"]

    template_path = _PROJECT_ROOT / "toolchain.cmake"
    template = template_path.read_text()

    rendered = template.replace("@GCC_TOOLSET_ROOT@", toolset_root)

    if output_path is None:
        output_path = Path(cfg["build_dir"]) / "toolchain.cmake"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered)

    return output_path


def build_environment(cfg: dict[str, Any]) -> dict[str, str]:
    """Construct a subprocess environment with devtoolset paths.

    Prepends the devtoolset bin directory to PATH and sets
    LD_LIBRARY_PATH. This mirrors what /opt/rh/gcc-toolset-12/enable
    does, but without sourcing any external scripts.
    """
    env = os.environ.copy()
    toolset = cfg["gcc_toolset"]
    root = toolset["root"]

    # Prepend devtoolset bin directory to PATH.
    # This ensures that when Ninja invokes the compiler, and when
    # the compiler internally shells out to tools like 'as' (the
    # assembler), the devtoolset versions are found first.
    bin_dir = os.path.join(root, "usr", "bin")
    env["PATH"] = bin_dir + ":" + env.get("PATH", "")

    # Set LD_LIBRARY_PATH so the compiler and linker can find
    # the devtoolset's own runtime libraries.
    ld_paths = toolset.get("ld_library_path", [])
    existing_ld = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = ":".join(
        ld_paths + ([existing_ld] if existing_ld else [])
    )

    return env


def build_cmake_command(
    cfg: dict[str, Any],
    pass_flags: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Assemble the full CMake configure command line.

    Args:
        cfg: Loaded config dict.
        pass_flags: Pass-specific CMake cache variables, e.g.
            {"CMAKE_CXX_FLAGS": "-ftime-report"}.
        extra_args: Additional raw CMake arguments (e.g. ["--graphviz=..."]).

    Returns:
        Command as a list of strings suitable for subprocess.run().
    """
    toolchain_path = render_toolchain(cfg)
    build_dir = cfg["build_dir"]
    source_dir = cfg["source_dir"]

    cmd = [
        "cmake",
        "-S", source_dir,
        "-B", build_dir,
        "-G", "Ninja",
        f"-DCMAKE_TOOLCHAIN_FILE={toolchain_path}",
    ]

    # CMAKE_PREFIX_PATH
    prefix_paths = cfg.get("cmake_prefix_path", [])
    if prefix_paths:
        joined = ";".join(prefix_paths)
        cmd.append(f"-DCMAKE_PREFIX_PATH={joined}")

    # Standard cache variables from config
    for var, value in cfg.get("cmake_cache_variables", {}).items():
        cmd.append(f"-D{var}={value}")

    # Pass-specific flags
    if pass_flags:
        for var, value in pass_flags.items():
            cmd.append(f"-D{var}={value}")

    # Extra raw arguments
    if extra_args:
        cmd.extend(extra_args)

    return cmd


def build_ninja_command(
    cfg: dict[str, Any],
    target: str | None = None,
    jobs: int | None = None,
) -> list[str]:
    """Assemble a Ninja build command.

    Args:
        cfg: Loaded config dict.
        target: Specific Ninja target to build, or None for all.
        jobs: Override parallelism (0 = Ninja decides).

    Returns:
        Command as a list of strings.
    """
    build_dir = cfg["build_dir"]
    j = jobs if jobs is not None else cfg.get("ninja_jobs", 0)

    cmd = ["ninja", "-C", build_dir]
    if j > 0:
        cmd.extend(["-j", str(j)])
    if target:
        cmd.append(target)
    return cmd
