"""Tests for scripts/collect/05_preprocessed_size.py pure functions."""

import importlib

mod = importlib.import_module("scripts.collect.05_preprocessed_size")
modify_command_for_preprocess = mod.modify_command_for_preprocess


class TestModifyCommandForPreprocess:
    def test_inserts_E_flag(self):
        result = modify_command_for_preprocess("/usr/bin/g++ -c main.cpp -o main.o")
        assert "-E" in result
        assert "-o" not in result

    def test_strips_output_flag(self):
        result = modify_command_for_preprocess("/usr/bin/g++ -c main.cpp -o output.o")
        assert "output.o" not in result

    def test_strips_ftime_report(self):
        result = modify_command_for_preprocess("/usr/bin/g++ -ftime-report -c main.cpp -o main.o")
        assert "-ftime-report" not in result

    def test_strips_H_flag(self):
        result = modify_command_for_preprocess("/usr/bin/g++ -H -c main.cpp -o main.o")
        assert "' -H'" not in result  # Should not contain bare -H

    def test_strips_capture_stderr(self):
        result = modify_command_for_preprocess("/path/to/capture_stderr.sh /usr/bin/g++ -c main.cpp -o main.o")
        assert "capture_stderr" not in result
