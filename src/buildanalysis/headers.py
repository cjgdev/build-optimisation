"""Header inclusion analysis: fan-in/out, impact scoring, PageRank, amplification."""

from __future__ import annotations

import networkx as nx
import pandas as pd

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

        rows.append({
            "file": node,
            "direct_fan_in": include_graph.in_degree(node),
            "direct_fan_out": include_graph.out_degree(node),
            "transitive_fan_in": transitive_fan_in,
            "is_header": is_hdr,
        })

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
    merged["impact_score"] = (
        merged["transitive_fan_in"] * merged["source_size_bytes"] * (1 + merged["n_commits"])
    )

    result = merged[["file", "transitive_fan_in", "sloc", "source_size_bytes", "n_commits", "impact_score", "direct_fan_in"]]
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

        rows.append({
            "file": node,
            "direct_includes": direct,
            "transitive_includes": transitive,
            "amplification_ratio": ratio,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["file", "direct_includes", "transitive_includes", "amplification_ratio", "preprocessed_bytes"])
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
