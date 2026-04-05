"""Tests for ninja log parsing and step classification."""

import importlib
import tempfile
from pathlib import Path

# The script module name starts with a digit, so import via importlib
_mod = importlib.import_module("scripts.collect.06_ninja_log")
parse_ninja_log = _mod.parse_ninja_log
classify_step = _mod.classify_step

SAMPLE_LOG = """\
# ninja log v5
0\t500\t0\tCMakeFiles/core.dir/src/core/types.cpp.o\tabc123
0\t800\t0\tCMakeFiles/core.dir/src/core/assert.cpp.o\tdef456
100\t2000\t0\tsrc/core/libcore.a\tghi789
200\t3000\t0\tapp\tjkl012
50\t150\t0\tsrc/codegen/generated/messages.cpp\tmno345
500\t600\t0\tsrc/plugin_api/libplugin_api.dylib\tpqr678
"""


class TestParseNinjaLog:
    def test_parses_all_records(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ninja_log", delete=False) as f:
            f.write(SAMPLE_LOG)
            f.flush()
            records = parse_ninja_log(Path(f.name))
        assert len(records) == 6

    def test_fields_correct(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ninja_log", delete=False) as f:
            f.write(SAMPLE_LOG)
            f.flush()
            records = parse_ninja_log(Path(f.name))

        first = records[0]
        assert first["start_ms"] == 0
        assert first["end_ms"] == 500
        assert first["output_path"] == "CMakeFiles/core.dir/src/core/types.cpp.o"
        assert first["command_hash"] == "abc123"

    def test_skips_header_and_empty_lines(self):
        log = "# ninja log v5\n\n0\t100\t0\tfile.o\thash1\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ninja_log", delete=False) as f:
            f.write(log)
            f.flush()
            records = parse_ninja_log(Path(f.name))
        assert len(records) == 1


class TestClassifyStep:
    def setup_method(self):
        self.file_index = {
            "/src/core/types.cpp": "core",
            "/src/core/assert.cpp": "core",
        }
        self.target_artifacts = {
            "/build/src/core/libcore.a": "core",
            "/build/app": "app",
            "/build/src/plugin_api/libplugin_api.dylib": "plugin_api",
        }
        self.codegen_outputs = {
            "/build/src/codegen/generated/messages.cpp",
        }

    def test_compile_step(self):
        step_type, source, target = classify_step(
            "CMakeFiles/core.dir/src/core/types.cpp.o",
            self.file_index,
            self.target_artifacts,
            self.codegen_outputs,
            "/build",
        )
        assert step_type == "compile"

    def test_archive_step(self):
        step_type, source, target = classify_step(
            "src/core/libcore.a", self.file_index, self.target_artifacts, self.codegen_outputs, "/build"
        )
        assert step_type == "archive"

    def test_link_step_dylib(self):
        step_type, source, target = classify_step(
            "src/plugin_api/libplugin_api.dylib", self.file_index, self.target_artifacts, self.codegen_outputs, "/build"
        )
        assert step_type == "link"

    def test_unknown_step(self):
        step_type, source, target = classify_step(
            "some/random/file.txt", self.file_index, self.target_artifacts, self.codegen_outputs, "/build"
        )
        assert step_type == "other"
