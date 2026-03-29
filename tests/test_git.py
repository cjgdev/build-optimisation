import pandas as pd
import numpy as np
import pytest

from buildanalysis.git import (
    compute_cochange_matrix,
    compute_file_churn,
    compute_ownership_concentration,
)


class TestFileChurn:
    def test_basic(self, synthetic_git_log):
        churn = compute_file_churn(synthetic_git_log)
        assert len(churn) == 4  # 4 unique files
        # /src/a.cpp appears in commits c1, c2, c3 = 3 commits
        a_row = churn[churn["source_file"] == "/src/a.cpp"].iloc[0]
        assert a_row["n_commits"] == 3
        assert a_row["total_lines_added"] == 10 + 20 + 15  # 45
        assert a_row["total_churn"] == a_row["total_lines_added"] + a_row["total_lines_deleted"]

    def test_sorted_by_commits(self, synthetic_git_log):
        churn = compute_file_churn(synthetic_git_log)
        assert churn["n_commits"].is_monotonic_decreasing

    def test_scope_filter(self, synthetic_git_log):
        from buildanalysis.types import AnalysisScope
        scope = AnalysisScope(files=frozenset(["/src/a.cpp", "/src/b.cpp"]))
        churn = compute_file_churn(synthetic_git_log, scope=scope)
        assert len(churn) == 2


class TestCochange:
    def test_file_level(self, synthetic_git_log):
        result = compute_cochange_matrix(
            synthetic_git_log, level="file", min_cochanges=2
        )
        # a.cpp and b.cpp co-change in c1, c2, c3 = 3 times
        ab_row = result[
            ((result["item_a"] == "/src/a.cpp") & (result["item_b"] == "/src/b.cpp")) |
            ((result["item_a"] == "/src/b.cpp") & (result["item_b"] == "/src/a.cpp"))
        ]
        assert len(ab_row) == 1
        assert ab_row.iloc[0]["cochange_count"] == 3
        # PMI should be positive (they co-change more than chance)
        assert ab_row.iloc[0]["pmi"] > 0

    def test_max_commit_size_filter(self, synthetic_git_log):
        # With max_commit_size=2, commit c2 (3 files) should be excluded
        result = compute_cochange_matrix(
            synthetic_git_log, level="file", min_cochanges=1, max_commit_size=2
        )
        # a and b co-change in c1 and c3 only (c2 filtered)
        ab_row = result[
            ((result["item_a"] == "/src/a.cpp") & (result["item_b"] == "/src/b.cpp")) |
            ((result["item_a"] == "/src/b.cpp") & (result["item_b"] == "/src/a.cpp"))
        ]
        assert ab_row.iloc[0]["cochange_count"] == 2

    def test_min_cochanges_filter(self, synthetic_git_log):
        result = compute_cochange_matrix(
            synthetic_git_log, level="file", min_cochanges=5
        )
        # No pair has 5+ co-changes in this small dataset
        assert len(result) == 0

    def test_target_level(self, synthetic_git_log):
        file_to_target = pd.Series({
            "/src/a.cpp": "target_a",
            "/src/b.cpp": "target_a",  # Same target
            "/src/c.cpp": "target_b",
            "/src/d.cpp": "target_c",
        })
        result = compute_cochange_matrix(
            synthetic_git_log,
            file_to_target=file_to_target,
            level="target",
            min_cochanges=1,
        )
        # target_a and target_b should co-change (via c2: a.cpp, b.cpp, c.cpp)
        assert len(result) > 0

    def test_jaccard_range(self, synthetic_git_log):
        result = compute_cochange_matrix(
            synthetic_git_log, level="file", min_cochanges=1
        )
        assert (result["jaccard"] >= 0).all()
        assert (result["jaccard"] <= 1).all()


class TestOwnership:
    def test_basic(self, synthetic_git_log):
        file_to_target = pd.Series({
            "/src/a.cpp": "target_a",
            "/src/b.cpp": "target_a",
            "/src/c.cpp": "target_b",
            "/src/d.cpp": "target_c",
        })
        result = compute_ownership_concentration(synthetic_git_log, file_to_target)
        assert len(result) > 0
        assert (result["gini"] >= 0).all()
        assert (result["gini"] <= 1).all()
        assert (result["top_contributor_share"] > 0).all()
        assert (result["top_contributor_share"] <= 1).all()
