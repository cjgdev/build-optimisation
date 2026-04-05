"""Tests for scripts/consolidate/build_header_edges.py pure functions."""

import importlib

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

mod = importlib.import_module("scripts.consolidate.build_header_edges")
is_system_header = mod.is_system_header
canonicalise = mod.canonicalise
extract_edges = mod.extract_edges
build_target_lookup = mod.build_target_lookup
resolve_target = mod.resolve_target
count_lines = mod.count_lines


class TestIsSystemHeader:
    def test_usr_include(self):
        assert is_system_header("/usr/include/stdio.h") is True

    def test_usr_local(self):
        assert is_system_header("/usr/local/include/boost/config.hpp") is True

    def test_xcode_sdk(self):
        assert is_system_header("/Applications/Xcode.app/Contents/Developer/SDK/foo.h") is True

    def test_third_party_fragment(self):
        assert is_system_header("/home/user/project/third_party/gtest/gtest.h") is True

    def test_vendor_fragment(self):
        assert is_system_header("/opt/code/vendor/json.hpp") is True

    def test_project_header(self):
        assert is_system_header("/home/user/project/src/core/types.h") is False

    def test_external_fragment(self):
        assert is_system_header("/project/external/lib/header.h") is True

    # --- Untested prefixes ---

    def test_usr_lib_gcc(self):
        assert is_system_header("/usr/lib/gcc/x86_64-linux-gnu/12/include/stddef.h") is True

    def test_usr_lib_x86_64(self):
        assert is_system_header("/usr/lib/x86_64-linux-gnu/glib-2.0/include/glibconfig.h") is True

    def test_library_developer(self):
        assert is_system_header("/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/math.h") is True

    # --- Untested fragments ---

    def test_3rdparty_fragment(self):
        assert is_system_header("/home/user/project/3rdparty/catch2/catch.hpp") is True

    def test_thirdparty_fragment(self):
        assert is_system_header("/home/user/project/thirdparty/spdlog/spdlog.h") is True

    # --- Negative / boundary tests ---

    def test_project_header_absolute_path(self):
        assert is_system_header("/home/user/project/src/engine/render.h") is False

    def test_usr_prefix_not_include(self):
        """Path starts with /usr but not a system prefix."""
        assert is_system_header("/usr/share/doc/readme.h") is False

    def test_fragment_without_slashes(self):
        """'third_party' without surrounding slashes should not match."""
        assert is_system_header("/home/user/project/src/third_partyfoo.h") is False

    def test_partial_vendor_no_trailing_slash(self):
        """'vendor' as part of a name, not a directory, should not match."""
        assert is_system_header("/home/user/project/src/vendor_utils.h") is False

    def test_canonicalise_then_classify(self):
        """Paths with '..' that normalise to a system location should classify as system."""
        normalised = canonicalise("/usr/local/../local/include/boost/config.hpp")
        assert is_system_header(normalised) is True


class TestCanonicalise:
    def test_resolves_dotdot(self):
        result = canonicalise("/a/b/../c/d.h")
        assert result == "/a/c/d.h"

    def test_normalises_slashes(self):
        result = canonicalise("/a//b/./c.h")
        assert result == "/a/b/c.h"


class TestExtractEdges:
    def test_empty_tree(self):
        edges = extract_edges("/src/main.cpp", [])
        assert edges == []

    def test_single_level(self):
        tree = [[1, "/src/foo.h"], [1, "/src/bar.h"]]
        edges = extract_edges("/src/main.cpp", tree)
        assert len(edges) == 2
        includers = {e["includer"] for e in edges}
        assert includers == {canonicalise("/src/main.cpp")}
        included = {e["included"] for e in edges}
        assert canonicalise("/src/foo.h") in included
        assert canonicalise("/src/bar.h") in included

    def test_nested_depth(self):
        tree = [[1, "/src/foo.h"], [2, "/src/types.h"]]
        edges = extract_edges("/src/main.cpp", tree)
        # main.cpp -> foo.h, foo.h -> types.h
        assert len(edges) == 2
        deep_edge = [e for e in edges if e["included"] == canonicalise("/src/types.h")][0]
        assert deep_edge["includer"] == canonicalise("/src/foo.h")
        assert deep_edge["depth"] == 2

    def test_dedup_within_tu(self):
        tree = [[1, "/src/foo.h"], [1, "/src/foo.h"]]
        edges = extract_edges("/src/main.cpp", tree)
        assert len(edges) == 1

    def test_system_header_flagged(self):
        tree = [[1, "/usr/include/stdio.h"]]
        edges = extract_edges("/src/main.cpp", tree)
        assert edges[0]["is_system"] is True

    def test_source_file_in_edge(self):
        tree = [[1, "/src/foo.h"]]
        edges = extract_edges("/src/main.cpp", tree)
        assert edges[0]["source_file"] == canonicalise("/src/main.cpp")


class TestBuildTargetLookup:
    def test_missing_file_returns_empty(self, tmp_path):
        file_to_target, target_dirs = build_target_lookup(tmp_path / "nonexistent.parquet")
        assert file_to_target == {}
        assert target_dirs == []

    def test_builds_lookup(self, tmp_path):
        import json

        tm = pd.DataFrame(
            {
                "cmake_target": ["lib_a"],
                "source_files": [json.dumps(["/src/a/main.cpp", "/src/a/util.cpp"])],
                "generated_files": [json.dumps([])],
            }
        )
        path = tmp_path / "target_metrics.parquet"
        pq.write_table(pa.Table.from_pandas(tm), path)
        file_to_target, target_dirs = build_target_lookup(path)
        assert file_to_target[canonicalise("/src/a/main.cpp")] == "lib_a"
        assert len(target_dirs) > 0


class TestResolveTarget:
    def test_direct_hit(self):
        ftt = {"/src/a/main.cpp": "lib_a"}
        assert resolve_target("/src/a/main.cpp", ftt, []) == "lib_a"

    def test_prefix_match(self):
        dirs = [("/src/a", "lib_a"), ("/src", "lib_root")]
        assert resolve_target("/src/a/header.h", {}, dirs) == "lib_a"

    def test_no_match(self):
        assert resolve_target("/unknown/header.h", {}, []) is None


class TestCountLines:
    def test_basic_count(self, tmp_path):
        src = tmp_path / "test.cpp"
        src.write_text("// comment\n\nint main() {\n  return 0;\n}\n")
        result = count_lines(str(src))
        assert result["sloc"] == 3  # int main, return, }
        assert result["source_size_bytes"] > 0

    def test_nonexistent_file(self):
        result = count_lines("/nonexistent/path.h")
        assert result["sloc"] == 0
        assert result["source_size_bytes"] == 0
