"""Tests for build_optimiser.metrics module."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from build_optimiser.metrics import (
    parse_cmake_target_from_object_path,
    canonicalise_path,
    align_git_paths,
    map_compile_commands_to_targets,
    aggregate_file_to_target,
)


class TestParseCmakeTarget:
    def test_standard_path(self):
        path = "CMakeFiles/my_library.dir/src/foo.cpp.o"
        assert parse_cmake_target_from_object_path(path) == "my_library"

    def test_nested_path(self):
        path = "/build/CMakeFiles/my_lib.dir/deep/nested/file.cpp.o"
        assert parse_cmake_target_from_object_path(path) == "my_lib"

    def test_no_match(self):
        path = "lib/libfoo.so"
        assert parse_cmake_target_from_object_path(path) is None

    def test_empty(self):
        assert parse_cmake_target_from_object_path("") is None


class TestCanonicalisePath:
    def test_relative_path(self, tmp_path):
        result = canonicalise_path("src/foo.cpp", str(tmp_path))
        assert Path(result).is_absolute()
        assert result.endswith("src/foo.cpp")

    def test_absolute_path(self):
        result = canonicalise_path("/abs/path/foo.cpp", "/other")
        assert result == "/abs/path/foo.cpp"


class TestAlignGitPaths:
    def test_converts_relative_to_absolute(self):
        df = pd.DataFrame({"source_file": ["src/foo.cpp", "src/bar.cpp"]})
        result = align_git_paths(df, "/repo")
        assert all(Path(p).is_absolute() for p in result["source_file"])


class TestMapCompileCommands:
    def test_parses_commands(self, tmp_path):
        commands = [
            {
                "file": "/src/foo.cpp",
                "command": "g++ -o CMakeFiles/mylib.dir/src/foo.cpp.o -c /src/foo.cpp",
                "directory": "/build",
            }
        ]
        cc_path = tmp_path / "compile_commands.json"
        with open(cc_path, "w") as f:
            json.dump(commands, f)

        mapping = map_compile_commands_to_targets(str(cc_path))
        assert "/src/foo.cpp" in mapping or str(Path("/src/foo.cpp").resolve()) in mapping


class TestAggregateFileToTarget:
    def test_aggregates_correctly(self):
        df = pd.DataFrame({
            "cmake_target": ["libA", "libA", "libB"],
            "compile_time_ms": [100, 200, 300],
            "code_lines": [50, 60, 70],
        })
        result = aggregate_file_to_target(df)
        assert len(result) == 2
        assert "file_count" in result.columns
        liba = result[result["cmake_target"] == "libA"]
        assert liba["file_count"].iloc[0] == 2
