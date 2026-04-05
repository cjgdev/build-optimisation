"""Tests for configurable team structure (REQ-01)."""

import textwrap

import pandas as pd
import pytest

from buildanalysis.teams import (
    TeamConfig,
    compute_file_ownership,
    compute_target_ownership,
    compute_team_coupling,
    resolve_git_contributors,
)


@pytest.fixture
def sample_yaml(tmp_path):
    """Write a sample teams.yaml and return its path."""
    content = textwrap.dedent("""
    teams:
      - name: "Alpha"
        modules: ["Base", "Core"]
        members:
          - name: "Alice"
            emails: ["alice@co.com", "alice@old.com"]
          - name: "Bob"
            emails: ["bob@co.com"]
      - name: "Beta"
        members:
          - name: "Carol"
            emails: ["carol@co.com"]
          - name: "Dan"
            emails: ["dan@co.com", "daniel@co.com"]
    unaffiliated:
      - name: "Eve"
        emails: ["eve@external.com"]
    """)
    path = tmp_path / "teams.yaml"
    path.write_text(content)
    return path


@pytest.fixture
def team_config(sample_yaml):
    return TeamConfig.from_yaml(sample_yaml)


class TestTeamConfigLoading:
    def test_loads_teams(self, team_config):
        assert set(team_config.team_names()) == {"Alpha", "Beta"}

    def test_member_count(self, team_config):
        assert len(team_config.members_of("Alpha")) == 2
        assert len(team_config.members_of("Beta")) == 2

    def test_email_resolution(self, team_config):
        member = team_config.resolve_contributor("alice@co.com")
        assert member is not None
        assert member.name == "Alice"
        assert member.team == "Alpha"

    def test_alias_resolution(self, team_config):
        """Different emails for the same person resolve to the same member."""
        m1 = team_config.resolve_contributor("alice@co.com")
        m2 = team_config.resolve_contributor("alice@old.com")
        assert m1 == m2

    def test_team_resolution(self, team_config):
        assert team_config.resolve_team("bob@co.com") == "Alpha"
        assert team_config.resolve_team("carol@co.com") == "Beta"

    def test_unknown_email(self, team_config):
        assert team_config.resolve_contributor("unknown@co.com") is None
        assert team_config.resolve_team("unknown@co.com") is None

    def test_unaffiliated_resolves_member_but_no_team(self, team_config):
        member = team_config.resolve_contributor("eve@external.com")
        assert member is not None
        assert member.name == "Eve"
        assert team_config.resolve_team("eve@external.com") is None

    def test_all_known_emails(self, team_config):
        emails = team_config.all_known_emails()
        assert "alice@co.com" in emails
        assert "alice@old.com" in emails
        assert "eve@external.com" in emails
        assert len(emails) == 7  # 2 + 1 + 1 + 2 + 1

    def test_team_modules(self, team_config):
        assert team_config.team_modules["Alpha"] == ["Base", "Core"]
        assert team_config.team_modules.get("Beta", []) == []

    def test_duplicate_email_raises(self, tmp_path):
        content = textwrap.dedent("""
        teams:
          - name: "A"
            members:
              - name: "Person1"
                emails: ["same@co.com"]
          - name: "B"
            members:
              - name: "Person2"
                emails: ["same@co.com"]
        """)
        path = tmp_path / "bad.yaml"
        path.write_text(content)
        with pytest.raises(ValueError, match="[Dd]uplicate"):
            TeamConfig.from_yaml(path)

    def test_empty_team_raises(self, tmp_path):
        content = textwrap.dedent("""
        teams:
          - name: "Empty"
            members: []
        """)
        path = tmp_path / "bad.yaml"
        path.write_text(content)
        with pytest.raises(ValueError):
            TeamConfig.from_yaml(path)

    def test_members_of_unknown_team(self, team_config):
        assert team_config.members_of("NonExistent") == []


class TestGitLogEnrichment:
    def test_resolve_known_contributors(self, team_config):
        git_log = pd.DataFrame(
            {
                "commit_hash": ["c1", "c2", "c3"],
                "contributor": ["alice@co.com", "bob@co.com", "unknown@co.com"],
                "source_file": ["/a.cpp", "/b.cpp", "/c.cpp"],
                "timestamp": pd.to_datetime(["2024-01-01"] * 3),
                "lines_added": [10, 20, 30],
                "lines_deleted": [1, 2, 3],
            }
        )

        result = resolve_git_contributors(git_log, team_config)

        assert "canonical_name" in result.columns
        assert "team" in result.columns
        assert "is_resolved" in result.columns

        alice_row = result[result["contributor"] == "alice@co.com"].iloc[0]
        assert alice_row["canonical_name"] == "Alice"
        assert alice_row["team"] == "Alpha"
        assert alice_row["is_resolved"] == True  # noqa: E712

        unknown_row = result[result["contributor"] == "unknown@co.com"].iloc[0]
        assert unknown_row["canonical_name"] is None or pd.isna(unknown_row["canonical_name"])
        assert unknown_row["is_resolved"] == False  # noqa: E712

    def test_original_contributor_preserved(self, team_config):
        git_log = pd.DataFrame(
            {
                "commit_hash": ["c1"],
                "contributor": ["alice@old.com"],
                "source_file": ["/a.cpp"],
                "timestamp": pd.to_datetime(["2024-01-01"]),
                "lines_added": [10],
                "lines_deleted": [1],
            }
        )

        result = resolve_git_contributors(git_log, team_config)
        assert result.iloc[0]["contributor"] == "alice@old.com"
        assert result.iloc[0]["canonical_name"] == "Alice"


class TestTargetOwnership:
    def test_single_team_ownership(self, team_config):
        git_log = pd.DataFrame(
            {
                "commit_hash": ["c1", "c2", "c3", "c4", "c5"],
                "contributor": ["alice@co.com"] * 3 + ["bob@co.com"] * 2,
                "source_file": ["/src/a.cpp"] * 5,
                "timestamp": pd.to_datetime(["2024-01-01"] * 5),
                "lines_added": [10] * 5,
                "lines_deleted": [1] * 5,
            }
        )
        file_to_target = pd.Series({"/src/a.cpp": "target_a"})

        result = compute_target_ownership(git_log, file_to_target, team_config)

        row = result[result["cmake_target"] == "target_a"].iloc[0]
        assert row["owning_team"] == "Alpha"
        assert row["owning_team_share"] == 1.0
        assert row["cross_team_fraction"] == 0.0
        assert row["ownership_hhi"] == 1.0

    def test_shared_ownership(self, team_config):
        git_log = pd.DataFrame(
            {
                "commit_hash": ["c1", "c2", "c3", "c4"],
                "contributor": ["alice@co.com", "alice@co.com", "carol@co.com", "carol@co.com"],
                "source_file": ["/src/a.cpp"] * 4,
                "timestamp": pd.to_datetime(["2024-01-01"] * 4),
                "lines_added": [10] * 4,
                "lines_deleted": [1] * 4,
            }
        )
        file_to_target = pd.Series({"/src/a.cpp": "target_a"})

        result = compute_target_ownership(git_log, file_to_target, team_config)

        row = result[result["cmake_target"] == "target_a"].iloc[0]
        assert row["team_count"] == 2
        assert row["cross_team_fraction"] == 0.5
        assert row["ownership_hhi"] == pytest.approx(0.5)  # 0.5^2 + 0.5^2

    def test_hhi_range(self, team_config):
        """HHI should always be between 1/N and 1.0."""
        git_log = pd.DataFrame(
            {
                "commit_hash": [f"c{i}" for i in range(10)],
                "contributor": ["alice@co.com"] * 5 + ["carol@co.com"] * 3 + ["dan@co.com"] * 2,
                "source_file": ["/src/a.cpp"] * 10,
                "timestamp": pd.to_datetime(["2024-01-01"] * 10),
                "lines_added": [10] * 10,
                "lines_deleted": [1] * 10,
            }
        )
        file_to_target = pd.Series({"/src/a.cpp": "target_a"})

        result = compute_target_ownership(git_log, file_to_target, team_config)
        row = result.iloc[0]
        assert 0 < row["ownership_hhi"] <= 1.0


class TestTeamCoupling:
    def test_basic_coupling(self):
        edge_list = pd.DataFrame(
            {
                "source_target": ["t1", "t2"],
                "dest_target": ["t3", "t3"],
                "is_direct": [True, True],
            }
        )
        target_ownership = pd.DataFrame(
            {
                "cmake_target": ["t1", "t2", "t3"],
                "owning_team": ["Alpha", "Alpha", "Beta"],
            }
        )

        result = compute_team_coupling(edge_list, target_ownership)

        cross = result[(result["team_a"] == "Alpha") & (result["team_b"] == "Beta")]
        assert len(cross) == 1
        assert cross.iloc[0]["edge_count"] == 2

    def test_self_coupling(self):
        edge_list = pd.DataFrame(
            {
                "source_target": ["t1"],
                "dest_target": ["t2"],
                "is_direct": [True],
            }
        )
        target_ownership = pd.DataFrame(
            {
                "cmake_target": ["t1", "t2"],
                "owning_team": ["Alpha", "Alpha"],
            }
        )

        result = compute_team_coupling(edge_list, target_ownership)

        self_coupling = result[(result["team_a"] == "Alpha") & (result["team_b"] == "Alpha")]
        assert len(self_coupling) == 1
        assert self_coupling.iloc[0]["edge_count"] == 1


class TestFileOwnership:
    def test_basic_file_ownership(self, team_config):
        git_log = pd.DataFrame(
            {
                "commit_hash": ["c1", "c2", "c3"],
                "contributor": ["alice@co.com", "alice@co.com", "carol@co.com"],
                "source_file": ["/src/a.cpp", "/src/a.cpp", "/src/a.cpp"],
                "timestamp": pd.to_datetime(["2024-01-01"] * 3),
                "lines_added": [10] * 3,
                "lines_deleted": [1] * 3,
            }
        )
        file_to_target = pd.Series({"/src/a.cpp": "target_a"})

        result = compute_file_ownership(git_log, team_config, file_to_target=file_to_target)

        row = result[result["source_file"] == "/src/a.cpp"].iloc[0]
        assert row["owning_team"] == "Alpha"
        assert row["is_cross_team"] == True  # noqa: E712
        assert row["team_count"] == 2
