"""Configurable team structure, email resolution, and ownership analysis.

Provides YAML-driven team configuration that maps git email addresses to
canonical team membership, enabling team-aware ownership and coupling analysis.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

UNAFFILIATED_TEAM = "__unaffiliated__"


@dataclass(frozen=True)
class TeamMember:
    """A person with one or more git email aliases."""

    name: str
    emails: frozenset[str]
    team: str  # Team name, or UNAFFILIATED_TEAM


@dataclass
class TeamConfig:
    """Organisational team structure loaded from YAML.

    Provides reverse-lookup indices for resolving git emails to canonical
    identities and team membership.
    """

    teams: dict[str, list[TeamMember]]
    email_to_member: dict[str, TeamMember]
    email_to_team: dict[str, str]
    team_modules: dict[str, list[str]]
    unaffiliated: list[TeamMember]

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_yaml(cls, path: Path) -> TeamConfig:
        """Load and validate a teams.yaml configuration file."""
        with open(path) as f:
            raw = yaml.safe_load(f)

        teams: dict[str, list[TeamMember]] = {}
        email_to_member: dict[str, TeamMember] = {}
        email_to_team: dict[str, str] = {}
        team_modules: dict[str, list[str]] = {}
        seen_emails: dict[str, str] = {}  # email → "team/member" for error messages

        for team_entry in raw.get("teams", []):
            team_name = team_entry.get("name", "").strip()
            if not team_name:
                raise ValueError("Team name must be non-empty.")

            members_raw = team_entry.get("members", [])
            if not members_raw:
                raise ValueError(f"Team '{team_name}' has zero members.")

            modules = team_entry.get("modules", [])
            team_modules[team_name] = modules

            members: list[TeamMember] = []
            for member_entry in members_raw:
                member_name = member_entry.get("name", "").strip()
                if not member_name:
                    raise ValueError(f"Member name must be non-empty in team '{team_name}'.")

                emails_raw = member_entry.get("emails", [])
                if not emails_raw:
                    raise ValueError(f"Member '{member_name}' in team '{team_name}' has no email addresses.")

                for email in emails_raw:
                    if not email or not isinstance(email, str):
                        raise ValueError(f"Invalid email for '{member_name}' in team '{team_name}'.")
                    if email in seen_emails:
                        raise ValueError(f"Duplicate email '{email}' — already used by {seen_emails[email]}.")
                    seen_emails[email] = f"{team_name}/{member_name}"

                member = TeamMember(
                    name=member_name,
                    emails=frozenset(emails_raw),
                    team=team_name,
                )
                members.append(member)

                for email in emails_raw:
                    email_to_member[email] = member
                    email_to_team[email] = team_name

            teams[team_name] = members

        # Unaffiliated contributors
        unaffiliated: list[TeamMember] = []
        for entry in raw.get("unaffiliated", []):
            member_name = entry.get("name", "").strip()
            emails_raw = entry.get("emails", [])

            for email in emails_raw:
                if email in seen_emails:
                    raise ValueError(f"Duplicate email '{email}' — already used by {seen_emails[email]}.")
                seen_emails[email] = f"unaffiliated/{member_name}"

            member = TeamMember(
                name=member_name,
                emails=frozenset(emails_raw),
                team=UNAFFILIATED_TEAM,
            )
            unaffiliated.append(member)

            for email in emails_raw:
                email_to_member[email] = member
                # Deliberately NOT adding to email_to_team — unaffiliated has no team

        return cls(
            teams=teams,
            email_to_member=email_to_member,
            email_to_team=email_to_team,
            team_modules=team_modules,
            unaffiliated=unaffiliated,
        )

    # -- Query methods ------------------------------------------------------

    def resolve_contributor(self, email: str) -> Optional[TeamMember]:
        """Map a git email address to a canonical team member.

        Returns None for unknown email addresses.
        """
        return self.email_to_member.get(email)

    def resolve_team(self, email: str) -> Optional[str]:
        """Map a git email address to a team name.

        Returns None for unknown or unaffiliated email addresses.
        """
        return self.email_to_team.get(email)

    def team_names(self) -> list[str]:
        """Return all team names in alphabetical order."""
        return sorted(self.teams.keys())

    def members_of(self, team_name: str) -> list[TeamMember]:
        """Return all members of a given team."""
        return self.teams.get(team_name, [])

    def all_known_emails(self) -> set[str]:
        """Return every email address in the configuration (teams + unaffiliated)."""
        return set(self.email_to_member.keys())


# ---------------------------------------------------------------------------
# Git log enrichment
# ---------------------------------------------------------------------------


def resolve_git_contributors(
    git_log: pd.DataFrame,
    team_config: TeamConfig,
) -> pd.DataFrame:
    """Enrich a git commit log with canonical identities.

    Adds columns: canonical_name, team, is_resolved.
    The original ``contributor`` column is preserved.
    """
    result = git_log.copy()

    canonical_names = []
    teams = []
    is_resolved = []

    for email in result["contributor"]:
        member = team_config.resolve_contributor(email)
        if member is not None:
            canonical_names.append(member.name)
            team = team_config.resolve_team(email)
            teams.append(team)
            is_resolved.append(True)
        else:
            canonical_names.append(None)
            teams.append(None)
            is_resolved.append(False)

    result["canonical_name"] = canonical_names
    result["team"] = teams
    result["is_resolved"] = is_resolved

    # Log resolution summary
    unique_emails = result["contributor"].nunique()
    resolved_df = result.drop_duplicates(subset=["contributor"])
    n_resolved_team = resolved_df["team"].notna().sum()
    n_resolved_unaffiliated = (resolved_df["is_resolved"] & resolved_df["team"].isna()).sum()
    n_unresolved = (~resolved_df["is_resolved"]).sum()

    logger.info(
        "Git contributor resolution: %d unique emails — "
        "%d (%.1f%%) resolved to team, "
        "%d (%.1f%%) unaffiliated, "
        "%d (%.1f%%) unresolved",
        unique_emails,
        n_resolved_team,
        100 * n_resolved_team / max(unique_emails, 1),
        n_resolved_unaffiliated,
        100 * n_resolved_unaffiliated / max(unique_emails, 1),
        n_unresolved,
        100 * n_unresolved / max(unique_emails, 1),
    )

    # Top unresolved emails
    if n_unresolved > 0:
        unresolved = result[~result["is_resolved"]]
        top_unresolved = unresolved.groupby("contributor").size().sort_values(ascending=False).head(10)
        logger.info("Top unresolved emails by commit count:\n%s", top_unresolved.to_string())

    return result


# ---------------------------------------------------------------------------
# Team-aware ownership analysis
# ---------------------------------------------------------------------------


def compute_target_ownership(
    git_log: pd.DataFrame,
    file_to_target: pd.Series,
    team_config: TeamConfig,
) -> pd.DataFrame:
    """Compute team-level ownership for each target.

    Parameters
    ----------
    git_log:
        Git commit log with contributor column.
    file_to_target:
        Series mapping source_file → cmake_target.
    team_config:
        Team configuration for resolving emails.

    Returns
    -------
    DataFrame with one row per target containing ownership metrics.
    """
    # Enrich the git log
    enriched = resolve_git_contributors(git_log, team_config)

    # Map files to targets
    enriched = enriched.copy()
    enriched["cmake_target"] = enriched["source_file"].map(file_to_target)
    enriched = enriched.dropna(subset=["cmake_target"])

    rows = []
    for target, group in enriched.groupby("cmake_target"):
        total_commits = len(group)

        # Team-level aggregation
        team_commits = group.groupby("team", dropna=False).size()
        # Handle NaN keys properly
        unresolved_mask = team_commits.index.isna()
        if unresolved_mask.any():
            unresolved_count = int(team_commits[unresolved_mask].sum())
        else:
            unresolved_count = 0

        known_team_commits = team_commits[team_commits.index.notna()]

        if len(known_team_commits) > 0:
            owning_team = known_team_commits.idxmax()
            owning_team_count = known_team_commits.max()
            owning_team_share = owning_team_count / total_commits
            team_count = len(known_team_commits)

            # HHI
            shares = known_team_commits / total_commits
            ownership_hhi = float((shares**2).sum())
        else:
            owning_team = None
            owning_team_share = 0.0
            team_count = 0
            ownership_hhi = 0.0

        cross_team_fraction = 1.0 - owning_team_share

        # Top individual contributor (canonical)
        contributor_col = "canonical_name" if "canonical_name" in group.columns else "contributor"
        contributor_counts = group.groupby(contributor_col, dropna=False).size()
        # Use canonical_name if available, fall back
        if contributor_counts.index.notna().any():
            named = contributor_counts[contributor_counts.index.notna()]
            top_contributor = named.idxmax()
            top_contributor_count = named.max()
        else:
            top_contributor = None
            top_contributor_count = 0

        top_contributor_share = top_contributor_count / total_commits if total_commits > 0 else 0.0

        # Look up team of top contributor
        top_contributor_team = None
        if top_contributor is not None:
            # Find any email for this contributor
            for email, member in team_config.email_to_member.items():
                if member.name == top_contributor:
                    top_contributor_team = team_config.resolve_team(email)
                    break

        # Unique canonical contributors
        canonical = group["canonical_name"].dropna().unique()
        raw_contributors = group.loc[group["canonical_name"].isna(), "contributor"].unique()
        contributor_count = len(canonical) + len(raw_contributors)

        unresolved_fraction = unresolved_count / total_commits if total_commits > 0 else 0.0

        rows.append(
            {
                "cmake_target": target,
                "owning_team": owning_team,
                "owning_team_share": owning_team_share,
                "contributor_count": contributor_count,
                "team_count": team_count,
                "total_commits": total_commits,
                "ownership_hhi": ownership_hhi,
                "cross_team_fraction": cross_team_fraction,
                "top_contributor": top_contributor,
                "top_contributor_team": top_contributor_team,
                "top_contributor_share": top_contributor_share,
                "unresolved_fraction": unresolved_fraction,
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "cmake_target",
                "owning_team",
                "owning_team_share",
                "contributor_count",
                "team_count",
                "total_commits",
                "ownership_hhi",
                "cross_team_fraction",
                "top_contributor",
                "top_contributor_team",
                "top_contributor_share",
                "unresolved_fraction",
            ]
        )

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# File-level ownership
# ---------------------------------------------------------------------------


def compute_file_ownership(
    git_log: pd.DataFrame,
    team_config: TeamConfig,
    file_to_target: Optional[pd.Series] = None,
    target: Optional[str] = None,
) -> pd.DataFrame:
    """Compute per-file team ownership.

    Parameters
    ----------
    git_log:
        Git commit log with contributor column.
    team_config:
        Team configuration.
    file_to_target:
        Optional Series mapping source_file → cmake_target.
    target:
        If provided, only files belonging to this target are included.
    """
    enriched = resolve_git_contributors(git_log, team_config)

    if file_to_target is not None:
        enriched = enriched.copy()
        enriched["cmake_target"] = enriched["source_file"].map(file_to_target)
    elif "cmake_target" not in enriched.columns:
        enriched["cmake_target"] = None

    if target is not None:
        enriched = enriched[enriched["cmake_target"] == target]

    rows = []
    for source_file, group in enriched.groupby("source_file"):
        total_commits = len(group)
        team_commits = group.groupby("team", dropna=False).size()
        known = team_commits[team_commits.index.notna()]

        if len(known) > 0:
            owning_team = known.idxmax()
            owning_team_share = float(known.max() / total_commits)
            team_count = len(known)
        else:
            owning_team = None
            owning_team_share = 0.0
            team_count = 0

        cmake_target = group["cmake_target"].iloc[0] if "cmake_target" in group.columns else None

        rows.append(
            {
                "source_file": source_file,
                "cmake_target": cmake_target,
                "owning_team": owning_team,
                "owning_team_share": owning_team_share,
                "team_count": team_count,
                "total_commits": total_commits,
                "is_cross_team": team_count > 1,
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "source_file",
                "cmake_target",
                "owning_team",
                "owning_team_share",
                "team_count",
                "total_commits",
                "is_cross_team",
            ]
        )

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Team coupling matrix
# ---------------------------------------------------------------------------


def compute_team_coupling(
    edge_list: pd.DataFrame,
    target_ownership: pd.DataFrame,
) -> pd.DataFrame:
    """Compute dependency coupling between teams.

    Parameters
    ----------
    edge_list:
        DataFrame with source_target and dest_target columns.
    target_ownership:
        DataFrame with cmake_target and owning_team columns.
    """
    ownership_map = target_ownership.set_index("cmake_target")["owning_team"].to_dict()

    edges = edge_list.copy()
    edges["team_a"] = edges["source_target"].map(ownership_map)
    edges["team_b"] = edges["dest_target"].map(ownership_map)

    # Drop edges where either team is unknown
    edges = edges.dropna(subset=["team_a", "team_b"])

    if edges.empty:
        return pd.DataFrame(
            columns=[
                "team_a",
                "team_b",
                "edge_count",
                "public_edge_count",
                "target_pairs",
            ]
        )

    grouped = edges.groupby(["team_a", "team_b"])

    rows = []
    for (team_a, team_b), group in grouped:
        edge_count = len(group)

        # Count PUBLIC edges if visibility column exists
        if "cmake_visibility" in group.columns:
            public_edge_count = int((group["cmake_visibility"] == "PUBLIC").sum())
        else:
            public_edge_count = 0

        target_pairs = group[["source_target", "dest_target"]].drop_duplicates().shape[0]

        rows.append(
            {
                "team_a": team_a,
                "team_b": team_b,
                "edge_count": edge_count,
                "public_edge_count": public_edge_count,
                "target_pairs": target_pairs,
            }
        )

    return pd.DataFrame(rows)
