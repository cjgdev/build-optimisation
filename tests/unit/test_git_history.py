"""Tests for git history parsing."""

import importlib

_mod = importlib.import_module("scripts.collect.02_git_history")
parse_git_log = _mod.parse_git_log
summarise = _mod.summarise


SAMPLE_GIT_LOG = """\
COMMIT:abc123def456|2024-06-15T10:30:00+00:00|Alice|Fix bug in parser
3\t1\tsrc/core/types.cpp
10\t5\tsrc/core/assert.cpp

COMMIT:789012fed345|2024-07-20T14:00:00+00:00|Bob|Refactor logging
0\t2\tsrc/core/types.cpp
20\t8\tsrc/logging/logger.cpp

COMMIT:aabbccdd1122|2024-08-01T09:00:00+00:00|Alice|Update types
5\t0\tsrc/core/types.cpp
"""


class TestParseGitLog:
    def test_parses_all_records(self):
        records = parse_git_log(SAMPLE_GIT_LOG, "/repo")
        assert len(records) == 5

    def test_commit_metadata(self):
        records = parse_git_log(SAMPLE_GIT_LOG, "/repo")
        first = records[0]
        assert first["commit_hash"] == "abc123def456"
        assert first["author"] == "Alice"
        assert "2024-06-15" in first["commit_date"]

    def test_numstat_values(self):
        records = parse_git_log(SAMPLE_GIT_LOG, "/repo")
        first = records[0]
        assert first["lines_added"] == 3
        assert first["lines_deleted"] == 1

    def test_path_resolution(self):
        records = parse_git_log(SAMPLE_GIT_LOG, "/repo")
        # All paths should be absolute
        for r in records:
            assert r["source_file"].startswith("/"), f"Not absolute: {r['source_file']}"

    def test_handles_binary_files(self):
        log = "COMMIT:abc|2024-01-01|Alice|test\n-\t-\timage.png\n1\t0\tcode.cpp\n"
        records = parse_git_log(log, "/repo")
        # Binary files should be skipped
        assert len(records) == 1
        assert records[0]["source_file"].endswith("code.cpp")


class TestSummarise:
    def test_aggregation(self):
        records = parse_git_log(SAMPLE_GIT_LOG, "/repo")
        summaries = summarise(records)

        # Find the types.cpp summary (touched in 3 commits)
        types_summary = [s for s in summaries if s["source_file"].endswith("types.cpp")]
        assert len(types_summary) == 1
        s = types_summary[0]
        assert s["commit_count"] == 3
        assert s["total_lines_added"] == 3 + 0 + 5  # 8
        assert s["total_lines_deleted"] == 1 + 2 + 0  # 3
        assert s["total_churn"] == 11
        assert s["distinct_authors"] == 2  # Alice and Bob

    def test_date_range(self):
        records = parse_git_log(SAMPLE_GIT_LOG, "/repo")
        summaries = summarise(records)

        types_summary = [s for s in summaries if s["source_file"].endswith("types.cpp")][0]
        assert "2024-06-15" in types_summary["first_change_date"]
        assert "2024-08-01" in types_summary["last_change_date"]
