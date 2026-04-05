"""Snapshot management for tracking build analysis over time.

Provides structured snapshot directories with metadata, creation,
loading, and comparison capabilities.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from buildanalysis.loading import BuildDataset

import yaml

logger = logging.getLogger(__name__)

_LABEL_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")


# ---------------------------------------------------------------------------
# Snapshot metadata
# ---------------------------------------------------------------------------


@dataclass
class SnapshotMetadata:
    """Metadata describing a snapshot's context."""

    label: str
    date: str  # ISO 8601 date
    git_ref: str
    git_branch: str
    build_config: str
    compiler: str
    compiler_flags: str
    core_count: int
    build_machine: Optional[str]
    notes: str
    interventions_applied: list[str] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path) -> SnapshotMetadata:
        """Load from a metadata.yaml file."""
        with open(path) as f:
            raw = yaml.safe_load(f)
        return cls(
            label=raw["label"],
            date=raw["date"],
            git_ref=raw["git_ref"],
            git_branch=raw["git_branch"],
            build_config=raw["build_config"],
            compiler=raw["compiler"],
            compiler_flags=raw.get("compiler_flags", ""),
            core_count=raw["core_count"],
            build_machine=raw.get("build_machine"),
            notes=raw.get("notes", ""),
            interventions_applied=raw.get("interventions_applied", []),
        )

    def to_yaml(self, path: Path) -> None:
        """Write to a metadata.yaml file."""
        data = {
            "label": self.label,
            "date": self.date,
            "git_ref": self.git_ref,
            "git_branch": self.git_branch,
            "build_config": self.build_config,
            "compiler": self.compiler,
            "compiler_flags": self.compiler_flags,
            "core_count": self.core_count,
            "build_machine": self.build_machine,
            "notes": self.notes,
            "interventions_applied": self.interventions_applied,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)


# ---------------------------------------------------------------------------
# Snapshot manager
# ---------------------------------------------------------------------------


class SnapshotManager:
    """Manages snapshot directories under a root snapshots folder."""

    def __init__(self, snapshots_dir: Path):
        self.snapshots_dir = Path(snapshots_dir)

    def list_snapshots(self) -> list[SnapshotMetadata]:
        """List all snapshots in chronological order by date."""
        if not self.snapshots_dir.exists():
            return []

        snapshots = []
        for child in self.snapshots_dir.iterdir():
            if not child.is_dir():
                continue
            if child.name == "latest":
                continue
            meta_path = child / "metadata.yaml"
            if meta_path.exists():
                snapshots.append(SnapshotMetadata.from_yaml(meta_path))

        return sorted(snapshots, key=lambda s: s.date)

    def get_snapshot_path(self, label: str) -> Path:
        """Get the directory path for a named snapshot."""
        return self.snapshots_dir / label

    def get_baseline(self) -> Optional[Path]:
        """Get the baseline snapshot path (label starting with 'baseline')."""
        for snap in self.list_snapshots():
            if snap.label.startswith("baseline"):
                return self.snapshots_dir / snap.label
        return None

    def get_latest(self) -> Optional[Path]:
        """Get the most recent snapshot path (by date)."""
        snapshots = self.list_snapshots()
        if not snapshots:
            return None
        # Check for 'latest' symlink first
        latest_link = self.snapshots_dir / "latest"
        if latest_link.exists():
            return latest_link.resolve()
        # Fall back to most recent by date
        return self.snapshots_dir / snapshots[-1].label

    def create_snapshot(
        self,
        source_dir: Path,
        label: str,
        metadata: SnapshotMetadata,
    ) -> Path:
        """Copy processed data to a new snapshot directory.

        Creates the directory, copies parquet files, writes metadata,
        and updates the 'latest' symlink.
        """
        # Validate label
        if not label:
            raise ValueError("Snapshot label must be non-empty.")
        if not _LABEL_PATTERN.match(label):
            raise ValueError(
                f"Invalid label '{label}'. Must contain only alphanumeric, "
                f"hyphens, underscores, and not start with a number."
            )

        snapshot_dir = self.snapshots_dir / label
        if snapshot_dir.exists():
            raise ValueError(f"Snapshot '{label}' already exists at {snapshot_dir}.")

        # Create directories
        processed_dir = snapshot_dir / "processed"
        processed_dir.mkdir(parents=True, exist_ok=True)

        # Copy parquet files
        source_dir = Path(source_dir)
        file_count = 0
        total_size = 0
        for pq_file in source_dir.glob("*.parquet"):
            dest = processed_dir / pq_file.name
            shutil.copy2(pq_file, dest)
            file_count += 1
            total_size += pq_file.stat().st_size

        # Write metadata
        metadata.to_yaml(snapshot_dir / "metadata.yaml")

        # Update latest symlink
        latest_link = self.snapshots_dir / "latest"
        if latest_link.is_symlink() or latest_link.exists():
            latest_link.unlink()
        try:
            latest_link.symlink_to(snapshot_dir.name)
        except OSError:
            pass  # Symlinks may not be supported on all platforms

        logger.info(
            "Created snapshot '%s': %d files, %.1f MB → %s",
            label,
            file_count,
            total_size / 1e6,
            snapshot_dir,
        )

        return snapshot_dir

    def load_dataset(self, label: str) -> "BuildDataset":
        """Load a BuildDataset from a named snapshot."""
        from buildanalysis.loading import BuildDataset

        snapshot_dir = self.snapshots_dir / label
        processed_dir = snapshot_dir / "processed"
        if not processed_dir.exists():
            raise FileNotFoundError(f"No processed directory in snapshot '{label}' at {processed_dir}")
        return BuildDataset(processed_dir, validate=False)

    def load_pair(self, label_a: str, label_b: str) -> tuple:
        """Load two snapshots for comparison."""
        return self.load_dataset(label_a), self.load_dataset(label_b)

    def load_all(self) -> list[tuple[SnapshotMetadata, "BuildDataset"]]:
        """Load all snapshots for trend analysis. Ordered chronologically."""
        result = []
        for meta in self.list_snapshots():
            ds = self.load_dataset(meta.label)
            result.append((meta, ds))
        return result
