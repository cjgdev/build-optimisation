"""GEXF graph export for Gephi visualisation."""

from __future__ import annotations

from pathlib import Path

import networkx as nx
import pandas as pd

from buildanalysis.types import BuildGraph


def _lookup(df: pd.DataFrame, key_col: str, key: str, val_col: str, default):
    """Look up a single value from a DataFrame, returning *default* if missing."""
    rows = df.loc[df[key_col] == key, val_col]
    if rows.empty:
        return default
    return rows.iloc[0]


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


# ---------------------------------------------------------------------------
# 1. Dependency graph
# ---------------------------------------------------------------------------


def export_dependency_graph(
    bg: BuildGraph,
    centrality: pd.DataFrame,
    layers: pd.DataFrame,
    communities: pd.DataFrame,
    timing: pd.DataFrame,
    team_assignments: pd.DataFrame,
    critical_path_targets: set[str] | None = None,
    codegen_fraction: pd.DataFrame | None = None,
    output_path: Path = Path("data/intermediate/gephi/dependency_graph.gexf"),
) -> Path:
    """Export the target dependency graph with analysis attributes as GEXF."""
    g = bg.graph.copy()
    if critical_path_targets is None:
        critical_path_targets = set()

    # Build lookup helpers — index DataFrames by cmake_target for fast access
    cent_map = centrality.set_index("cmake_target") if "cmake_target" in centrality.columns else centrality
    layer_map = layers.set_index("cmake_target") if "cmake_target" in layers.columns else layers
    comm_map = communities.set_index("cmake_target") if "cmake_target" in communities.columns else communities

    # Determine the team column name
    team_col = "primary_team" if "primary_team" in team_assignments.columns else "team"
    if "cmake_target" in team_assignments.columns:
        team_map = team_assignments.set_index("cmake_target")
    else:
        team_map = team_assignments

    timing_map = timing.set_index("cmake_target") if "cmake_target" in timing.columns else timing

    codegen_map = None
    if codegen_fraction is not None:
        if "cmake_target" in codegen_fraction.columns:
            codegen_map = codegen_fraction.set_index("cmake_target")
        else:
            codegen_map = codegen_fraction

    # Attach node attributes
    for node in g.nodes():
        attrs = {}

        # Timing
        if node in timing_map.index:
            val = timing_map.at[node, "total_build_time_ms"]
            attrs["compile_time_s"] = float(val) / 1000.0
        else:
            attrs["compile_time_s"] = 0.0

        # Layer
        attrs["layer"] = int(layer_map.at[node, "layer"]) if node in layer_map.index else 0

        # Community
        attrs["community"] = int(comm_map.at[node, "community"]) if node in comm_map.index else 0

        # Team
        attrs["team"] = str(team_map.at[node, team_col]) if node in team_map.index else "unknown"

        # Centrality metrics
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

        # Target type from graph node data
        attrs["target_type"] = str(g.nodes[node].get("target_type", "unknown"))

        # Source directory from target_metadata
        if node in bg.target_metadata.index and "source_directory" in bg.target_metadata.columns:
            attrs["source_directory"] = str(bg.target_metadata.at[node, "source_directory"])
        else:
            attrs["source_directory"] = "unknown"

        # Codegen ratio
        if codegen_map is not None and node in codegen_map.index:
            attrs["codegen_ratio"] = float(codegen_map.at[node, "codegen_ratio"])
        elif node in timing_map.index and "codegen_ratio" in timing_map.columns:
            attrs["codegen_ratio"] = float(timing_map.at[node, "codegen_ratio"])
        else:
            attrs["codegen_ratio"] = 0.0

        # Critical path
        attrs["on_critical_path"] = bool(node in critical_path_targets)

        # File count and SLOC from timing/target_metrics
        if node in timing_map.index:
            attrs["file_count"] = int(timing_map.at[node, "file_count"]) if "file_count" in timing_map.columns else 0
            sloc_col = "code_lines_total" if "code_lines_total" in timing_map.columns else None
            attrs["sloc"] = int(timing_map.at[node, sloc_col]) if sloc_col else 0
        else:
            attrs["file_count"] = 0
            attrs["sloc"] = 0

        g.nodes[node].update(attrs)

    # Attach edge attributes
    community_lookup = comm_map["community"].to_dict() if "community" in comm_map.columns else {}
    if not community_lookup and hasattr(comm_map, "index"):
        # comm_map was set_index'd, so community is a column
        community_lookup = comm_map["community"].to_dict()

    layer_lookup = layer_map["layer"].to_dict() if "layer" in layer_map.columns else {}
    if not layer_lookup and hasattr(layer_map, "index"):
        layer_lookup = layer_map["layer"].to_dict()

    for u, v, data in g.edges(data=True):
        data["dep_type"] = str(data.get("dependency_type", "unknown"))
        data["cmake_visibility"] = str(data.get("cmake_visibility", "unknown"))

        # Cross-community
        comm_u = community_lookup.get(u, 0)
        comm_v = community_lookup.get(v, 0)
        data["is_cross_community"] = bool(comm_u != comm_v)

        # Layer violation: dependency goes upward (source layer < dest layer)
        layer_u = layer_lookup.get(u, 0)
        layer_v = layer_lookup.get(v, 0)
        data["is_layer_violation"] = bool(int(layer_u) < int(layer_v))

    # Write
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_gexf(g, str(output_path))
    print(f"Exported {g.number_of_nodes()} nodes, {g.number_of_edges()} edges to {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# 2. Include graph
# ---------------------------------------------------------------------------


def export_include_graph(
    include_graph: nx.DiGraph,
    header_metrics: pd.DataFrame,
    header_impact: pd.DataFrame,
    header_pagerank: pd.DataFrame,
    git_churn: pd.DataFrame,
    file_metrics: pd.DataFrame | None = None,
    exclude_system: bool = True,
    output_path: Path = Path("data/intermediate/gephi/include_graph.gexf"),
) -> Path:
    """Export the header inclusion graph with analysis attributes as GEXF."""
    g = include_graph.copy()

    # Optionally remove system header edges
    if exclude_system:
        system_edges = [
            (u, v) for u, v, d in g.edges(data=True)
            if d.get("is_system", False)
        ]
        g.remove_edges_from(system_edges)
        # Remove isolated system nodes
        isolates = [n for n in list(nx.isolates(g)) if _is_system_header(n)]
        g.remove_nodes_from(isolates)

    # Build lookup maps
    pr_map = header_pagerank.set_index("file") if "file" in header_pagerank.columns else header_pagerank
    impact_map = header_impact.set_index("file") if "file" in header_impact.columns else header_impact
    hm_map = header_metrics.set_index("header_file") if "header_file" in header_metrics.columns else header_metrics
    churn_map = git_churn.set_index("source_file") if "source_file" in git_churn.columns else git_churn

    for node in g.nodes():
        attrs = {}

        # PageRank
        attrs["pagerank"] = float(pr_map.at[node, "pagerank"]) if node in pr_map.index else 0.0

        # Impact score
        if node in impact_map.index:
            attrs["impact_score"] = float(impact_map.at[node, "impact_score"])
            if "direct_fan_in" in impact_map.columns:
                attrs["fan_in"] = int(impact_map.at[node, "direct_fan_in"])
            else:
                attrs["fan_in"] = 0
            if "transitive_fan_in" in impact_map.columns:
                attrs["transitive_fan_in"] = int(impact_map.at[node, "transitive_fan_in"])
            else:
                attrs["transitive_fan_in"] = 0
        else:
            attrs["impact_score"] = 0.0
            attrs["fan_in"] = 0
            attrs["transitive_fan_in"] = 0

        # Header metrics
        if node in hm_map.index:
            row = hm_map.loc[node]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            attrs["sloc"] = int(row.get("sloc", 0))
            attrs["source_size_bytes"] = int(row.get("source_size_bytes", 0))
            attrs["cmake_target"] = str(row.get("cmake_target", "unknown"))
        else:
            attrs["sloc"] = 0
            attrs["source_size_bytes"] = 0
            attrs["cmake_target"] = "unknown"

        # Git churn
        attrs["n_commits"] = int(churn_map.at[node, "n_commits"]) if node in churn_map.index else 0

        # Origin
        attrs["origin"] = "HANDWRITTEN"  # default
        if file_metrics is not None and "source_file" in file_metrics.columns:
            fm_row = file_metrics.loc[file_metrics["source_file"] == node]
            if not fm_row.empty and fm_row.iloc[0].get("is_generated", False):
                attrs["origin"] = "GENERATED"

        # Is header
        attrs["is_header"] = bool(_is_header(node))

        g.nodes[node].update(attrs)

    # Edge attributes
    for u, v, data in g.edges(data=True):
        if "weight" not in data:
            data["weight"] = 1
        else:
            data["weight"] = int(data["weight"])
        data["is_system"] = bool(data.get("is_system", False))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_gexf(g, str(output_path))
    print(f"Exported {g.number_of_nodes()} nodes, {g.number_of_edges()} edges to {output_path}")
    return output_path


def _is_header(path: str) -> bool:
    """Heuristic: file is a header if extension is .h, .hpp, .hxx, or .hh."""
    lower = path.lower()
    return any(lower.endswith(ext) for ext in (".h", ".hpp", ".hxx", ".hh"))


def _is_system_header(path: str) -> bool:
    """Heuristic: system header if path starts with / or contains no /."""
    return path.startswith("/") or "/" not in path


# ---------------------------------------------------------------------------
# 3. Co-change graph
# ---------------------------------------------------------------------------


def export_cochange_graph(
    cochange: pd.DataFrame,
    target_metrics: pd.DataFrame,
    git_churn: pd.DataFrame,
    structural_communities: pd.DataFrame,
    min_pmi: float = 0.0,
    output_path: Path = Path("data/intermediate/gephi/cochange_graph.gexf"),
) -> Path:
    """Export the co-change coupling graph as an undirected GEXF."""
    # Filter by min_pmi
    filtered = cochange[cochange["pmi"] >= min_pmi].copy()

    g = nx.Graph()

    # Determine item columns
    a_col = "item_a"
    b_col = "item_b"

    # Collect all nodes
    all_nodes = set(filtered[a_col]) | set(filtered[b_col])

    # Build lookup maps
    tm_map = target_metrics.set_index("cmake_target") if "cmake_target" in target_metrics.columns else target_metrics
    if "cmake_target" in git_churn.columns:
        churn_map = git_churn.set_index("cmake_target")
    elif "source_file" in git_churn.columns:
        churn_map = git_churn.set_index("source_file")
    else:
        churn_map = git_churn
    if "cmake_target" in structural_communities.columns:
        comm_map = structural_communities.set_index("cmake_target")
    else:
        comm_map = structural_communities

    # Add nodes with attributes
    for node in all_nodes:
        attrs = {}

        if node in churn_map.index:
            row = churn_map.loc[node]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            attrs["n_commits"] = int(row.get("n_commits", row.get("total_commits", 0)))
            attrs["total_churn"] = int(row.get("total_churn", row.get("git_churn_total", 0)))
        else:
            attrs["n_commits"] = 0
            attrs["total_churn"] = 0

        attrs["structural_community"] = int(comm_map.at[node, "community"]) if node in comm_map.index else 0

        if node in tm_map.index:
            attrs["target_type"] = str(tm_map.at[node, "target_type"])
            build_time = tm_map.at[node, "total_build_time_ms"] if "total_build_time_ms" in tm_map.columns else 0
            attrs["compile_time_s"] = float(build_time) / 1000.0
        else:
            attrs["target_type"] = "unknown"
            attrs["compile_time_s"] = 0.0

        g.add_node(node, **attrs)

    # Add edges
    for _, row in filtered.iterrows():
        g.add_edge(
            row[a_col],
            row[b_col],
            cochange_count=int(row["cochange_count"]),
            pmi=float(row["pmi"]),
            jaccard=float(row["jaccard"]),
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_gexf(g, str(output_path))
    print(f"Exported {g.number_of_nodes()} nodes, {g.number_of_edges()} edges to {output_path}")
    return output_path
