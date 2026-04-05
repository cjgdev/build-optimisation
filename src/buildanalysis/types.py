"""Core type definitions for build analysis."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

import networkx as nx
import pandas as pd

if TYPE_CHECKING:
    from buildanalysis.teams import TeamConfig

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FileOrigin(Enum):
    """Origin of a source file — handwritten or generated.

    The current data pipeline only provides a boolean ``is_generated`` flag.
    The richer variants (GENERATED_PROTOBUF, etc.) are reserved for future use
    when generator type becomes determinable from file paths or metadata.
    """

    HANDWRITTEN = auto()
    GENERATED = auto()

    # Future: uncomment when generator type is available in the data.
    # GENERATED_PROTOBUF = auto()
    # GENERATED_GSOAP = auto()
    # GENERATED_XSD2CPP = auto()
    # GENERATED_SWAGGER = auto()
    # GENERATED_INHOUSE = auto()
    # GENERATED_OTHER = auto()

    @classmethod
    def from_file_metrics(cls, is_generated: bool, file_path: str = "") -> FileOrigin:
        """Map from the current data representation.

        Parameters
        ----------
        is_generated:
            Boolean flag from ``file_metrics.parquet``.
        file_path:
            Source file path — reserved for future heuristic classification
            of generator type.
        """
        return cls.GENERATED if is_generated else cls.HANDWRITTEN


class TargetType(Enum):
    """CMake target types matching values in ``target_metrics.parquet``."""

    EXECUTABLE = "executable"
    STATIC_LIBRARY = "static_library"
    SHARED_LIBRARY = "shared_library"
    MODULE_LIBRARY = "module_library"
    OBJECT_LIBRARY = "object_library"
    INTERFACE_LIBRARY = "interface_library"
    CUSTOM_TARGET = "custom_target"

    @classmethod
    def from_str(cls, value: str) -> TargetType:
        """Look up a TargetType by its string value."""
        return cls(value)


# ---------------------------------------------------------------------------
# Analysis scope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnalysisScope:
    """Filter for restricting analyses to a subset of the codebase."""

    targets: frozenset[str] | None = None
    teams: frozenset[str] | None = None
    files: frozenset[str] | None = None
    label: str = "global"

    def filter_targets(self, df: pd.DataFrame, col: str = "cmake_target") -> pd.DataFrame:
        """Filter a DataFrame to rows matching this scope's targets."""
        if self.targets is None:
            return df
        return df[df[col].isin(self.targets)]

    def filter_files(self, df: pd.DataFrame, col: str = "source_file") -> pd.DataFrame:
        """Filter a DataFrame to rows matching this scope's files."""
        if self.files is None:
            return df
        return df[df[col].isin(self.files)]

    def is_global(self) -> bool:
        """True if no filters are applied."""
        return self.targets is None and self.teams is None and self.files is None

    @classmethod
    def for_team(
        cls,
        team_name: str,
        team_config: TeamConfig,
        target_ownership: pd.DataFrame,
    ) -> AnalysisScope:
        """Create a scope restricting to targets owned by a team.

        Parameters
        ----------
        team_name:
            Team name from teams.yaml.
        team_config:
            Loaded TeamConfig (used for validation only).
        target_ownership:
            DataFrame with ``cmake_target`` and ``owning_team`` columns.
        """
        owned = target_ownership.loc[target_ownership["owning_team"] == team_name, "cmake_target"]
        return cls(
            targets=frozenset(owned),
            teams=frozenset([team_name]),
            label=f"team:{team_name}",
        )


# ---------------------------------------------------------------------------
# Build graph container
# ---------------------------------------------------------------------------


@dataclass
class BuildGraph:
    """Dependency graph with target metadata.

    Edge convention: A -> B means "A depends on B" (A builds after B).
    ``graph.successors(A)`` returns A's direct dependencies.
    """

    graph: nx.DiGraph
    target_metadata: pd.DataFrame  # Indexed by cmake_target

    @property
    def n_targets(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def n_edges(self) -> int:
        return self.graph.number_of_edges()

    def subgraph(self, scope: AnalysisScope) -> BuildGraph:
        """Extract scoped subgraph with full transitive dependencies included.

        Collects all transitive dependencies (successors, since A->B means
        A depends on B) of the scoped targets so the result is a buildable subset.
        """
        if scope.is_global():
            return self

        seed = scope.targets if scope.targets is not None else frozenset(self.graph.nodes())
        nodes: set[str] = set()
        for t in seed:
            if t in self.graph:
                nodes.add(t)
                nodes |= nx.descendants(self.graph, t)

        sub_g = self.graph.subgraph(nodes).copy()
        sub_meta = self.target_metadata.loc[self.target_metadata.index.intersection(nodes)]
        return BuildGraph(graph=sub_g, target_metadata=sub_meta)

    def targets_of_type(self, target_type: TargetType) -> list[str]:
        """Return all targets of a given type."""
        mask = self.target_metadata["target_type"] == target_type.value
        return list(self.target_metadata.index[mask])

    def executables(self) -> list[str]:
        """Return all executable targets."""
        return self.targets_of_type(TargetType.EXECUTABLE)
