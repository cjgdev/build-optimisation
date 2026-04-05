"""Intervention scoring and prioritisation for build optimisation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

import pandas as pd

from buildanalysis.build import CriticalPathResult, whatif_remove_edge
from buildanalysis.types import BuildGraph


class InterventionType(Enum):
    SPLIT_TARGET = auto()
    REMOVE_DEPENDENCY = auto()
    NARROW_VISIBILITY = auto()
    REFACTOR_HEADER = auto()
    ADD_PCH = auto()
    FORWARD_DECLARE = auto()
    CACHE_CODEGEN = auto()
    EXTRACT_INTERFACE = auto()


@dataclass
class Intervention:
    intervention_type: InterventionType
    description: str
    targets_affected: list[str]
    estimated_build_time_reduction_ms: float
    estimated_effort_days: float
    confidence: float
    team: str | None = None
    module: str | None = None
    category: str = "medium"
    rationale: str = ""


def score_header_interventions(
    header_impact: pd.DataFrame,
    include_amplification: pd.DataFrame,
    top_n: int = 20,
) -> list[Intervention]:
    """Generate header refactoring recommendations from header analysis.

    Impact heuristic: transitive_fan_in * source_size_bytes * 0.3 / 1e6.
    The 0.3 factor assumes ~30% of preprocessed contribution can be reduced
    via splitting, forward declarations, or pimpl. The /1e6 is an approximate
    conversion to milliseconds.

    Effort heuristic: direct_fan_in * 0.5 days, clamped to [0.5, 20].
    """
    top_headers = header_impact.head(top_n)
    interventions: list[Intervention] = []

    for _, row in top_headers.iterrows():
        fan_in = row["transitive_fan_in"]
        size_bytes = row["source_size_bytes"]
        direct_fan_in = row["direct_fan_in"]

        impact_ms = fan_in * size_bytes * 0.3 / 1e6
        if impact_ms == 0:
            continue
        effort = max(0.5, min(20.0, direct_fan_in * 0.5))

        n_commits = row.get("n_commits", 0)
        rationale_parts = [f"Header has transitive fan-in of {fan_in}"]
        if n_commits:
            rationale_parts.append(f"changes {n_commits} times")
        rationale_parts.append(f"size {size_bytes} bytes")

        interventions.append(
            Intervention(
                intervention_type=InterventionType.REFACTOR_HEADER,
                description=f"Split/simplify {row['file']}",
                targets_affected=[],
                estimated_build_time_reduction_ms=impact_ms,
                estimated_effort_days=effort,
                confidence=0.4 + 0.2 * min(1.0, fan_in / 500),
                rationale=". ".join(rationale_parts) + ".",
            )
        )

    return interventions


def score_dependency_interventions(
    bg: BuildGraph,
    timing: pd.DataFrame,
    critical_path_result: CriticalPathResult,
    edge_list: pd.DataFrame,
    top_n: int = 20,
) -> list[Intervention]:
    """Generate dependency removal/narrowing recommendations."""
    cp_set = set(critical_path_result.path)
    has_visibility = "cmake_visibility" in edge_list.columns

    candidates: list[dict] = []
    for _, row in edge_list.iterrows():
        source = row["source_target"]
        dependency = row["dest_target"]
        on_cp = source in cp_set and dependency in cp_set
        is_public = has_visibility and row.get("cmake_visibility") == "PUBLIC"

        if not on_cp and not is_public:
            continue

        result = whatif_remove_edge(bg, timing, source, dependency)
        if not result["is_valid"] or result["delta_ms"] >= 0:
            continue

        source_files = 1
        if "n_source_files" in timing.columns:
            match = timing[timing["cmake_target"] == source]
            if len(match):
                source_files = max(1, int(match.iloc[0].get("n_source_files", 1)))

        candidates.append(
            {
                "source": source,
                "dependency": dependency,
                "delta_ms": result["delta_ms"],
                "on_cp": on_cp,
                "is_public": is_public,
                "source_files": source_files,
            }
        )

    candidates.sort(key=lambda c: c["delta_ms"])
    candidates = candidates[:top_n]

    interventions: list[Intervention] = []
    for c in candidates:
        if c["is_public"]:
            itype = InterventionType.NARROW_VISIBILITY
            desc = f"Change {c['source']} → {c['dependency']} from PUBLIC to PRIVATE"
        else:
            itype = InterventionType.REMOVE_DEPENDENCY
            desc = f"Remove dependency {c['source']} → {c['dependency']}"

        effort = max(0.5, min(10.0, c["source_files"] * 0.1))
        confidence = 0.7 if c["on_cp"] else 0.6

        interventions.append(
            Intervention(
                intervention_type=itype,
                description=desc,
                targets_affected=[c["source"], c["dependency"]],
                estimated_build_time_reduction_ms=abs(c["delta_ms"]),
                estimated_effort_days=effort,
                confidence=confidence,
                rationale=f"Removing this edge saves ~{abs(c['delta_ms']):.0f}ms on the critical path.",
            )
        )

    return interventions


def score_target_split_interventions(
    target_metrics: pd.DataFrame,
    critical_path_result: CriticalPathResult,
    top_n: int = 10,
) -> list[Intervention]:
    """Recommend splitting large targets on the critical path."""
    cp_set = set(critical_path_result.path)

    time_col = "total_build_time_ms" if "total_build_time_ms" in target_metrics.columns else "compile_time_sum_ms"
    file_count_col = "n_source_files" if "n_source_files" in target_metrics.columns else None

    cp_targets = target_metrics[target_metrics["cmake_target"].isin(cp_set)].copy()
    if cp_targets.empty:
        return []

    cp_targets = cp_targets.sort_values(time_col, ascending=False).head(top_n)

    interventions: list[Intervention] = []
    for _, row in cp_targets.iterrows():
        compile_time = row[time_col]
        n_files = int(row[file_count_col]) if file_count_col and file_count_col in row.index else 10

        if n_files < 4:
            continue

        impact_ms = compile_time * 0.4
        effort = max(1.0, min(30.0, n_files * 0.3))

        interventions.append(
            Intervention(
                intervention_type=InterventionType.SPLIT_TARGET,
                description=f"Split {row['cmake_target']} ({n_files} files)",
                targets_affected=[row["cmake_target"]],
                estimated_build_time_reduction_ms=impact_ms,
                estimated_effort_days=effort,
                confidence=0.5,
                rationale=(
                    f"Target is on the critical path with {compile_time:.0f}ms build time "
                    f"and {n_files} source files. Splitting could allow parallel compilation."
                ),
            )
        )

    return interventions


def _categorise_effort(effort_days: float) -> str:
    """Classify intervention effort into quick_win, medium, or strategic."""
    if effort_days < 2:
        return "quick_win"
    if effort_days <= 10:
        return "medium"
    return "strategic"


def build_pareto_frontier(interventions: list[Intervention]) -> pd.DataFrame:
    """Identify Pareto-optimal interventions on the impact-vs-effort plane.

    Intervention A dominates B if A.impact >= B.impact AND A.effort <= B.effort
    and at least one inequality is strict.
    """
    records = [
        {
            "type": iv.intervention_type.name,
            "description": iv.description,
            "impact_ms": iv.estimated_build_time_reduction_ms,
            "effort_days": iv.estimated_effort_days,
            "confidence": iv.confidence,
            "team": iv.team,
            "module": iv.module,
            "rationale": iv.rationale,
            "targets_affected": iv.targets_affected,
        }
        for iv in interventions
    ]
    if not records:
        cols = [
            "type",
            "description",
            "impact_ms",
            "effort_days",
            "confidence",
            "team",
            "module",
            "rationale",
            "targets_affected",
            "pareto_optimal",
            "category",
        ]
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(records)

    pareto = []
    for i in range(len(df)):
        dominated = False
        for j in range(len(df)):
            if i == j:
                continue
            if (
                df.iloc[j]["impact_ms"] >= df.iloc[i]["impact_ms"]
                and df.iloc[j]["effort_days"] <= df.iloc[i]["effort_days"]
                and (
                    df.iloc[j]["impact_ms"] > df.iloc[i]["impact_ms"]
                    or df.iloc[j]["effort_days"] < df.iloc[i]["effort_days"]
                )
            ):
                dominated = True
                break
        pareto.append(not dominated)

    df["pareto_optimal"] = pareto
    df["category"] = df["effort_days"].apply(_categorise_effort)
    df = df.sort_values("impact_ms", ascending=False).reset_index(drop=True)
    return df


def format_recommendation_summary(pareto_df: pd.DataFrame, top_n: int = 10) -> str:
    """Format the top N Pareto-optimal recommendations as readable text."""
    optimal = pareto_df[pareto_df["pareto_optimal"]].head(top_n)

    lines = ["Top Build Optimisation Recommendations", "=" * 38, ""]

    for i, (_, row) in enumerate(optimal.iterrows(), 1):
        targets = row["targets_affected"]
        if len(targets) <= 3:
            targets_str = ", ".join(targets)
        else:
            targets_str = ", ".join(targets[:3]) + f" (+{len(targets) - 3} others)"

        impact_s = row["impact_ms"] / 1000
        if impact_s >= 60:
            impact_str = f"~{impact_s / 60:.0f}min reduction"
        else:
            impact_str = f"~{impact_s:.0f}s reduction"

        lines.append(f"{i}. [{row['type']}] {row['description']}")
        effort = f"~{row['effort_days']:.0f} days"
        lines.append(f"   Impact: {impact_str} | Effort: {effort} | Confidence: {row['confidence']:.1f}")
        if row["rationale"]:
            lines.append(f"   Rationale: {row['rationale']}")
        if targets_str:
            lines.append(f"   Targets affected: {targets_str}")
        lines.append("")

    return "\n".join(lines)
