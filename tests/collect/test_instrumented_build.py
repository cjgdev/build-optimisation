"""Tests for header tree parser from step 03 and detect_and_parse integration."""

import importlib

from buildanalysis.compiler_timing import detect_and_parse

_mod = importlib.import_module("scripts.collect.03_instrumented_build")
parse_header_tree_text = _mod.parse_header_tree_text


SAMPLE_FTIME_REPORT = """\
Time variable                                   usr           sys          wall               GGC
 phase setup                                :   0.00 (  0%)   0.00 (  0%)   0.00 (  0%)    1363 kB (  1%)
 phase parsing                              :   0.12 ( 14%)   0.01 ( 25%)   0.13 ( 14%)    8027 kB ( 10%)
 phase lang. deferred                       :   0.01 (  1%)   0.00 (  0%)   0.01 (  1%)     116 kB (  0%)
 phase opt and generate                     :   0.72 ( 85%)   0.03 ( 75%)   0.72 ( 84%)   68433 kB ( 89%)
 TOTAL                                      :   0.85          0.04          0.86           76939 kB
"""

SAMPLE_HEADER_OUTPUT = """\
. /usr/include/c++/12/iostream
.. /usr/include/c++/12/ostream
... /usr/include/c++/12/ios
.... /usr/include/c++/12/iosfwd
..... /usr/include/c++/12/bits/stringfwd.h
. /usr/include/c++/12/string
.. /usr/include/c++/12/bits/char_traits.h
"""


class TestDetectAndParseIntegration:
    """Smoke tests verifying detect_and_parse works from the collect script context."""

    def test_gcc_report_detected(self):
        report = detect_and_parse(SAMPLE_FTIME_REPORT)
        assert report is not None
        assert report.compiler == "gcc"
        assert report.wall_total_ms == 860

    def test_to_dict_has_expected_keys(self):
        report = detect_and_parse(SAMPLE_FTIME_REPORT)
        assert report is not None
        d = report.to_dict()
        assert "compiler" in d
        assert "phases" in d
        assert "total" in d
        assert "wall_total_ms" in d


class TestParseHeaderTree:
    def test_extracts_headers(self):
        result = parse_header_tree_text(SAMPLE_HEADER_OUTPUT)
        assert result["total_includes"] == 7
        assert result["unique_headers"] == 7

    def test_max_depth(self):
        result = parse_header_tree_text(SAMPLE_HEADER_OUTPUT)
        assert result["max_include_depth"] == 5

    def test_header_tree_structure(self):
        result = parse_header_tree_text(SAMPLE_HEADER_OUTPUT)
        tree = result["header_tree"]
        assert tree[0] == [1, "/usr/include/c++/12/iostream"]
        assert tree[1] == [2, "/usr/include/c++/12/ostream"]

    def test_empty_input(self):
        result = parse_header_tree_text("")
        assert result["max_include_depth"] == 0
        assert result["unique_headers"] == 0
        assert result["total_includes"] == 0

    def test_duplicate_headers(self):
        text = ". /usr/include/a.h\n.. /usr/include/b.h\n. /usr/include/a.h\n"
        result = parse_header_tree_text(text)
        assert result["total_includes"] == 3
        assert result["unique_headers"] == 2  # a.h counted once
