"""Tests for scripts/collect/04_post_build_metrics.py pure functions."""

import importlib

mod = importlib.import_module("scripts.collect.04_post_build_metrics")
find_object_files = mod.find_object_files
map_object_to_source = mod.map_object_to_source
count_lines_python = mod.count_lines_python


class TestFindObjectFiles:
    def test_finds_o_files(self, tmp_path):
        (tmp_path / "CMakeFiles").mkdir()
        (tmp_path / "CMakeFiles" / "foo.cpp.o").touch()
        (tmp_path / "CMakeFiles" / "bar.cpp.o").touch()
        (tmp_path / "CMakeFiles" / "not_an_object.txt").touch()
        result = find_object_files(tmp_path)
        assert len(result) == 2
        assert all(str(p).endswith(".o") for p in result)

    def test_empty_dir(self, tmp_path):
        result = find_object_files(tmp_path)
        assert result == []


class TestMapObjectToSource:
    def test_cmake_dir_pattern(self, tmp_path):
        build_dir = tmp_path / "build"
        obj_dir = build_dir / "CMakeFiles" / "mylib.dir" / "src"
        obj_dir.mkdir(parents=True)
        obj_path = obj_dir / "main.cpp.o"
        obj_path.touch()

        file_index = {"/project/src/main.cpp": "mylib"}
        source, target = map_object_to_source(obj_path, build_dir, file_index)
        assert source == "/project/src/main.cpp"
        assert target == "mylib"

    def test_no_match_returns_target_name(self, tmp_path):
        build_dir = tmp_path / "build"
        obj_dir = build_dir / "CMakeFiles" / "mylib.dir" / "src"
        obj_dir.mkdir(parents=True)
        obj_path = obj_dir / "unknown.cpp.o"
        obj_path.touch()

        source, target = map_object_to_source(obj_path, build_dir, {})
        assert source is None
        assert target == "mylib"


class TestCountLinesPython:
    def test_basic_count(self, tmp_path):
        src = tmp_path / "test.cpp"
        src.write_text("// comment\n\nint main() {\n  /* block comment */\n  return 0;\n}\n")
        result = count_lines_python(str(src))
        assert result["blank_lines"] == 1
        assert result["comment_lines"] == 2  # // comment and /* block */
        assert result["code_lines"] == 3  # int main, return, }

    def test_block_comment(self, tmp_path):
        src = tmp_path / "test.cpp"
        src.write_text("/* multi\n   line\n   comment */\nint x;\n")
        result = count_lines_python(str(src))
        assert result["comment_lines"] == 3
        assert result["code_lines"] == 1

    def test_nonexistent_file(self):
        result = count_lines_python("/nonexistent/file.cpp")
        assert result["code_lines"] == 0
        assert result["blank_lines"] == 0
