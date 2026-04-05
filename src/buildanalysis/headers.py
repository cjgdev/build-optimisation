"""Header inclusion analysis: fan-in/out, impact scoring, PageRank, amplification, PCH analysis."""

from __future__ import annotations

import json
import logging
from typing import Optional

import networkx as nx
import pandas as pd

from buildanalysis.types import AnalysisScope

logger = logging.getLogger(__name__)

_HEADER_EXTENSIONS = frozenset({".h", ".hpp", ".hxx", ".hh", ".inl", ".ipp"})
_SOURCE_EXTENSIONS = frozenset({".cpp", ".cc", ".c", ".cxx"})


def _is_header(path: str) -> bool:
    """Return True if the file has a header extension."""
    dot = path.rfind(".")
    return dot != -1 and path[dot:] in _HEADER_EXTENSIONS


def _is_source(path: str) -> bool:
    """Return True if the file has a source extension."""
    dot = path.rfind(".")
    return dot != -1 and path[dot:] in _SOURCE_EXTENSIONS


def compute_include_fan_metrics(include_graph: nx.DiGraph) -> pd.DataFrame:
    """Compute fan-in and fan-out for every file in the include graph.

    Parameters
    ----------
    include_graph:
        DiGraph where edge (A, B) means A includes B.

    Returns
    -------
    DataFrame with columns: file, direct_fan_in, direct_fan_out,
    transitive_fan_in, is_header.
    """
    reversed_graph = include_graph.reverse()

    rows = []
    for node in include_graph.nodes():
        is_hdr = _is_header(node)
        if is_hdr:
            transitive_fan_in = len(nx.descendants(reversed_graph, node))
        else:
            transitive_fan_in = -1

        rows.append(
            {
                "file": node,
                "direct_fan_in": include_graph.in_degree(node),
                "direct_fan_out": include_graph.out_degree(node),
                "transitive_fan_in": transitive_fan_in,
                "is_header": is_hdr,
            }
        )

    return pd.DataFrame(rows)


def compute_header_impact_score(
    fan_metrics: pd.DataFrame,
    header_metrics: pd.DataFrame,
    git_churn: pd.DataFrame,
) -> pd.DataFrame:
    """Score headers by their impact on build performance.

    Impact = transitive_fan_in * source_size_bytes * (1 + n_commits)

    Parameters
    ----------
    fan_metrics:
        Output of ``compute_include_fan_metrics`` (columns: file, transitive_fan_in, ...).
    header_metrics:
        DataFrame with ``header_file``, ``sloc``, ``source_size_bytes`` columns.
    git_churn:
        DataFrame with ``source_file`` and ``n_commits`` columns.
    """
    # Filter to headers only
    headers = fan_metrics[fan_metrics["is_header"]].copy()

    # Merge header metrics (header_file → file)
    merged = headers.merge(
        header_metrics.rename(columns={"header_file": "file"})[["file", "sloc", "source_size_bytes"]],
        on="file",
        how="left",
    )

    # Merge git churn (source_file → file)
    merged = merged.merge(
        git_churn.rename(columns={"source_file": "file"})[["file", "n_commits"]],
        on="file",
        how="left",
    )
    merged["n_commits"] = merged["n_commits"].fillna(0).astype(int)
    merged["sloc"] = merged["sloc"].fillna(0).astype(int)
    merged["source_size_bytes"] = merged["source_size_bytes"].fillna(0).astype(int)

    # Compute impact score
    merged["impact_score"] = merged["transitive_fan_in"] * merged["source_size_bytes"] * (1 + merged["n_commits"])

    result = merged[
        ["file", "transitive_fan_in", "sloc", "source_size_bytes", "n_commits", "impact_score", "direct_fan_in"]
    ]
    return result.sort_values("impact_score", ascending=False).reset_index(drop=True)


def compute_header_pagerank(
    include_graph: nx.DiGraph,
    exclude_system: bool = True,
) -> pd.DataFrame:
    """Apply PageRank to identify structurally important headers.

    Parameters
    ----------
    include_graph:
        The include DiGraph.
    exclude_system:
        If True, remove nodes with ``is_system=True`` before computing PageRank.
    """
    g = include_graph
    if exclude_system:
        system_nodes = [n for n, data in g.nodes(data=True) if data.get("is_system", False)]
        g = g.copy()
        g.remove_nodes_from(system_nodes)

    if g.number_of_nodes() == 0:
        return pd.DataFrame(columns=["file", "pagerank"])

    pr = nx.pagerank(g)
    df = pd.DataFrame({"file": list(pr.keys()), "pagerank": list(pr.values())})
    return df.sort_values("pagerank", ascending=False).reset_index(drop=True)


def compute_include_amplification(
    include_graph: nx.DiGraph,
    file_metrics: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Measure how much each #include directive amplifies preprocessed output.

    Parameters
    ----------
    include_graph:
        The include DiGraph.
    file_metrics:
        Optional DataFrame with ``preprocessed_bytes`` column indexed or
        containing a file path column, to enrich the output.
    """
    rows = []
    for node in include_graph.nodes():
        if not _is_source(node):
            continue
        if include_graph.out_degree(node) == 0:
            continue

        direct = include_graph.out_degree(node)
        transitive = len(nx.descendants(include_graph, node))
        ratio = transitive / direct if direct > 0 else 0.0

        rows.append(
            {
                "file": node,
                "direct_includes": direct,
                "transitive_includes": transitive,
                "amplification_ratio": ratio,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(
            columns=["file", "direct_includes", "transitive_includes", "amplification_ratio", "preprocessed_bytes"]
        )
        return df

    if file_metrics is not None:
        # Determine the file column in file_metrics
        fm = file_metrics.copy()
        if "source_file" in fm.columns:
            fm = fm.rename(columns={"source_file": "file"})
        elif "file" not in fm.columns and fm.index.name in ("source_file", "file"):
            fm = fm.reset_index().rename(columns={fm.index.name: "file"})

        if "preprocessed_bytes" in fm.columns:
            df = df.merge(fm[["file", "preprocessed_bytes"]], on="file", how="left")

    return df.sort_values("amplification_ratio", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# PCH candidate identification (REQ-03)
# ---------------------------------------------------------------------------


def identify_pch_candidates(
    target: str,
    include_graph: nx.DiGraph,
    file_metrics: pd.DataFrame,
    header_metrics: pd.DataFrame,
    git_churn: pd.DataFrame,
    n_candidates: int = 20,
) -> pd.DataFrame:
    """Identify headers suitable for inclusion in a precompiled header.

    Scores each header on coverage × size × stability.
    """
    # 1. Source files for this target
    target_files = file_metrics.loc[file_metrics["cmake_target"] == target, "source_file"].tolist()

    if not target_files:
        return pd.DataFrame(
            columns=[
                "header_file",
                "coverage",
                "coverage_fraction",
                "source_size_bytes",
                "sloc",
                "git_commits",
                "stability_score",
                "pch_score",
                "is_target_owned",
            ]
        )

    total_files = len(target_files)

    # 2. For each source file, collect transitive non-system headers
    header_coverage: dict[str, int] = {}
    for src in target_files:
        if src not in include_graph:
            continue
        transitive = nx.descendants(include_graph, src)
        for h in transitive:
            if _is_header(h):
                header_coverage[h] = header_coverage.get(h, 0) + 1

    # Filter to coverage > 1
    header_coverage = {h: c for h, c in header_coverage.items() if c > 1}

    if not header_coverage:
        return pd.DataFrame(
            columns=[
                "header_file",
                "coverage",
                "coverage_fraction",
                "source_size_bytes",
                "sloc",
                "git_commits",
                "stability_score",
                "pch_score",
                "is_target_owned",
            ]
        )

    # Build lookup maps
    hm_map = header_metrics.set_index("header_file") if "header_file" in header_metrics.columns else header_metrics
    gc_col = "source_file" if "source_file" in git_churn.columns else "header_file"
    gc_map = git_churn.set_index(gc_col)["n_commits"].to_dict() if "n_commits" in git_churn.columns else {}

    # Header target ownership
    hm_target_map = {}
    if "cmake_target" in header_metrics.columns:
        hm_target_map = header_metrics.set_index(
            "header_file" if "header_file" in header_metrics.columns else header_metrics.index.name
        )["cmake_target"].to_dict()

    # Normalisation maxima
    max_size = max((hm_map.loc[h, "source_size_bytes"] if h in hm_map.index else 0 for h in header_coverage), default=0)
    max_commits = max((gc_map.get(h, 0) for h in header_coverage), default=0)
    if max_size == 0:
        max_size = 1
    if max_commits == 0:
        max_commits = 1

    rows = []
    for h, cov in header_coverage.items():
        coverage_fraction = cov / total_files

        size = int(hm_map.loc[h, "source_size_bytes"]) if h in hm_map.index else 0
        sloc = int(hm_map.loc[h, "sloc"]) if h in hm_map.index else 0
        commits = gc_map.get(h, 0)

        size_score = size / max_size
        stability_score = 1.0 - (commits / max_commits)
        pch_score = coverage_fraction * size_score * stability_score

        is_target_owned = hm_target_map.get(h) == target

        rows.append(
            {
                "header_file": h,
                "coverage": cov,
                "coverage_fraction": coverage_fraction,
                "source_size_bytes": size,
                "sloc": sloc,
                "git_commits": commits,
                "stability_score": stability_score,
                "pch_score": pch_score,
                "is_target_owned": is_target_owned,
            }
        )

    df = pd.DataFrame(rows)
    df = df.sort_values("pch_score", ascending=False).head(n_candidates).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# PCH impact simulation (REQ-03)
# ---------------------------------------------------------------------------


def simulate_pch_impact(
    target: str,
    pch_headers: list[str],
    include_graph: nx.DiGraph,
    file_metrics: pd.DataFrame,
    header_metrics: pd.DataFrame,
    git_churn: pd.DataFrame,
    builds_per_day: int = 10,
) -> dict:
    """Estimate build time impact of introducing a PCH.

    Returns a dict with estimated savings and recommendation.
    """
    if not pch_headers:
        return {
            "target": target,
            "pch_header_count": 0,
            "source_file_count": 0,
            "total_preprocessed_bytes_saved": 0,
            "preprocessed_reduction_fraction": 0.0,
            "estimated_compile_time_saved_ms": 0,
            "estimated_pch_rebuild_cost_ms": 0.0,
            "pch_rebuild_frequency_per_month": 0.0,
            "net_monthly_savings_ms": 0.0,
            "recommendation": "not_recommended",
            "risk_headers": [],
        }

    pch_set = set(pch_headers)

    # Source files for this target
    target_files = file_metrics.loc[file_metrics["cmake_target"] == target]
    source_file_count = len(target_files)

    # Header metrics lookup
    hm_map = header_metrics.set_index("header_file") if "header_file" in header_metrics.columns else header_metrics

    # Git churn lookup
    gc_col = "source_file" if "source_file" in git_churn.columns else "header_file"
    gc_map = git_churn.set_index(gc_col)["n_commits"].to_dict() if "n_commits" in git_churn.columns else {}

    # 1. Preprocessed bytes saved per file
    total_bytes_saved = 0
    for _, row in target_files.iterrows():
        src = row["source_file"]
        if src not in include_graph:
            continue
        transitive = nx.descendants(include_graph, src)
        for h in transitive:
            if h in pch_set and h in hm_map.index:
                total_bytes_saved += int(hm_map.loc[h, "source_size_bytes"])

    # Total preprocessed bytes for the target
    total_preprocessed = target_files["preprocessed_bytes"].sum() if "preprocessed_bytes" in target_files.columns else 1
    if total_preprocessed == 0:
        total_preprocessed = 1
    preprocessed_reduction = total_bytes_saved / total_preprocessed

    # 3. Estimated compile time reduction
    total_compile_time = target_files["compile_time_ms"].sum() if "compile_time_ms" in target_files.columns else 0
    if total_preprocessed > 0 and total_compile_time > 0:
        bytes_per_ms = total_preprocessed / total_compile_time
        time_saved = total_bytes_saved / bytes_per_ms if bytes_per_ms > 0 else 0
    else:
        time_saved = 0

    # 4. PCH rebuild frequency — sum of individual header change frequencies
    # Approximate commits/month based on available data
    total_months = 12  # default assumption
    rebuild_freq_per_month = sum(gc_map.get(h, 0) / total_months for h in pch_headers)

    # 5. PCH rebuild cost
    pch_total_bytes = sum(int(hm_map.loc[h, "source_size_bytes"]) if h in hm_map.index else 0 for h in pch_headers)
    if total_preprocessed > 0 and total_compile_time > 0:
        bytes_per_ms = total_preprocessed / total_compile_time
        pch_rebuild_cost = pch_total_bytes / bytes_per_ms if bytes_per_ms > 0 else 0
    else:
        pch_rebuild_cost = 0

    # 6. Net monthly impact
    builds_per_month = builds_per_day * 22  # ~22 working days
    net_monthly = (time_saved * builds_per_month) - (pch_rebuild_cost * rebuild_freq_per_month)

    # Risk headers: those with high commit frequency
    # Use absolute threshold: >5 commits in the analysis period
    risk_headers = [h for h in pch_headers if gc_map.get(h, 0) > 5]

    # Recommendation
    if preprocessed_reduction > 0.2 and len(risk_headers) == 0:
        recommendation = "recommended"
    elif preprocessed_reduction > 0.1 or len(risk_headers) <= 2:
        recommendation = "marginal"
    else:
        recommendation = "not_recommended"

    return {
        "target": target,
        "pch_header_count": len(pch_headers),
        "source_file_count": source_file_count,
        "total_preprocessed_bytes_saved": total_bytes_saved,
        "preprocessed_reduction_fraction": float(preprocessed_reduction),
        "estimated_compile_time_saved_ms": float(time_saved),
        "estimated_pch_rebuild_cost_ms": float(pch_rebuild_cost),
        "pch_rebuild_frequency_per_month": float(rebuild_freq_per_month),
        "net_monthly_savings_ms": float(net_monthly),
        "recommendation": recommendation,
        "risk_headers": risk_headers,
    }


# ---------------------------------------------------------------------------
# Batch PCH analysis (REQ-03)
# ---------------------------------------------------------------------------


def analyse_pch_opportunities(
    targets: list[str],
    include_graph: nx.DiGraph,
    file_metrics: pd.DataFrame,
    header_metrics: pd.DataFrame,
    git_churn: pd.DataFrame,
    n_candidates_per_target: int = 15,
    scope: Optional[AnalysisScope] = None,
) -> pd.DataFrame:
    """Run PCH analysis for multiple targets.

    Filters to targets with ≥3 source files. Returns one row per target,
    sorted by estimated savings descending.
    """
    if scope is not None:
        file_metrics = scope.filter_targets(file_metrics)

    # Determine targets to analyse
    if not targets:
        targets = file_metrics["cmake_target"].unique().tolist()

    rows = []
    for t in targets:
        t_files = file_metrics[file_metrics["cmake_target"] == t]
        if len(t_files) < 3:
            continue

        candidates = identify_pch_candidates(
            target=t,
            include_graph=include_graph,
            file_metrics=file_metrics,
            header_metrics=header_metrics,
            git_churn=git_churn,
            n_candidates=n_candidates_per_target,
        )

        pch_headers = candidates["header_file"].tolist()
        impact = simulate_pch_impact(
            target=t,
            pch_headers=pch_headers,
            include_graph=include_graph,
            file_metrics=file_metrics,
            header_metrics=header_metrics,
            git_churn=git_churn,
        )

        current_compile = t_files["compile_time_ms"].sum() if "compile_time_ms" in t_files.columns else 0

        rows.append(
            {
                "cmake_target": t,
                "source_file_count": len(t_files),
                "current_compile_time_ms": int(current_compile),
                "estimated_savings_ms": float(impact["estimated_compile_time_saved_ms"]),
                "savings_fraction": (
                    impact["estimated_compile_time_saved_ms"] / current_compile if current_compile > 0 else 0.0
                ),
                "pch_header_count": impact["pch_header_count"],
                "risk_header_count": len(impact["risk_headers"]),
                "recommendation": impact["recommendation"],
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("estimated_savings_ms", ascending=False).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# PCH overlap analysis (REQ-03)
# ---------------------------------------------------------------------------


def analyse_pch_overlap(
    pch_candidates: dict[str, list[str]],
) -> pd.DataFrame:
    """Identify headers appearing across multiple targets' PCH candidate lists.

    Parameters
    ----------
    pch_candidates:
        Maps target name → list of proposed PCH header paths.

    Returns DataFrame with one row per header, sorted by target_count desc.
    """
    n_targets = len(pch_candidates)
    header_targets: dict[str, list[str]] = {}

    for target, headers in pch_candidates.items():
        for h in headers:
            if h not in header_targets:
                header_targets[h] = []
            header_targets[h].append(target)

    rows = []
    for h, targets in header_targets.items():
        rows.append(
            {
                "header_file": h,
                "target_count": len(targets),
                "target_fraction": len(targets) / n_targets if n_targets > 0 else 0.0,
                "targets": json.dumps(targets),
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("target_count", ascending=False).reset_index(drop=True)
    return df
