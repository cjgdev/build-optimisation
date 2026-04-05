"""Tests for buildanalysis.contributors."""

import pandas as pd

from buildanalysis.contributors import (
    build_contributor_target_matrix,
    cluster_contributors_hierarchical,
    cluster_contributors_nmf,
    compute_bus_factor,
    compute_ownership,
    normalise_to_distributions,
)


def make_commits_df() -> pd.DataFrame:
    """Contributor-target commit data with two natural clusters."""
    return pd.DataFrame(
        {
            "contributor": [
                # Team A: works on target_1 and target_2
                "alice@co.com",
                "alice@co.com",
                "alice@co.com",
                "bob@co.com",
                "bob@co.com",
                "bob@co.com",
                # Team B: works on target_3 and target_4
                "carol@co.com",
                "carol@co.com",
                "carol@co.com",
                "dave@co.com",
                "dave@co.com",
                "dave@co.com",
                # Drive-by contributor (below threshold)
                "eve@co.com",
            ],
            "cmake_target": [
                "target_1",
                "target_2",
                "target_1",
                "target_1",
                "target_2",
                "target_2",
                "target_3",
                "target_4",
                "target_3",
                "target_3",
                "target_4",
                "target_4",
                "target_1",
            ],
            "commit_count": [
                10,
                8,
                5,
                7,
                12,
                3,
                15,
                6,
                4,
                9,
                11,
                7,
                1,
            ],
        }
    )


class TestBuildContributorTargetMatrix:
    def test_basic(self):
        df = make_commits_df()
        matrix = build_contributor_target_matrix(df, min_contributor_commits=5, min_target_commits=5)
        # Eve should be filtered out (only 1 commit)
        assert "eve@co.com" not in matrix.index
        assert len(matrix) == 4  # alice, bob, carol, dave

    def test_target_filtering(self):
        df = make_commits_df()
        # Set threshold so high only heavily-committed targets pass
        matrix = build_contributor_target_matrix(df, min_contributor_commits=1, min_target_commits=30)
        assert len(matrix.columns) <= 2  # only target_1 and target_3 have enough

    def test_values(self):
        df = make_commits_df()
        matrix = build_contributor_target_matrix(df, min_contributor_commits=1, min_target_commits=1)
        # Alice's commits to target_1: 10 + 5 = 15
        assert matrix.loc["alice@co.com", "target_1"] == 15


class TestNormaliseToDistributions:
    def test_rows_sum_to_one(self):
        df = make_commits_df()
        matrix = build_contributor_target_matrix(df, min_contributor_commits=5, min_target_commits=5)
        normed = normalise_to_distributions(matrix)
        for _, row in normed.iterrows():
            assert abs(row.sum() - 1.0) < 1e-10

    def test_zero_row_stays_zero(self):
        matrix = pd.DataFrame({"a": [0, 1], "b": [0, 2]}, index=["x", "y"])
        normed = normalise_to_distributions(matrix)
        assert normed.loc["x"].sum() == 0


class TestClusterContributorsHierarchical:
    def test_returns_structure(self):
        df = make_commits_df()
        matrix = build_contributor_target_matrix(df, min_contributor_commits=5, min_target_commits=5)
        result = cluster_contributors_hierarchical(matrix, cut_levels=[2])
        assert "linkage_matrix" in result
        assert "dendrogram_data" in result
        assert 2 in result["assignments"]
        assert len(result["assignments"][2]) == len(matrix)

    def test_two_clusters_separate_teams(self):
        df = make_commits_df()
        matrix = build_contributor_target_matrix(df, min_contributor_commits=5, min_target_commits=5)
        result = cluster_contributors_hierarchical(matrix, cut_levels=[2])
        assignments = result["assignments"][2]
        # Alice and Bob should be in the same cluster, Carol and Dave in another
        alice_cluster = assignments.loc[assignments["contributor"] == "alice@co.com", "cluster_id"].iloc[0]
        bob_cluster = assignments.loc[assignments["contributor"] == "bob@co.com", "cluster_id"].iloc[0]
        carol_cluster = assignments.loc[assignments["contributor"] == "carol@co.com", "cluster_id"].iloc[0]
        assert alice_cluster == bob_cluster
        assert alice_cluster != carol_cluster


class TestClusterContributorsNMF:
    def test_returns_structure(self):
        df = make_commits_df()
        matrix = build_contributor_target_matrix(df, min_contributor_commits=5, min_target_commits=5)
        result = cluster_contributors_nmf(matrix, k_range=range(2, 4))
        assert "results" in result
        assert "best_k" in result
        assert len(result["results"]) > 0

    def test_result_shapes(self):
        df = make_commits_df()
        matrix = build_contributor_target_matrix(df, min_contributor_commits=5, min_target_commits=5)
        result = cluster_contributors_nmf(matrix, k_range=range(2, 4))
        for r in result["results"]:
            assert r["W"].shape[0] == len(matrix)
            assert r["W"].shape[1] == r["k"]
            assert r["H"].shape[0] == r["k"]
            assert r["H"].shape[1] == len(matrix.columns)


class TestComputeOwnership:
    def test_normalised_scores_sum_to_one(self):
        commits_df = make_commits_df()
        groups_df = pd.DataFrame(
            {
                "contributor": ["alice@co.com", "bob@co.com", "carol@co.com", "dave@co.com"],
                "group_id": [0, 0, 1, 1],
            }
        )
        ownership = compute_ownership(commits_df, groups_df)
        for target, group in ownership.groupby("cmake_target"):
            total = group["ownership_normalised"].sum()
            assert abs(total - 1.0) < 1e-10, f"Target {target} scores sum to {total}"

    def test_dominant_group(self):
        commits_df = make_commits_df()
        groups_df = pd.DataFrame(
            {
                "contributor": ["alice@co.com", "bob@co.com", "carol@co.com", "dave@co.com"],
                "group_id": [0, 0, 1, 1],
            }
        )
        ownership = compute_ownership(commits_df, groups_df)
        # target_1 should be dominated by group 0 (Alice + Bob)
        t1 = ownership[ownership["cmake_target"] == "target_1"]
        assert len(t1) > 0
        dominant = t1.loc[t1["ownership_normalised"].idxmax()]
        assert dominant["group_id"] == 0


class TestComputeBusFactor:
    def test_counts_contributors(self):
        detail_df = pd.DataFrame(
            {
                "contributor": ["alice@co.com", "bob@co.com", "alice@co.com"],
                "cmake_target": ["t1", "t1", "t1"],
                "commit_date": ["2024-06-01", "2024-06-15", "2024-07-01"],
            }
        )
        groups_df = pd.DataFrame(
            {
                "contributor": ["alice@co.com", "bob@co.com"],
                "group_id": [0, 0],
            }
        )
        bus = compute_bus_factor(detail_df, groups_df, recent_months=6)
        assert len(bus) == 1
        assert bus.iloc[0]["bus_factor"] == 2  # alice and bob
