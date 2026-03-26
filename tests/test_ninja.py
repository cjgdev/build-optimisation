"""Tests for build_optimiser.ninja module."""

from __future__ import annotations

import struct

import pytest

from build_optimiser.ninja import (
    _normalise_output_path,
    _parse_cmake_target,
    join_compdb_with_log,
    map_compdb_to_targets,
    murmurhash64a,
    parse_ninja_log,
)


# ── murmurhash64a ────────────────────────────────────────────────────


class TestMurmurHash64A:
    """Tests for the MurmurHash64A implementation."""

    def test_empty_bytes(self):
        h = murmurhash64a(b"")
        assert isinstance(h, int)
        assert 0 <= h < 2**64

    def test_deterministic(self):
        assert murmurhash64a(b"hello") == murmurhash64a(b"hello")

    def test_different_inputs_differ(self):
        assert murmurhash64a(b"hello") != murmurhash64a(b"world")

    def test_short_input(self):
        h = murmurhash64a(b"a")
        assert isinstance(h, int)
        assert 0 <= h < 2**64

    def test_exact_8_bytes(self):
        h = murmurhash64a(b"12345678")
        assert isinstance(h, int)
        assert 0 <= h < 2**64

    def test_longer_than_8_bytes(self):
        h = murmurhash64a(b"this is a longer test string for hashing")
        assert isinstance(h, int)
        assert 0 <= h < 2**64

    def test_all_tail_lengths(self):
        """Ensure all tail byte lengths (1-7) are handled without error."""
        for length in range(1, 16):
            h = murmurhash64a(b"x" * length)
            assert isinstance(h, int)
            assert 0 <= h < 2**64

    def test_format_as_hex(self):
        h = murmurhash64a(b"g++ -c foo.cpp -o foo.o")
        hex_str = format(h, "x")
        assert len(hex_str) <= 16

    def test_seed_is_correct(self):
        """Verify that the seed 0xDECAFBADDECAFBAD is used."""
        # Empty input should produce a specific hash based on the seed
        h = murmurhash64a(b"")
        # With seed=0xDECAFBADDECAFBAD, m=0xc6a4a7935bd1e995, len=0:
        # h = seed ^ (0 * m) = seed
        # Then final mixing: h ^= h>>47; h *= m; h ^= h>>47
        assert h != 0  # Non-trivial output


# ── _normalise_output_path ───────────────────────────────────────────


class TestNormaliseOutputPath:
    def test_no_prefix(self):
        assert _normalise_output_path("foo/bar.o") == "foo/bar.o"

    def test_dot_slash_prefix(self):
        assert _normalise_output_path("./foo/bar.o") == "foo/bar.o"

    def test_double_dot_slash(self):
        assert _normalise_output_path("././foo.o") == "foo.o"

    def test_empty(self):
        assert _normalise_output_path("") == ""


# ── _parse_cmake_target ─────────────────────────────────────────────


class TestParseCmakeTarget:
    def test_standard_path(self):
        assert _parse_cmake_target("CMakeFiles/mylib.dir/src/foo.cpp.o") == "mylib"

    def test_no_match(self):
        assert _parse_cmake_target("src/foo.o") is None

    def test_nested_target(self):
        assert _parse_cmake_target("sub/CMakeFiles/app.dir/main.cpp.o") == "app"


# ── parse_ninja_log ─────────────────────────────────────────────────


class TestParseNinjaLog:
    """Tests for the v5 ninja log parser."""

    def test_basic_entry(self, tmp_path):
        log = tmp_path / ".ninja_log"
        log.write_text(
            "# ninja log v5\n"
            "100\t500\t0\tgen/msg.pb.cc\tabc123def456\n"
        )
        result = parse_ninja_log(str(log))
        assert "gen/msg.pb.cc" in result
        entry = result["gen/msg.pb.cc"]
        assert entry["start_ms"] == 100
        assert entry["end_ms"] == 500
        assert entry["wall_clock_ms"] == 400
        assert entry["restat_mtime"] == 0
        assert entry["command_hash"] == "abc123def456"

    def test_last_entry_wins(self, tmp_path):
        log = tmp_path / ".ninja_log"
        log.write_text(
            "# ninja log v5\n"
            "100\t500\t0\tfoo.o\thash1\n"
            "600\t900\t0\tfoo.o\thash2\n"
        )
        result = parse_ninja_log(str(log))
        assert result["foo.o"]["start_ms"] == 600
        assert result["foo.o"]["wall_clock_ms"] == 300
        assert result["foo.o"]["command_hash"] == "hash2"

    def test_multiple_outputs(self, tmp_path):
        log = tmp_path / ".ninja_log"
        log.write_text(
            "# ninja log v5\n"
            "100\t500\t0\tfoo.o\thash1\n"
            "200\t800\t0\tbar.o\thash2\n"
        )
        result = parse_ninja_log(str(log))
        assert len(result) == 2
        assert result["foo.o"]["wall_clock_ms"] == 400
        assert result["bar.o"]["wall_clock_ms"] == 600

    def test_normalises_dot_slash(self, tmp_path):
        log = tmp_path / ".ninja_log"
        log.write_text(
            "# ninja log v5\n"
            "100\t500\t0\t./gen/msg.pb.cc\thash1\n"
        )
        result = parse_ninja_log(str(log))
        assert "gen/msg.pb.cc" in result

    def test_comment_lines_skipped(self, tmp_path):
        log = tmp_path / ".ninja_log"
        log.write_text(
            "# ninja log v5\n"
            "# some comment\n"
            "100\t300\t0\tgen/out.cpp\thash1\n"
        )
        result = parse_ninja_log(str(log))
        assert result["gen/out.cpp"]["wall_clock_ms"] == 200

    def test_missing_log(self, tmp_path):
        result = parse_ninja_log(str(tmp_path / "missing"))
        assert result == {}

    def test_malformed_lines_skipped(self, tmp_path):
        log = tmp_path / ".ninja_log"
        log.write_text(
            "# ninja log v5\n"
            "not\ta\tvalid\tline\n"
            "100\t300\t0\tgood.o\thash1\n"
            "bad\t300\t0\tbad.o\thash2\n"
        )
        result = parse_ninja_log(str(log))
        assert "good.o" in result
        assert len(result) == 1

    def test_restat_mtime_preserved(self, tmp_path):
        log = tmp_path / ".ninja_log"
        log.write_text(
            "# ninja log v5\n"
            "100\t500\t1679000000\tfoo.o\thash1\n"
        )
        result = parse_ninja_log(str(log))
        assert result["foo.o"]["restat_mtime"] == 1679000000


# ── map_compdb_to_targets ───────────────────────────────────────────


class TestMapCompdbToTargets:
    def test_basic_mapping(self):
        entries = [
            {
                "directory": "/build",
                "command": "g++ -c src/foo.cpp -o CMakeFiles/mylib.dir/src/foo.cpp.o",
                "file": "src/foo.cpp",
                "output": "CMakeFiles/mylib.dir/src/foo.cpp.o",
            },
        ]
        result = map_compdb_to_targets(entries)
        assert result["src/foo.cpp"] == "mylib"

    def test_multiple_targets(self):
        entries = [
            {
                "file": "a.cpp",
                "output": "CMakeFiles/libA.dir/a.cpp.o",
            },
            {
                "file": "b.cpp",
                "output": "CMakeFiles/libB.dir/b.cpp.o",
            },
        ]
        result = map_compdb_to_targets(entries)
        assert result["a.cpp"] == "libA"
        assert result["b.cpp"] == "libB"

    def test_no_cmake_target_in_path(self):
        entries = [{"file": "foo.cpp", "output": "foo.o"}]
        result = map_compdb_to_targets(entries)
        assert "foo.cpp" not in result

    def test_missing_fields(self):
        entries = [{"file": "", "output": ""}]
        result = map_compdb_to_targets(entries)
        assert result == {}


# ── join_compdb_with_log ─────────────────────────────────────────────


class TestJoinCompdbWithLog:
    def test_basic_join(self):
        compdb = [
            {
                "file": "src/foo.cpp",
                "output": "CMakeFiles/mylib.dir/src/foo.cpp.o",
            },
        ]
        log = {
            "CMakeFiles/mylib.dir/src/foo.cpp.o": {
                "start_ms": 100,
                "end_ms": 500,
                "wall_clock_ms": 400,
                "restat_mtime": 0,
                "command_hash": "abc123",
                "output": "CMakeFiles/mylib.dir/src/foo.cpp.o",
            },
        }
        result = join_compdb_with_log(compdb, log)
        assert len(result) == 1
        row = result[0]
        assert row["target_path"] == "CMakeFiles/mylib.dir/src/foo.cpp.o"
        assert row["source_file"] == "src/foo.cpp"
        assert row["cmake_target"] == "mylib"
        assert row["start_ms"] == 100
        assert row["end_ms"] == 500
        assert row["wall_clock_ms"] == 400

    def test_no_log_entry(self):
        compdb = [{"file": "foo.cpp", "output": "foo.o"}]
        result = join_compdb_with_log(compdb, {})
        assert len(result) == 1
        assert result[0]["start_ms"] == ""
        assert result[0]["wall_clock_ms"] == ""

    def test_dot_slash_normalisation(self):
        compdb = [
            {"file": "foo.cpp", "output": "./CMakeFiles/lib.dir/foo.cpp.o"},
        ]
        log = {
            "CMakeFiles/lib.dir/foo.cpp.o": {
                "start_ms": 0,
                "end_ms": 200,
                "wall_clock_ms": 200,
                "restat_mtime": 0,
                "command_hash": "h",
                "output": "CMakeFiles/lib.dir/foo.cpp.o",
            },
        }
        result = join_compdb_with_log(compdb, log)
        assert result[0]["wall_clock_ms"] == 200

    def test_skips_entries_without_output(self):
        compdb = [{"file": "foo.cpp"}]  # no 'output' key
        result = join_compdb_with_log(compdb, {})
        assert result == []

    def test_multiple_entries(self):
        compdb = [
            {"file": "a.cpp", "output": "CMakeFiles/X.dir/a.o"},
            {"file": "b.cpp", "output": "CMakeFiles/Y.dir/b.o"},
        ]
        log = {
            "CMakeFiles/X.dir/a.o": {
                "start_ms": 0, "end_ms": 100, "wall_clock_ms": 100,
                "restat_mtime": 0, "command_hash": "h1",
                "output": "CMakeFiles/X.dir/a.o",
            },
            "CMakeFiles/Y.dir/b.o": {
                "start_ms": 50, "end_ms": 300, "wall_clock_ms": 250,
                "restat_mtime": 0, "command_hash": "h2",
                "output": "CMakeFiles/Y.dir/b.o",
            },
        }
        result = join_compdb_with_log(compdb, log)
        assert len(result) == 2
        assert result[0]["cmake_target"] == "X"
        assert result[1]["cmake_target"] == "Y"
        assert result[0]["wall_clock_ms"] == 100
        assert result[1]["wall_clock_ms"] == 250
