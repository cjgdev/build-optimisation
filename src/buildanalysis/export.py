"""GEXF graph export for Gephi visualisation.

Exports dependency graphs, module graphs, include graphs, and co-change graphs
with full attribute sets. All optional data degrades gracefully to defaults.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import networkx as nx
import numpy as np
import pandas as pd

from buildanalysis.types import BuildGraph

if TYPE_CHECKING:
    from buildanalysis.build import CriticalPathResult
    from buildanalysis.modules import ModuleConfig
    from buildanalysis.teams import TeamConfig


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------


def _native(value, target_type):
    """Cast a value to a Python native type, using *target_type* as the constructor."""
    try:
        return target_type(value)
    except (TypeError, ValueError):
        if target_type is float:
            return 0.0
        if target_type is int:
            return 0
        if target_type is bool:
            return False
        return ""


_DEFAULTS = {
    "module": "unassigned",
    "module_category": "unknown",
    "team": "unknown",
    "source_directory": "",
    "cmake_target": "unknown",
    "target_type": "unknown",
    "cmake_visibility": "unknown",
    "origin": "unknown",
    "source_module": "unassigned",
    "dest_module": "unassigned",
    "owning_team": "unknown",
}


def _default_for_key(key: str):
    """Return the default value for a known attribute key."""
    if key in _DEFAULTS:
        return _DEFAULTS[key]
    # Numeric keys should default to 0, not empty string (which breaks GEXF typing)
    if any(key.endswith(s) for s in ("_ms", "_s", "_count", "_bytes", "_ratio", "_fraction", "_score", "_mb")):
        return 0.0
    if key in ("sloc", "in_degree", "out_degree", "layer", "community", "file_count", "code_lines",
               "depth", "weight", "n_commits", "total_churn", "contributor_count"):
        return 0
    return ""


def _is_na(value) -> bool:
    """Check if a value is NA/NaN/None, handling pandas and numpy types."""
    if value is None:
        return True
    try:
        return pd.isna(value)
    except (TypeError, ValueError):
        return False


def _set_node_attrs(g: nx.DiGraph | nx.Graph, node: str, attrs: dict) -> None:
    """Set node attributes with type casting for GEXF compatibility."""
    clean = {}
    for key, value in attrs.items():
        if isinstance(value, np.integer):
            clean[key] = int(value)
        elif isinstance(value, np.floating):
            v = float(value)
            clean[key] = v if not np.isnan(v) else _default_for_key(key)
        elif isinstance(value, np.bool_):
            clean[key] = bool(value)
        elif _is_na(value):
            clean[key] = _default_for_key(key)
        else:
            clean[key] = value
    g.nodes[node].update(clean)


def _set_edge_attrs(g: nx.DiGraph | nx.Graph, u: str, v: str, attrs: dict) -> None:
    """Set edge attributes with type casting for GEXF compatibility."""
    clean = {}
    for key, value in attrs.items():
        if isinstance(value, np.integer):
            clean[key] = int(value)
        elif isinstance(value, np.floating):
            v_float = float(value)
            clean[key] = v_float if not np.isnan(v_float) else _default_for_key(key)
        elif isinstance(value, np.bool_):
            clean[key] = bool(value)
        elif _is_na(value):
            clean[key] = _default_for_key(key)
        else:
            clean[key] = value
    g.edges[u, v].update(clean)


def _write_gexf(g, output_path: Path, label: str) -> Path:
    """Write graph to GEXF and print summary."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_gexf(g, str(output_path))
    print(f"Exported {label}: {g.number_of_nodes():,} nodes, {g.number_of_edges():,} edges → {output_path}")
    return output_path


def _build_index(df: pd.DataFrame, key_col: str) -> pd.DataFrame:
    """Set index on a DataFrame if the key column exists."""
    if key_col in df.columns:
        # Drop duplicates to avoid reindexing errors with non-unique keys
        deduped = df.drop_duplicates(subset=key_col, keep="first")
        return deduped.set_index(key_col)
    return df


# ---------------------------------------------------------------------------
# 1. Dependency graph
# ---------------------------------------------------------------------------


def export_dependency_graph(
    bg: BuildGraph,
    centrality: pd.DataFrame,
    layers: pd.DataFrame,
    communities: pd.DataFrame,
    timing: pd.DataFrame,
    critical_path_result: Optional["CriticalPathResult"] = None,
    team_config: Optional["TeamConfig"] = None,
    target_ownership: Optional[pd.DataFrame] = None,
    module_config: Optional["ModuleConfig"] = None,
    module_assignments: Optional[pd.DataFrame] = None,
    output_path: Path = Path("data/intermediate/gephi/dependency_graph.gexf"),
) -> Path:
    """Export the target dependency graph with full analysis attributes as GEXF."""
    g = bg.graph.copy()

    critical_path_targets: set[str] = set()
    slack_map: dict[str, float] = {}
    if critical_path_result is not None:
        critical_path_targets = set(critical_path_result.path)
        if hasattr(critical_path_result, "target_slack") and critical_path_result.target_slack is not None:
            slack_df = critical_path_result.target_slack
            if "cmake_target" in slack_df.columns and "slack_ms" in slack_df.columns:
                slack_map = slack_df.set_index("cmake_target")["slack_ms"].to_dict()

    # Build lookup maps
    cent_map = _build_index(centrality, "cmake_target")
    layer_map = _build_index(layers, "cmake_target")
    comm_map = _build_index(communities, "cmake_target")
    timing_map = _build_index(timing, "cmake_target")

    # Ownership map
    own_map = None
    if target_ownership is not None:
        own_map = _build_index(target_ownership, "cmake_target")

    # Module assignment map
    mod_map = None
    if module_assignments is not None:
        mod_map = _build_index(module_assignments, "cmake_target")

    meta = bg.target_metadata
    total_targets = g.number_of_nodes()

    # Attach node attributes
    for node in g.nodes():
        attrs: dict = {"label": str(node)}

        # Target metadata
        if node in meta.index:
            attrs["target_type"] = str(meta.at[node, "target_type"]) if "target_type" in meta.columns else "unknown"
            attrs["source_directory"] = (
                str(meta.at[node, "source_directory"]) if "source_directory" in meta.columns else ""
            )
        else:
            attrs["target_type"] = "unknown"
            attrs["source_directory"] = ""

        # Module
        if mod_map is not None and node in mod_map.index:
            attrs["module"] = (
                str(mod_map.at[node, "module"]) if not pd.isna(mod_map.at[node, "module"]) else "unassigned"
            )
            mc = mod_map.at[node, "module_category"] if "module_category" in mod_map.columns else "unknown"
            attrs["module_category"] = str(mc) if not pd.isna(mc) else "unknown"
        else:
            attrs["module"] = "unassigned"
            attrs["module_category"] = "unknown"

        # Team (from ownership)
        if own_map is not None and node in own_map.index:
            ot = own_map.at[node, "owning_team"]
            attrs["team"] = str(ot) if ot is not None and not pd.isna(ot) else "unknown"
            attrs["ownership_hhi"] = (
                float(own_map.at[node, "ownership_hhi"]) if "ownership_hhi" in own_map.columns else 0.0
            )
            attrs["cross_team_fraction"] = (
                float(own_map.at[node, "cross_team_fraction"]) if "cross_team_fraction" in own_map.columns else 0.0
            )
            attrs["contributor_count"] = (
                int(own_map.at[node, "contributor_count"]) if "contributor_count" in own_map.columns else 0
            )
        else:
            attrs["team"] = "unknown"
            attrs["ownership_hhi"] = 0.0
            attrs["cross_team_fraction"] = 0.0
            attrs["contributor_count"] = 0

        # Timing
        if node in timing_map.index:
            attrs["compile_time_s"] = (
                float(timing_map.at[node, "total_build_time_ms"]) / 1000.0
                if "total_build_time_ms" in timing_map.columns
                else 0.0
            )
            attrs["total_build_time_s"] = attrs["compile_time_s"]
        else:
            attrs["compile_time_s"] = 0.0
            attrs["total_build_time_s"] = 0.0

        # Extra timing from target metadata
        if node in meta.index:
            for col, attr, divisor in [
                ("compile_time_sum_ms", "compile_time_s", 1000),
                ("link_time_ms", "link_time_s", 1000),
                ("codegen_time_ms", "codegen_time_s", 1000),
                ("file_count", "file_count", 1),
                ("code_lines_total", "code_lines", 1),
                ("preprocessed_bytes_total", "preprocessed_mb", 1e6),
                ("codegen_ratio", "codegen_ratio", 1),
                ("git_commit_count_total", "git_commit_count", 1),
                ("git_churn_total", "git_churn", 1),
            ]:
                if col in meta.columns:
                    val = meta.at[node, col]
                    if divisor == 1:
                        if isinstance(val, (float, np.floating)) and col not in ("codegen_ratio",):
                            attrs[attr] = int(val) if not pd.isna(val) else 0
                        else:
                            attrs[attr] = float(val) if not pd.isna(val) else 0.0
                    else:
                        attrs[attr] = float(val) / divisor if not pd.isna(val) else 0.0
                elif attr not in attrs:
                    attrs[attr] = 0.0 if "." in str(type(0.0)) else 0

        # Layer
        attrs["layer"] = int(layer_map.at[node, "layer"]) if node in layer_map.index else -1

        # Community
        attrs["community"] = int(comm_map.at[node, "community"]) if node in comm_map.index else -1

        # Centrality
        if node in cent_map.index:
            attrs["betweenness"] = float(cent_map.at[node, "betweenness"])
            attrs["pagerank"] = float(cent_map.at[node, "pagerank"])
            attrs["in_degree"] = int(cent_map.at[node, "in_degree"])
            attrs["out_degree"] = int(cent_map.at[node, "out_degree"])
        else:
            attrs["betweenness"] = 0.0
            attrs["pagerank"] = 0.0
            attrs["in_degree"] = 0
            attrs["out_degree"] = 0

        # Transitive dependencies
        if node in cent_map.index and "n_transitive_deps" in cent_map.columns:
            n_trans = int(cent_map.at[node, "n_transitive_deps"])
        else:
            n_trans = len(nx.descendants(g, node))
        attrs["transitive_dep_count"] = n_trans
        attrs["transitive_dep_fraction"] = float(n_trans) / total_targets if total_targets > 0 else 0.0

        # Critical path
        attrs["on_critical_path"] = node in critical_path_targets
        attrs["slack_s"] = float(slack_map.get(node, 0)) / 1000.0

        _set_node_attrs(g, node, attrs)

    # Edge attributes
    community_lookup = comm_map["community"].to_dict() if "community" in comm_map.columns else {}
    layer_lookup = layer_map["layer"].to_dict() if "layer" in layer_map.columns else {}

    module_lookup = {}
    if mod_map is not None and "module" in mod_map.columns:
        module_lookup = mod_map["module"].to_dict()

    team_lookup = {}
    if own_map is not None and "owning_team" in own_map.columns:
        team_lookup = own_map["owning_team"].to_dict()

    for u, v, data in g.edges(data=True):
        edge_attrs = {}
        edge_attrs["cmake_visibility"] = str(data.get("cmake_visibility", data.get("visibility", "unknown")))

        comm_u = community_lookup.get(u, -1)
        comm_v = community_lookup.get(v, -1)
        edge_attrs["is_cross_community"] = comm_u != comm_v

        layer_u = layer_lookup.get(u, 0)
        layer_v = layer_lookup.get(v, 0)
        edge_attrs["is_layer_violation"] = int(layer_u) <= int(layer_v)

        mod_u = module_lookup.get(u, "unassigned")
        mod_v = module_lookup.get(v, "unassigned")
        edge_attrs["is_cross_module"] = str(mod_u) != str(mod_v)
        edge_attrs["source_module"] = str(mod_u) if mod_u and not pd.isna(mod_u) else "unassigned"
        edge_attrs["dest_module"] = str(mod_v) if mod_v and not pd.isna(mod_v) else "unassigned"

        team_u = team_lookup.get(u, "unknown")
        team_v = team_lookup.get(v, "unknown")
        edge_attrs["is_cross_team"] = str(team_u) != str(team_v)

        _set_edge_attrs(g, u, v, edge_attrs)

    return _write_gexf(g, output_path, "dependency_graph.gexf")


# ---------------------------------------------------------------------------
# 2. Module dependency graph
# ---------------------------------------------------------------------------


def export_module_graph(
    module_graph: nx.DiGraph,
    module_config: Optional["ModuleConfig"],
    module_metrics: pd.DataFrame,
    feature_configs: Optional[pd.DataFrame] = None,
    output_path: Path = Path("data/intermediate/gephi/module_graph.gexf"),
) -> Path:
    """Export the module-level dependency graph as GEXF."""
    g = module_graph.copy()

    mm_map = _build_index(module_metrics, "module")
    fc_map = _build_index(feature_configs, "module") if feature_configs is not None else None

    for node in g.nodes():
        attrs: dict = {"label": str(node)}

        if node in mm_map.index:
            row = mm_map.loc[node]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            attrs["category"] = str(row.get("category", "unknown"))
            attrs["owning_team"] = (
                str(row.get("owning_team", "unknown")) if row.get("owning_team") is not None else "unknown"
            )
            attrs["target_count"] = int(row.get("target_count", 0))
            attrs["total_build_time_s"] = float(row.get("total_build_time_ms", 0)) / 1000.0
            attrs["total_sloc"] = int(row.get("total_sloc", 0))
            attrs["file_count"] = int(row.get("file_count", 0))
            attrs["codegen_ratio"] = float(row.get("codegen_ratio", 0.0))
            attrs["self_containment"] = float(row.get("self_containment", 0.0))
            attrs["internal_dep_count"] = int(row.get("internal_dep_count", 0))
            attrs["external_dep_count"] = int(row.get("external_dep_count", 0))
            attrs["critical_path_target_count"] = int(row.get("critical_path_target_count", 0))
        else:
            attrs["category"] = str(g.nodes[node].get("category", "unknown"))

        if fc_map is not None and node in fc_map.index:
            attrs["build_fraction"] = float(fc_map.at[node, "build_fraction"])

        _set_node_attrs(g, node, attrs)

    # Edge attributes
    for u, v, data in g.edges(data=True):
        edge_attrs = {
            "weight": int(data.get("weight", 1)),
            "public_count": int(data.get("public_count", 0)),
            "private_count": int(data.get("private_count", 0)),
            "is_cross_category": bool(data.get("is_cross_category", False)),
            "is_bidirectional": bool(data.get("is_bidirectional", False)),
        }
        _set_edge_attrs(g, u, v, edge_attrs)

    return _write_gexf(g, output_path, "module_graph.gexf")


# ---------------------------------------------------------------------------
# 3. Include graph
# ---------------------------------------------------------------------------


def _is_header(path: str) -> bool:
    """Heuristic: file is a header if extension is .h, .hpp, .hxx, or .hh."""
    lower = path.lower()
    return any(lower.endswith(ext) for ext in (".h", ".hpp", ".hxx", ".hh", ".inl", ".ipp"))


def _is_system_header(path: str) -> bool:
    """Heuristic: system header if path starts with / or contains no /."""
    return path.startswith("/") or "/" not in path


def export_include_graph(
    include_graph: nx.DiGraph,
    header_metrics: pd.DataFrame,
    header_impact: pd.DataFrame,
    header_pagerank: pd.DataFrame,
    git_churn: pd.DataFrame,
    file_metrics: Optional[pd.DataFrame] = None,
    module_assignments: Optional[pd.DataFrame] = None,
    team_ownership: Optional[pd.DataFrame] = None,
    pch_candidates: Optional[dict[str, pd.DataFrame]] = None,
    amplification: Optional[pd.DataFrame] = None,
    exclude_system: bool = True,
    output_path: Path = Path("data/intermediate/gephi/include_graph.gexf"),
) -> Path:
    """Export the header inclusion graph with full analysis attributes as GEXF."""
    g = include_graph.copy()

    if exclude_system:
        system_edges = [(u, v) for u, v, d in g.edges(data=True) if d.get("is_system", False)]
        g.remove_edges_from(system_edges)
        isolates = [n for n in list(nx.isolates(g)) if _is_system_header(n)]
        g.remove_nodes_from(isolates)

    # Build lookup maps
    pr_map = _build_index(header_pagerank, "file")
    impact_map = _build_index(header_impact, "file")
    hm_map = _build_index(header_metrics, "header_file")
    churn_col = "source_file" if "source_file" in git_churn.columns else "header_file"
    churn_map = _build_index(git_churn, churn_col)

    # File metrics for source files
    fm_map = None
    if file_metrics is not None:
        fm_map = _build_index(file_metrics, "source_file")

    # Module/team lookups via target
    target_to_module = {}
    target_to_team = {}
    if module_assignments is not None and "cmake_target" in module_assignments.columns:
        target_to_module = module_assignments.set_index("cmake_target")["module"].to_dict()
    if team_ownership is not None and "cmake_target" in team_ownership.columns:
        target_to_team = team_ownership.set_index("cmake_target")["owning_team"].to_dict()

    # Amplification ratio map
    amp_map: dict[str, float] = {}
    if amplification is not None and "file" in amplification.columns and "amplification_ratio" in amplification.columns:
        amp_map = amplification.set_index("file")["amplification_ratio"].to_dict()

    # PCH candidate scores
    pch_score_map: dict[str, float] = {}
    if pch_candidates:
        for _target, cdf in pch_candidates.items():
            if "header_file" in cdf.columns and "pch_score" in cdf.columns:
                for _, row in cdf.iterrows():
                    h = row["header_file"]
                    score = row["pch_score"]
                    pch_score_map[h] = max(pch_score_map.get(h, 0), score)

    for node in g.nodes():
        attrs: dict = {
            "label": os.path.basename(node),
            "full_path": str(node),
            "is_header": _is_header(node),
        }

        # Header metrics
        if node in hm_map.index:
            hrow = hm_map.loc[node]
            if isinstance(hrow, pd.DataFrame):
                hrow = hrow.iloc[0]
            attrs["sloc"] = int(hrow.get("sloc", 0))
            attrs["source_size_bytes"] = int(hrow.get("source_size_bytes", 0))
            target = str(hrow.get("cmake_target", "unknown"))
            attrs["cmake_target"] = target
        else:
            attrs["sloc"] = 0
            attrs["source_size_bytes"] = 0
            target = "unknown"
            attrs["cmake_target"] = "unknown"

        # Module and team via target
        attrs["module"] = str(target_to_module.get(target, "unassigned"))
        attrs["team"] = str(target_to_team.get(target, "unknown"))

        # Origin
        attrs["origin"] = "unknown"
        if fm_map is not None and node in fm_map.index:
            frow = fm_map.loc[node]
            if isinstance(frow, pd.DataFrame):
                frow = frow.iloc[0]
            if frow.get("is_generated", False):
                attrs["origin"] = "GENERATED"
            else:
                attrs["origin"] = "HANDWRITTEN"

        # PageRank
        attrs["pagerank"] = float(pr_map.at[node, "pagerank"]) if node in pr_map.index else 0.0

        # Impact
        if node in impact_map.index:
            irow = impact_map.loc[node]
            if isinstance(irow, pd.DataFrame):
                irow = irow.iloc[0]
            attrs["impact_score"] = float(irow.get("impact_score", 0.0))
            attrs["direct_fan_in"] = int(irow.get("direct_fan_in", 0))
            attrs["transitive_fan_in"] = int(irow.get("transitive_fan_in", 0))
        else:
            attrs["impact_score"] = 0.0
            attrs["direct_fan_in"] = 0
            attrs["transitive_fan_in"] = 0

        attrs["direct_fan_out"] = g.out_degree(node)

        # Git
        if node in churn_map.index:
            crow = churn_map.loc[node]
            if isinstance(crow, pd.DataFrame):
                crow = crow.iloc[0]
            attrs["git_commits"] = int(crow.get("n_commits", 0))
            attrs["git_churn"] = int(crow.get("total_churn", crow.get("git_churn", 0)))
        else:
            attrs["git_commits"] = 0
            attrs["git_churn"] = 0

        # Source file metrics
        if fm_map is not None and node in fm_map.index:
            frow = fm_map.loc[node]
            if isinstance(frow, pd.DataFrame):
                frow = frow.iloc[0]
            attrs["compile_time_ms"] = _native(frow.get("compile_time_ms", 0), int)
            attrs["preprocessed_bytes"] = _native(frow.get("preprocessed_bytes", 0), int)
            attrs["expansion_ratio"] = _native(frow.get("expansion_ratio", 0.0), float)
        else:
            attrs["compile_time_ms"] = 0
            attrs["preprocessed_bytes"] = 0
            attrs["expansion_ratio"] = 0.0

        # Amplification ratio: prefer explicit amplification parameter, fall back to file_metrics
        if node in amp_map:
            attrs["amplification_ratio"] = float(amp_map[node])
        elif fm_map is not None and node in fm_map.index:
            frow = fm_map.loc[node]
            if isinstance(frow, pd.DataFrame):
                frow = frow.iloc[0]
            attrs["amplification_ratio"] = float(frow.get("amplification_ratio", 0.0))
        else:
            attrs["amplification_ratio"] = 0.0

        # PCH candidate score
        attrs["pch_candidate_score"] = float(pch_score_map.get(node, 0.0))

        _set_node_attrs(g, node, attrs)

    # Edge attributes
    for u, v, data in g.edges(data=True):
        edge_attrs: dict = {}
        edge_attrs["weight"] = int(data.get("weight", 1))

        # Cross-target / cross-module
        u_target = g.nodes[u].get("cmake_target", "unknown")
        v_target = g.nodes[v].get("cmake_target", "unknown")
        edge_attrs["is_cross_target"] = str(u_target) != str(v_target)

        u_mod = g.nodes[u].get("module", "unassigned")
        v_mod = g.nodes[v].get("module", "unassigned")
        edge_attrs["is_cross_module"] = str(u_mod) != str(v_mod)
        edge_attrs["source_module"] = str(u_mod)
        edge_attrs["dest_module"] = str(v_mod)

        _set_edge_attrs(g, u, v, edge_attrs)

    return _write_gexf(g, output_path, "include_graph.gexf")


# ---------------------------------------------------------------------------
# 4. Co-change graph
# ---------------------------------------------------------------------------


def export_cochange_graph(
    cochange: pd.DataFrame,
    target_metrics: pd.DataFrame,
    git_churn: pd.DataFrame,
    structural_communities: pd.DataFrame,
    edge_list: Optional[pd.DataFrame] = None,
    module_assignments: Optional[pd.DataFrame] = None,
    team_ownership: Optional[pd.DataFrame] = None,
    min_pmi: float = 0.0,
    output_path: Path = Path("data/intermediate/gephi/cochange_graph.gexf"),
) -> Path:
    """Export the co-change coupling graph as an undirected GEXF."""
    filtered = cochange[cochange["pmi"] >= min_pmi].copy()

    g = nx.Graph()

    a_col = "item_a"
    b_col = "item_b"

    all_nodes = set(filtered[a_col]) | set(filtered[b_col])

    # Build lookup maps
    tm_map = _build_index(target_metrics, "cmake_target")
    churn_col = "cmake_target" if "cmake_target" in git_churn.columns else "source_file"
    churn_map = _build_index(git_churn, churn_col)
    comm_map = _build_index(structural_communities, "cmake_target")

    # Module/team
    mod_lookup = {}
    if module_assignments is not None and "cmake_target" in module_assignments.columns:
        mod_lookup = module_assignments.set_index("cmake_target")["module"].to_dict()
    team_lookup = {}
    if team_ownership is not None and "cmake_target" in team_ownership.columns:
        team_lookup = team_ownership.set_index("cmake_target")["owning_team"].to_dict()

    # Structural edge set
    structural_edges: set[tuple[str, str]] = set()
    if edge_list is not None:
        for _, row in edge_list.iterrows():
            structural_edges.add((row["source_target"], row["dest_target"]))
            structural_edges.add((row["dest_target"], row["source_target"]))

    # Build ownership index once outside the loop
    own_map = _build_index(team_ownership, "cmake_target") if team_ownership is not None else None

    # Add nodes
    for node in all_nodes:
        attrs: dict = {"label": str(node)}

        if node in tm_map.index:
            attrs["target_type"] = str(tm_map.at[node, "target_type"])
            bt = tm_map.at[node, "total_build_time_ms"] if "total_build_time_ms" in tm_map.columns else 0
            attrs["total_build_time_s"] = float(bt) / 1000.0
            attrs["codegen_ratio"] = (
                float(tm_map.at[node, "codegen_ratio"]) if "codegen_ratio" in tm_map.columns else 0.0
            )
            attrs["code_lines"] = (
                int(tm_map.at[node, "code_lines_total"]) if "code_lines_total" in tm_map.columns else 0
            )
        else:
            attrs["target_type"] = "unknown"
            attrs["total_build_time_s"] = 0.0
            attrs["codegen_ratio"] = 0.0
            attrs["code_lines"] = 0

        if node in churn_map.index:
            crow = churn_map.loc[node]
            if isinstance(crow, pd.DataFrame):
                crow = crow.iloc[0]
            attrs["n_commits"] = int(crow.get("n_commits", crow.get("total_commits", 0)))
            attrs["total_churn"] = int(crow.get("total_churn", crow.get("git_churn_total", 0)))
            attrs["contributor_count"] = int(crow.get("contributor_count", crow.get("git_distinct_authors", 0)))
        else:
            attrs["n_commits"] = 0
            attrs["total_churn"] = 0
            attrs["contributor_count"] = 0

        attrs["structural_community"] = int(comm_map.at[node, "community"]) if node in comm_map.index else -1
        attrs["module"] = str(mod_lookup.get(node, "unassigned"))
        attrs["team"] = str(team_lookup.get(node, "unknown"))

        # Ownership HHI
        if own_map is not None:
            if node in own_map.index:
                attrs["ownership_hhi"] = (
                    float(own_map.at[node, "ownership_hhi"]) if "ownership_hhi" in own_map.columns else 0.0
                )
            else:
                attrs["ownership_hhi"] = 0.0
        else:
            attrs["ownership_hhi"] = 0.0

        g.add_node(node, **{})
        _set_node_attrs(g, node, attrs)

    # Add edges
    for _, row in filtered.iterrows():
        u, v = row[a_col], row[b_col]
        edge_attrs: dict = {
            "cochange_count": int(row["cochange_count"]),
            "pmi": float(row["pmi"]),
            "jaccard": float(row["jaccard"]),
        }

        mod_u = mod_lookup.get(u, "unassigned")
        mod_v = mod_lookup.get(v, "unassigned")
        edge_attrs["is_cross_module"] = str(mod_u) != str(mod_v)

        team_u = team_lookup.get(u, "unknown")
        team_v = team_lookup.get(v, "unknown")
        edge_attrs["is_cross_team"] = str(team_u) != str(team_v)

        edge_attrs["has_structural_edge"] = (u, v) in structural_edges
        edge_attrs["source_module"] = str(mod_u)
        edge_attrs["dest_module"] = str(mod_v)

        g.add_edge(u, v, **edge_attrs)

    return _write_gexf(g, output_path, "cochange_graph.gexf")
