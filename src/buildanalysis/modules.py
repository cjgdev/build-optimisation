"""Configurable module structure, assignment, dependency graph, and metrics.

Maps CMake targets to declared architectural modules via directory prefixes
and target name patterns, enabling module-level dependency analysis and
structural alignment comparison.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import networkx as nx
import pandas as pd
import yaml

from buildanalysis.types import BuildGraph

logger = logging.getLogger(__name__)

VALID_CATEGORIES = frozenset({"shared", "domain", "infrastructure", "test"})
UNASSIGNED_MODULE = "Unassigned"

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Module:
    """A declared architectural module."""

    name: str
    description: str
    category: str  # shared | domain | infrastructure | test
    owning_team: Optional[str]
    directories: tuple[str, ...]
    target_patterns: tuple[str, ...]


@dataclass
class ModuleConfig:
    """Module configuration loaded from YAML.

    Provides target-to-module assignment via pattern and directory matching.
    """

    modules: list[Module]
    _dir_to_module: dict[str, str] = field(repr=False)  # sorted by prefix length desc

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_yaml(cls, path: Path) -> ModuleConfig:
        """Load and validate a modules.yaml configuration file."""
        with open(path) as f:
            raw = yaml.safe_load(f)

        modules: list[Module] = []
        seen_names: set[str] = set()
        all_dirs: list[tuple[str, str]] = []  # (directory, module_name)

        for entry in raw.get("modules", []):
            name = entry.get("name", "").strip()
            if not name:
                raise ValueError("Module name must be non-empty.")
            if name in seen_names:
                raise ValueError(f"Duplicate module name '{name}'.")
            seen_names.add(name)

            category = entry.get("category", "").strip()
            if category not in VALID_CATEGORIES:
                raise ValueError(
                    f"Invalid category '{category}' for module '{name}'. "
                    f"Must be one of: {', '.join(sorted(VALID_CATEGORIES))}."
                )

            directories = tuple(entry.get("directories", []))
            target_patterns = tuple(entry.get("target_patterns", []))
            description = entry.get("description", "")
            owning_team = entry.get("owning_team")

            # Collect directories for overlap check
            for d in directories:
                all_dirs.append((d, name))

            modules.append(
                Module(
                    name=name,
                    description=description,
                    category=category,
                    owning_team=owning_team,
                    directories=directories,
                    target_patterns=target_patterns,
                )
            )

        # Check for overlapping directory prefixes
        _check_directory_overlaps(all_dirs)

        # Build directory-to-module mapping, sorted by prefix length desc
        dir_to_module: dict[str, str] = {}
        for d, mod_name in sorted(all_dirs, key=lambda x: len(x[0]), reverse=True):
            dir_to_module[d] = mod_name

        return cls(modules=modules, _dir_to_module=dir_to_module)

    # -- Query methods ------------------------------------------------------

    def assign_target(self, target_name: str, source_directory: str) -> Optional[str]:
        """Assign a target to a module.

        Priority:
        1. Target name matches a module's target_patterns (fnmatch)
        2. Source directory matches a module's directories (longest prefix)
        3. None if no match
        """
        # 1. Pattern match (first matching pattern wins)
        for module in self.modules:
            for pattern in module.target_patterns:
                if fnmatch.fnmatch(target_name, pattern):
                    return module.name

        # 2. Longest directory prefix match
        for prefix, mod_name in self._dir_to_module.items():
            if source_directory.startswith(prefix):
                return mod_name

        return None

    def assign_all_targets(self, target_metrics: pd.DataFrame) -> pd.DataFrame:
        """Add 'module' and 'module_category' columns to target_metrics.

        Parameters
        ----------
        target_metrics:
            Must have 'cmake_target' and 'source_directory' columns.

        Returns a copy with two new columns.
        """
        result = target_metrics.copy()
        modules_col = []
        categories_col = []

        for _, row in result.iterrows():
            target = row["cmake_target"]
            source_dir = row["source_directory"] if "source_directory" in row.index else ""
            if pd.isna(source_dir):
                source_dir = ""

            mod_name = self.assign_target(target, source_dir)
            modules_col.append(mod_name)

            if mod_name is not None:
                mod = self.get_module(mod_name)
                categories_col.append(mod.category if mod else None)
            else:
                categories_col.append(None)

        result["module"] = modules_col
        result["module_category"] = categories_col

        # Log summary
        assigned = result["module"].notna()
        per_module = result.loc[assigned].groupby("module").size()
        unassigned_count = (~assigned).sum()

        logger.info("Module assignment: %d targets assigned, %d unassigned", assigned.sum(), unassigned_count)
        for mod_name, count in per_module.items():
            logger.info("  %s: %d targets", mod_name, count)

        if unassigned_count > 0:
            unassigned_targets = result.loc[~assigned, "cmake_target"].tolist()
            logger.info("Unassigned targets: %s", unassigned_targets[:20])

        return result

    def get_module(self, name: str) -> Optional[Module]:
        """Look up a module by name."""
        for m in self.modules:
            if m.name == name:
                return m
        return None

    @property
    def module_names(self) -> list[str]:
        """All module names."""
        return [m.name for m in self.modules]

    @property
    def domain_modules(self) -> list[Module]:
        """Modules with category 'domain'."""
        return [m for m in self.modules if m.category == "domain"]

    @property
    def shared_modules(self) -> list[Module]:
        """Modules with category 'shared'."""
        return [m for m in self.modules if m.category == "shared"]


def _check_directory_overlaps(all_dirs: list[tuple[str, str]]) -> None:
    """Raise ValueError if any directory is a prefix of another in a different module."""
    for i, (dir_a, mod_a) in enumerate(all_dirs):
        for j, (dir_b, mod_b) in enumerate(all_dirs):
            if i >= j or mod_a == mod_b:
                continue
            if dir_a.startswith(dir_b) or dir_b.startswith(dir_a):
                raise ValueError(
                    f"Overlapping directories between modules '{mod_a}' and '{mod_b}': '{dir_a}' and '{dir_b}'."
                )


# ---------------------------------------------------------------------------
# Module-level dependency graph
# ---------------------------------------------------------------------------


def build_module_dependency_graph(
    bg: BuildGraph,
    module_assignments: pd.DataFrame,
) -> nx.DiGraph:
    """Aggregate target-level dependency graph to module level.

    Parameters
    ----------
    bg:
        Target-level build graph.
    module_assignments:
        DataFrame with 'cmake_target', 'module', and 'module_category' columns.

    Returns a DiGraph where nodes are module names.
    """
    # Build target → module mapping
    if "cmake_target" in module_assignments.columns:
        target_to_module = module_assignments.set_index("cmake_target")["module"].to_dict()
    else:
        target_to_module = module_assignments["module"].to_dict()

    # Fill unassigned
    for node in bg.graph.nodes():
        if node not in target_to_module or pd.isna(target_to_module.get(node)):
            target_to_module[node] = UNASSIGNED_MODULE

    # Build module-level category map
    module_category = {}
    if "module_category" in module_assignments.columns:
        for _, row in module_assignments.iterrows():
            mod = row.get("module")
            cat = row.get("module_category")
            if mod and not pd.isna(mod):
                module_category[mod] = cat
    module_category[UNASSIGNED_MODULE] = "unknown"

    # Aggregate edges
    mod_graph = nx.DiGraph()

    # Add all module nodes
    all_modules = set(target_to_module.values())
    for mod in all_modules:
        mod_graph.add_node(mod, category=module_category.get(mod, "unknown"))

    # Aggregate target-level edges into module-level edges
    edge_data: dict[tuple[str, str], dict] = {}
    for src, dst in bg.graph.edges():
        mod_src = target_to_module.get(src, UNASSIGNED_MODULE)
        mod_dst = target_to_module.get(dst, UNASSIGNED_MODULE)

        key = (mod_src, mod_dst)
        if key not in edge_data:
            edge_data[key] = {"weight": 0, "public_count": 0, "private_count": 0}

        edge_data[key]["weight"] += 1

        # Check visibility if available in graph edge data
        e_data = bg.graph.edges[src, dst]
        vis = e_data.get("cmake_visibility", "unknown")
        if vis == "PUBLIC":
            edge_data[key]["public_count"] += 1
        elif vis == "PRIVATE":
            edge_data[key]["private_count"] += 1

    for (mod_src, mod_dst), data in edge_data.items():
        is_self = mod_src == mod_dst
        # Cross-category: both are domain modules
        src_cat = module_category.get(mod_src, "unknown")
        dst_cat = module_category.get(mod_dst, "unknown")
        is_cross_category = not is_self and src_cat == "domain" and dst_cat == "domain"

        # Check bidirectionality
        is_bidirectional = (mod_dst, mod_src) in edge_data

        mod_graph.add_edge(
            mod_src,
            mod_dst,
            weight=data["weight"],
            public_count=data["public_count"],
            private_count=data["private_count"],
            is_cross_category=is_cross_category,
            is_bidirectional=is_bidirectional,
        )

    return mod_graph


# ---------------------------------------------------------------------------
# Module-level metrics
# ---------------------------------------------------------------------------


def compute_module_metrics(
    bg: BuildGraph,
    module_assignments: pd.DataFrame,
    target_metrics: pd.DataFrame,
    critical_path_targets: set[str] | None = None,
    total_targets: int | None = None,
) -> pd.DataFrame:
    """Compute aggregate metrics per module.

    Parameters
    ----------
    bg:
        Target-level build graph.
    module_assignments:
        DataFrame with cmake_target, module, module_category columns.
    target_metrics:
        Target metrics DataFrame (may have various metric columns).
    critical_path_targets:
        Optional set of target names on the critical path.
    total_targets:
        Optional total target count for computing build_fraction.
    """
    # Merge module assignments into target_metrics
    if "module" not in target_metrics.columns:
        assignment_map = module_assignments.set_index("cmake_target")[["module", "module_category"]]
        tm = target_metrics.merge(assignment_map, left_on="cmake_target", right_index=True, how="left")
    else:
        tm = target_metrics.copy()

    tm["module"] = tm["module"].fillna(UNASSIGNED_MODULE)

    # Build target → module map
    target_to_module = tm.set_index("cmake_target")["module"].to_dict()

    rows = []
    for module_name, group in tm.groupby("module"):
        targets_in_module = set(group["cmake_target"])

        # Count internal vs external deps
        internal_deps = 0
        external_deps = 0
        for src in targets_in_module:
            if src in bg.graph:
                for dst in bg.graph.successors(src):
                    dst_mod = target_to_module.get(dst, UNASSIGNED_MODULE)
                    if dst_mod == module_name:
                        internal_deps += 1
                    else:
                        external_deps += 1

        total_deps = internal_deps + external_deps
        self_containment = internal_deps / total_deps if total_deps > 0 else 1.0

        # Modules that depend on this one
        dependant_modules = set()
        dependency_modules = set()
        for src, dst in bg.graph.edges():
            src_mod = target_to_module.get(src, UNASSIGNED_MODULE)
            dst_mod = target_to_module.get(dst, UNASSIGNED_MODULE)
            if dst_mod == module_name and src_mod != module_name:
                dependant_modules.add(src_mod)
            if src_mod == module_name and dst_mod != module_name:
                dependency_modules.add(dst_mod)

        # Get module info
        mod_category = group["module_category"].iloc[0] if "module_category" in group.columns else "unknown"
        owning_team = None
        if "owning_team" in group.columns:
            owning_team = group["owning_team"].iloc[0]

        # Aggregate metrics with safe defaults
        def _safe_sum(col):
            if col in group.columns:
                return int(group[col].sum())
            return 0

        def _safe_mean(col):
            if col in group.columns:
                return float(group[col].mean())
            return 0.0

        target_count = len(group)
        executable_count = int((group["target_type"] == "executable").sum()) if "target_type" in group.columns else 0
        library_count = target_count - executable_count

        rows.append(
            {
                "module": module_name,
                "category": mod_category if not pd.isna(mod_category) else "unknown",
                "owning_team": owning_team,
                "target_count": target_count,
                "executable_count": executable_count,
                "library_count": library_count,
                "file_count": _safe_sum("file_count"),
                "total_sloc": _safe_sum("code_lines_total"),
                "total_build_time_ms": _safe_sum("total_build_time_ms"),
                "total_compile_time_ms": _safe_sum("compile_time_sum_ms"),
                "total_link_time_ms": _safe_sum("link_time_ms"),
                "codegen_ratio": _safe_mean("codegen_ratio"),
                "internal_dep_count": internal_deps,
                "external_dep_count": external_deps,
                "self_containment": self_containment,
                "dependant_module_count": len(dependant_modules),
                "dependency_module_count": len(dependency_modules),
                "critical_path_target_count": (
                    sum(1 for t in targets_in_module if t in critical_path_targets)
                    if critical_path_targets is not None
                    else 0
                ),
                "build_fraction": (
                    target_count / total_targets if total_targets is not None and total_targets > 0 else 0.0
                ),
            }
        )

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Structural vs Module alignment
# ---------------------------------------------------------------------------


def compare_communities_to_modules(
    communities: pd.DataFrame,
    module_assignments: pd.DataFrame,
) -> dict:
    """Measure alignment between discovered communities and declared modules.

    Parameters
    ----------
    communities:
        DataFrame with cmake_target and community columns.
    module_assignments:
        DataFrame with cmake_target and module columns.
    """
    from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

    # Merge on cmake_target
    merged = communities.merge(
        module_assignments[["cmake_target", "module"]],
        on="cmake_target",
        how="inner",
    )
    merged = merged.dropna(subset=["module", "community"])

    if len(merged) == 0:
        return {
            "adjusted_rand_index": 0.0,
            "normalized_mutual_info": 0.0,
            "n_targets_compared": 0,
            "alignment_by_module": {},
            "fragmented_modules": [],
            "merged_communities": [],
        }

    ari = adjusted_rand_score(merged["module"], merged["community"])
    nmi = normalized_mutual_info_score(merged["module"], merged["community"])

    # Per-module alignment
    alignment_by_module = {}
    fragmented_modules = []
    for mod_name, mod_group in merged.groupby("module"):
        comm_counts = mod_group["community"].value_counts()
        dominant_comm = comm_counts.index[0]
        dominant_fraction = comm_counts.iloc[0] / len(mod_group)
        alignment_by_module[mod_name] = {
            "dominant_community": int(dominant_comm),
            "fraction_in_dominant": float(dominant_fraction),
        }
        if len(comm_counts) >= 3:
            fragmented_modules.append(mod_name)

    # Communities spanning 3+ modules
    merged_communities = []
    for comm_id, comm_group in merged.groupby("community"):
        n_modules = comm_group["module"].nunique()
        if n_modules >= 3:
            merged_communities.append(int(comm_id))

    return {
        "adjusted_rand_index": float(ari),
        "normalized_mutual_info": float(nmi),
        "n_targets_compared": len(merged),
        "alignment_by_module": alignment_by_module,
        "fragmented_modules": fragmented_modules,
        "merged_communities": merged_communities,
    }


# ---------------------------------------------------------------------------
# Feature configurations from modules
# ---------------------------------------------------------------------------


def build_module_feature_configs(
    bg: BuildGraph,
    module_assignments: pd.DataFrame,
    timing: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Compute build cost of enabling each module as a feature.

    Parameters
    ----------
    bg:
        Target-level build graph.
    module_assignments:
        DataFrame with cmake_target and module columns.
    timing:
        Optional DataFrame with cmake_target and total_build_time_ms.
    """
    # Build target → module mapping
    target_to_module = module_assignments.set_index("cmake_target")["module"].to_dict()

    # Build timing map
    timing_map = {}
    if timing is not None:
        timing_map = timing.set_index("cmake_target")["total_build_time_ms"].to_dict()

    total_targets = bg.graph.number_of_nodes()
    total_build_time = sum(timing_map.values()) if timing_map else None

    # Module category map
    mod_category = {}
    if "module_category" in module_assignments.columns:
        for _, row in module_assignments.iterrows():
            mod = row.get("module")
            cat = row.get("module_category")
            if mod and not pd.isna(mod):
                mod_category[mod] = cat

    # Find shared module names
    shared_modules = {m for m, c in mod_category.items() if c == "shared"}

    # For each module, compute transitive build set
    rows = []
    all_module_build_sets = {}

    for module_name in set(target_to_module.values()):
        if pd.isna(module_name):
            continue

        own_targets = {t for t, m in target_to_module.items() if m == module_name}

        # Compute transitive dependencies
        build_set = set(own_targets)
        for t in own_targets:
            if t in bg.graph:
                build_set |= nx.descendants(bg.graph, t)

        all_module_build_sets[module_name] = build_set

        transitive_dep_targets = len(build_set) - len(own_targets)
        total_build_set = len(build_set)
        build_fraction = total_build_set / total_targets if total_targets > 0 else 0.0

        # Timing
        est_time = None
        est_time_fraction = None
        if timing_map:
            est_time = sum(timing_map.get(t, 0) for t in build_set)
            est_time_fraction = est_time / total_build_time if total_build_time else None

        # Shared core targets in build set
        shared_core_targets = sum(1 for t in build_set if target_to_module.get(t) in shared_modules)
        shared_core_fraction = shared_core_targets / total_build_set if total_build_set > 0 else 0.0

        rows.append(
            {
                "module": module_name,
                "category": mod_category.get(module_name, "unknown"),
                "own_targets": len(own_targets),
                "transitive_dep_targets": transitive_dep_targets,
                "total_build_set": total_build_set,
                "build_fraction": build_fraction,
                "estimated_build_time_ms": est_time,
                "estimated_build_time_fraction": est_time_fraction,
                "shared_core_targets": shared_core_targets,
                "shared_core_fraction": shared_core_fraction,
            }
        )

    return pd.DataFrame(rows)
