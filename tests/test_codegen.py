"""Tests for build_optimiser.codegen module."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from build_optimiser.codegen import (
    _find_unescaped_colon,
    _resolve_continuations,
    _split_ninja_paths,
    _unescape_ninja_path,
    classify_command,
    map_outputs_to_targets,
    parse_build_ninja,
    parse_ninja_log_for_commands,
)


# ── classify_command ──────────────────────────────────────────────────


class TestClassifyCommand:
    """Tests for the classify_command function."""

    def test_flex(self):
        assert classify_command("/usr/bin/flex -o out.cpp input.l", ["out.cpp"]) == "flex"

    def test_flex_bare(self):
        assert classify_command("flex scanner.l", ["scanner.cpp"]) == "flex"

    def test_bison(self):
        assert classify_command("/opt/bison -d parser.yy", ["parser.cpp", "parser.hpp"]) == "bison"

    def test_protoc(self):
        cmd = "/usr/local/bin/protoc --cpp_out=. msg.proto"
        assert classify_command(cmd, ["msg.pb.cc", "msg.pb.h"]) == "protoc"

    def test_xsdcxx_xsd(self):
        cmd = "/usr/bin/xsd cxx-tree schema.xsd"
        assert classify_command(cmd, ["schema.cxx", "schema.hxx"]) == "xsdcxx"

    def test_xsdcxx_xsdcxx(self):
        cmd = "xsdcxx cxx-tree --output-dir out schema.xsd"
        assert classify_command(cmd, ["out/schema.cxx"]) == "xsdcxx"

    def test_swagger_codegen(self):
        cmd = "swagger-codegen generate -i api.yaml -l cpp-restbed-server"
        assert classify_command(cmd, ["api.cpp", "api.h"]) == "swagger_codegen"

    def test_openapi_generator(self):
        cmd = "openapi-generator generate -i api.json"
        assert classify_command(cmd, ["model.cpp"]) == "swagger_codegen"

    def test_gsoap_soapcpp2(self):
        cmd = "/opt/gsoap/bin/soapcpp2 -c calc.h"
        assert classify_command(cmd, ["soapC.c", "soapH.h"]) == "gsoap"

    def test_gsoap_wsdl2h(self):
        cmd = "wsdl2h -o service.h service.wsdl"
        assert classify_command(cmd, ["service.h"]) == "gsoap"

    def test_message_compiler(self):
        cmd = "/path/to/tools/MessageCompiler --input msg.def"
        assert classify_command(cmd, ["msg.cpp", "msg.h"]) == "MessageCompiler"

    def test_dbautogen(self):
        cmd = "python DbAutoGen --schema db.json"
        assert classify_command(cmd, ["db_tables.cpp"]) == "DbAutoGen"

    def test_template_compiler(self):
        cmd = "/tools/TemplateCompiler template.tmpl"
        assert classify_command(cmd, ["generated.cpp"]) == "TemplateCompiler"

    def test_unknown_codegen(self):
        """Command not matching any known generator but producing .cpp output."""
        cmd = "/custom/my_generator input.def"
        assert classify_command(cmd, ["output.cpp"]) == "unknown_codegen"

    def test_non_codegen(self):
        """Command that doesn't produce source code outputs."""
        cmd = "cmake -E copy file.txt dest/"
        assert classify_command(cmd, ["dest/file.txt"]) == "non_codegen"

    def test_non_codegen_resource(self):
        cmd = "xxd -i resource.bin resource.o"
        assert classify_command(cmd, ["resource.o"]) == "non_codegen"

    def test_user_patterns_override(self):
        """User-supplied patterns override built-in ones."""
        patterns = {"protoc": ["/my/custom/protoc_wrapper"]}
        cmd = "/my/custom/protoc_wrapper msg.proto"
        assert classify_command(cmd, ["msg.pb.cc"], codegen_patterns=patterns) == "protoc"

    def test_user_patterns_new_generator(self):
        """User-supplied patterns can add new generator names."""
        patterns = {"MyCustomGen": ["my_custom_gen"]}
        cmd = "/tools/my_custom_gen schema.def"
        assert classify_command(cmd, ["output.cpp"], codegen_patterns=patterns) == "MyCustomGen"

    def test_first_match_wins(self):
        """If a command matches multiple patterns, the first one wins."""
        # flex appears before bison in the pattern list
        cmd = "flex bison something"
        assert classify_command(cmd, ["out.cpp"]) == "flex"


# ── parse_build_ninja ─────────────────────────────────────────────────


class TestParseBuildNinja:
    """Tests for the build.ninja parser."""

    def test_basic_custom_command(self, tmp_path):
        ninja = tmp_path / "build.ninja"
        ninja.write_text(textwrap.dedent("""\
            build gen/msg.pb.cc gen/msg.pb.h : CUSTOM_COMMAND msg.proto | /usr/bin/protoc
              COMMAND = /usr/bin/protoc --cpp_out=gen msg.proto
              DESC = Generating protobuf for msg.proto
        """))
        edges = parse_build_ninja(str(tmp_path))
        assert len(edges) == 1
        e = edges[0]
        assert e["rule"] == "CUSTOM_COMMAND"
        assert e["outputs"] == ["gen/msg.pb.cc", "gen/msg.pb.h"]
        assert e["inputs"] == ["msg.proto"]
        assert e["implicit"] == ["/usr/bin/protoc"]
        assert e["variables"]["COMMAND"] == "/usr/bin/protoc --cpp_out=gen msg.proto"
        assert e["variables"]["DESC"] == "Generating protobuf for msg.proto"

    def test_compile_edge(self, tmp_path):
        ninja = tmp_path / "build.ninja"
        ninja.write_text(textwrap.dedent("""\
            build CMakeFiles/mylib.dir/src/foo.cpp.o : CXX_COMPILER__mylib src/foo.cpp
              COMMAND = /usr/bin/g++ -c src/foo.cpp -o CMakeFiles/mylib.dir/src/foo.cpp.o
        """))
        edges = parse_build_ninja(str(tmp_path))
        assert len(edges) == 1
        assert edges[0]["rule"] == "CXX_COMPILER__mylib"

    def test_multiple_edges(self, tmp_path):
        ninja = tmp_path / "build.ninja"
        ninja.write_text(textwrap.dedent("""\
            build out1.cpp : CUSTOM_COMMAND in1.y
              COMMAND = bison in1.y -o out1.cpp

            build out2.cpp : CUSTOM_COMMAND in2.l
              COMMAND = flex -o out2.cpp in2.l
        """))
        edges = parse_build_ninja(str(tmp_path))
        assert len(edges) == 2
        assert edges[0]["rule"] == "CUSTOM_COMMAND"
        assert edges[1]["rule"] == "CUSTOM_COMMAND"

    def test_order_only_deps(self, tmp_path):
        ninja = tmp_path / "build.ninja"
        ninja.write_text(textwrap.dedent("""\
            build out.cpp : CUSTOM_COMMAND in.proto | /usr/bin/protoc || cmake_order_dep
              COMMAND = /usr/bin/protoc in.proto
        """))
        edges = parse_build_ninja(str(tmp_path))
        assert len(edges) == 1
        assert edges[0]["order_only"] == ["cmake_order_dep"]
        assert edges[0]["implicit"] == ["/usr/bin/protoc"]

    def test_empty_file(self, tmp_path):
        ninja = tmp_path / "build.ninja"
        ninja.write_text("")
        edges = parse_build_ninja(str(tmp_path))
        assert edges == []

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_build_ninja(str(tmp_path / "nonexistent"))

    def test_line_continuation(self, tmp_path):
        """Build lines spanning multiple physical lines via $\\n."""
        ninja = tmp_path / "build.ninja"
        ninja.write_text(
            "build gen/msg.pb.cc $\n"
            "  gen/msg.pb.h : CUSTOM_COMMAND $\n"
            "  msg.proto | /usr/bin/protoc\n"
            "  COMMAND = /usr/bin/protoc --cpp_out=gen msg.proto\n"
        )
        edges = parse_build_ninja(str(tmp_path))
        assert len(edges) == 1
        e = edges[0]
        assert e["rule"] == "CUSTOM_COMMAND"
        assert e["outputs"] == ["gen/msg.pb.cc", "gen/msg.pb.h"]
        assert e["inputs"] == ["msg.proto"]
        assert e["implicit"] == ["/usr/bin/protoc"]

    def test_escaped_space_in_path(self, tmp_path):
        """Paths with escaped spaces should be treated as single tokens."""
        ninja = tmp_path / "build.ninja"
        ninja.write_text(
            "build my$ output.o : CXX_COMPILER__lib my$ input.cpp\n"
        )
        edges = parse_build_ninja(str(tmp_path))
        assert len(edges) == 1
        assert edges[0]["outputs"] == ["my output.o"]
        assert edges[0]["inputs"] == ["my input.cpp"]

    def test_escaped_colon_in_path(self, tmp_path):
        """$: in paths should not be mistaken for the build separator."""
        ninja = tmp_path / "build.ninja"
        ninja.write_text(
            "build C$:/Users/out.o : CXX_COMPILER__lib C$:/Users/in.cpp\n"
        )
        edges = parse_build_ninja(str(tmp_path))
        assert len(edges) == 1
        assert edges[0]["outputs"] == ["C:/Users/out.o"]
        assert edges[0]["inputs"] == ["C:/Users/in.cpp"]
        assert edges[0]["rule"] == "CXX_COMPILER__lib"

    def test_implicit_outputs(self, tmp_path):
        """Outputs before : with | separator for implicit outputs."""
        ninja = tmp_path / "build.ninja"
        ninja.write_text(
            "build out.dll | out.lib : link main.o\n"
        )
        edges = parse_build_ninja(str(tmp_path))
        assert len(edges) == 1
        assert edges[0]["outputs"] == ["out.dll"]
        assert edges[0]["implicit_outputs"] == ["out.lib"]
        assert edges[0]["inputs"] == ["main.o"]

    def test_cmake_workdir_implicit_outputs(self, tmp_path):
        """CMake-style build lines with ${cmake_ninja_workdir} implicit outputs."""
        ninja = tmp_path / "build.ninja"
        ninja.write_text(
            "build autogen/timestamp autogen/mocs.cpp"
            " | ${cmake_ninja_workdir}autogen/timestamp"
            " ${cmake_ninja_workdir}autogen/mocs.cpp"
            " : CUSTOM_COMMAND || autogen_deps\n"
            "  COMMAND = cmake -E cmake_autogen info.json\n"
        )
        edges = parse_build_ninja(str(tmp_path))
        assert len(edges) == 1
        e = edges[0]
        assert e["outputs"] == ["autogen/timestamp", "autogen/mocs.cpp"]
        assert len(e["implicit_outputs"]) == 2
        assert e["rule"] == "CUSTOM_COMMAND"
        assert e["order_only"] == ["autogen_deps"]

    def test_multiline_command_variable(self, tmp_path):
        """COMMAND variable value spanning multiple lines via $\\n continuation."""
        ninja = tmp_path / "build.ninja"
        ninja.write_text(
            "build out.cpp : CUSTOM_COMMAND in.y\n"
            "  COMMAND = cd /build && $\n"
            "    /usr/bin/bison -o out.cpp in.y\n"
        )
        edges = parse_build_ninja(str(tmp_path))
        assert len(edges) == 1
        assert "bison" in edges[0]["variables"]["COMMAND"]
        assert "cd /build" in edges[0]["variables"]["COMMAND"]


# ── map_outputs_to_targets ────────────────────────────────────────────


class TestMapOutputsToTargets:
    """Tests for the output-to-target mapping."""

    def test_basic_mapping(self):
        edges = [
            {
                "rule": "CUSTOM_COMMAND",
                "outputs": ["gen/msg.pb.cc"],
                "inputs": ["msg.proto"],
                "implicit": [],
                "order_only": [],
                "variables": {"COMMAND": "protoc msg.proto"},
            },
            {
                "rule": "CXX_COMPILER__mylib",
                "outputs": ["CMakeFiles/mylib.dir/gen/msg.pb.cc.o"],
                "inputs": ["gen/msg.pb.cc"],
                "implicit": [],
                "order_only": [],
                "variables": {},
            },
        ]
        mapping = map_outputs_to_targets(edges)
        assert mapping == {"gen/msg.pb.cc": "mylib"}

    def test_no_consumer(self):
        """Generated file with no compilation edge mapping."""
        edges = [
            {
                "rule": "CUSTOM_COMMAND",
                "outputs": ["gen/orphan.h"],
                "inputs": ["schema.xsd"],
                "implicit": [],
                "order_only": [],
                "variables": {"COMMAND": "xsd schema.xsd"},
            },
        ]
        mapping = map_outputs_to_targets(edges)
        assert mapping == {}

    def test_non_source_output_ignored(self):
        """Non-source outputs (e.g. .txt) are not mapped."""
        edges = [
            {
                "rule": "CUSTOM_COMMAND",
                "outputs": ["config.txt"],
                "inputs": ["config.in"],
                "implicit": [],
                "order_only": [],
                "variables": {"COMMAND": "cmake -E copy config.in config.txt"},
            },
        ]
        mapping = map_outputs_to_targets(edges)
        assert mapping == {}


# ── parse_ninja_log_for_commands ──────────────────────────────────────


class TestParseNinjaLog:
    """Tests for ninja log timing extraction."""

    def test_basic_timing(self, tmp_path):
        log = tmp_path / ".ninja_log"
        log.write_text(
            "# ninja log v5\n"
            "100\t500\t0\tabc123\tgen/msg.pb.cc\n"
            "200\t800\t0\tdef456\tgen/other.pb.cc\n"
        )
        known = {"gen/msg.pb.cc"}
        result = parse_ninja_log_for_commands(str(log), known)
        assert result == {"gen/msg.pb.cc": 400}

    def test_empty_known_set(self, tmp_path):
        log = tmp_path / ".ninja_log"
        log.write_text(
            "# ninja log v5\n"
            "100\t500\t0\tabc123\tgen/msg.pb.cc\n"
        )
        result = parse_ninja_log_for_commands(str(log), set())
        assert result == {}

    def test_missing_log(self, tmp_path):
        result = parse_ninja_log_for_commands(str(tmp_path / "missing"), {"foo"})
        assert result == {}

    def test_comment_lines_skipped(self, tmp_path):
        log = tmp_path / ".ninja_log"
        log.write_text(
            "# ninja log v5\n"
            "# some comment\n"
            "100\t300\t0\thash1\tgen/out.cpp\n"
        )
        result = parse_ninja_log_for_commands(str(log), {"gen/out.cpp"})
        assert result == {"gen/out.cpp": 200}

    def test_normalised_paths(self, tmp_path):
        """Paths with ./ prefix should match normalised ninja_log entries."""
        log = tmp_path / ".ninja_log"
        log.write_text(
            "# ninja log v5\n"
            "100\t500\t0\tabc123\tgen/msg.pb.cc\n"
        )
        # Parser might produce ./gen/msg.pb.cc, log has gen/msg.pb.cc
        result = parse_ninja_log_for_commands(str(log), {"./gen/msg.pb.cc"})
        assert result == {"./gen/msg.pb.cc": 400}

    def test_log_path_with_leading_dotslash(self, tmp_path):
        """Log has ./prefix, known_outputs doesn't."""
        log = tmp_path / ".ninja_log"
        log.write_text(
            "# ninja log v5\n"
            "100\t500\t0\tabc123\t./gen/msg.pb.cc\n"
        )
        result = parse_ninja_log_for_commands(str(log), {"gen/msg.pb.cc"})
        assert result == {"gen/msg.pb.cc": 400}


# ── Helper function tests ────────────────────────────────────────────


class TestResolveContinuations:
    def test_no_continuation(self):
        assert _resolve_continuations(["abc\n", "def\n"]) == ["abc", "def"]

    def test_single_continuation(self):
        result = _resolve_continuations(["abc $\n", "  def\n"])
        assert result == ["abc def"]

    def test_double_dollar_not_continuation(self):
        result = _resolve_continuations(["abc$$\n", "def\n"])
        assert result == ["abc$$", "def"]

    def test_multi_continuation(self):
        result = _resolve_continuations(["a $\n", "  b $\n", "  c\n"])
        # "a " + "b " + "c" — each continuation strips leading whitespace
        assert result == ["a b c"]


class TestSplitNinjaPaths:
    def test_simple(self):
        assert _split_ninja_paths("a b c") == ["a", "b", "c"]

    def test_escaped_space(self):
        assert _split_ninja_paths("my$ file.o other.o") == ["my$ file.o", "other.o"]

    def test_escaped_colon(self):
        assert _split_ninja_paths("C$:/Users/file.o") == ["C$:/Users/file.o"]


class TestUnescapeNinjaPath:
    def test_escaped_space(self):
        assert _unescape_ninja_path("my$ file.o") == "my file.o"

    def test_escaped_colon(self):
        assert _unescape_ninja_path("C$:/Users") == "C:/Users"

    def test_escaped_dollar(self):
        assert _unescape_ninja_path("price$$10") == "price$10"

    def test_no_escapes(self):
        assert _unescape_ninja_path("normal/path.o") == "normal/path.o"


class TestFindUnescapedColon:
    def test_simple(self):
        assert _find_unescaped_colon("output : rule") == 7

    def test_escaped_colon_skipped(self):
        assert _find_unescaped_colon("C$:/out : rule") == 8

    def test_no_colon(self):
        assert _find_unescaped_colon("no colon here") == -1
