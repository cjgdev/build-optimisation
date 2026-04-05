"""Snapshot comparison and trend analysis functions.

Compares two snapshots for deltas in global metrics, target-level metrics,
dependency edges, and critical paths. Also provides trend analysis across
multiple snapshots.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import pandas as pd

if TYPE_CHECKING:
    from buildanalysis.loading import BuildDataset
    from buildanalysis.modules import ModuleConfig
    from buildanalysis.snapshots import SnapshotMetadata
    from buildanalysis.types import BuildGraph


# ---------------------------------------------------------------------------
# Global deltas
# ---------------------------------------------------------------------------

# Metrics where "lower is better"
_LOWER_IS_BETTER = {
    "total_build_time_ms",
    "total_compile_time_ms",
    "total_link_time_ms",
    "total_preprocessed_bytes",
    "mean_expansion_ratio",
    "edge_count",
    "mean_dependency_count",
}


def compute_global_deltas(
    ds_before: "BuildDataset",
    ds_after: "BuildDataset",
) -> pd.DataFrame:
    """Compare high-level codebase metrics between two snapshots.

    Returns a DataFrame with one row per metric.
    """

    def _col_sum(df, col):
        return df[col].sum() if col in df.columns else 0

    def _col_mean(df, col):
        return df[col].mean() if col in df.columns else 0

    def _extract(ds):
        tm = ds.target_metrics
        el = ds.edge_list
        return {
            "total_build_time_ms": _col_sum(tm, "total_build_time_ms"),
            "total_compile_time_ms": _col_sum(tm, "compile_time_sum_ms"),
            "total_link_time_ms": _col_sum(tm, "link_time_ms"),
            "total_sloc": _col_sum(tm, "code_lines_total"),
            "target_count": len(tm),
            "file_count": _col_sum(tm, "file_count"),
            "total_preprocessed_bytes": _col_sum(tm, "preprocessed_bytes_total"),
            "mean_expansion_ratio": _col_mean(tm, "expansion_ratio_mean"),
            "edge_count": len(el),
            "mean_dependency_count": _col_mean(tm, "total_dependency_count"),
        }

    before = _extract(ds_before)
    after = _extract(ds_after)

    rows = []
    for metric in before:
        b = float(before[metric])
        a = float(after[metric])
        delta = a - b
        delta_pct = (delta / b * 100) if b != 0 else 0.0

        if metric in _LOWER_IS_BETTER:
            improved = delta < 0
        else:
            improved = delta >= 0  # More SLOC, targets, etc. is neutral/expected

        rows.append(
            {
                "metric": metric,
                "before": b,
                "after": a,
                "delta": delta,
                "delta_pct": delta_pct,
                "improved": improved,
            }
        )

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Target-level deltas
# ---------------------------------------------------------------------------


def compute_target_deltas(
    ds_before: "BuildDataset",
    ds_after: "BuildDataset",
) -> pd.DataFrame:
    """Compare target-level metrics between two snapshots."""
    tm_before = ds_before.target_metrics.set_index("cmake_target")
    tm_after = ds_after.target_metrics.set_index("cmake_target")

    all_targets = set(tm_before.index) | set(tm_after.index)

    def _get_float(df, target, col):
        return float(df.at[target, col]) if col in df.columns else None

    def _get_int(df, target, col):
        if col not in df.columns:
            return 0
        try:
            return int(df.at[target, col])
        except KeyError:
            return 0

    rows = []
    for t in all_targets:
        in_before = t in tm_before.index
        in_after = t in tm_after.index

        if in_before and in_after:
            bt_before = _get_float(tm_before, t, "total_build_time_ms")
            bt_after = _get_float(tm_after, t, "total_build_time_ms")
            delta = (bt_after or 0) - (bt_before or 0)
            delta_pct = (delta / bt_before * 100) if bt_before and bt_before != 0 else 0.0

            if delta < 0:
                status = "improved"
            elif delta > 0:
                status = "regressed"
            else:
                status = "unchanged"

            rows.append(
                {
                    "cmake_target": t,
                    "status": status,
                    "build_time_before_ms": bt_before,
                    "build_time_after_ms": bt_after,
                    "build_time_delta_ms": delta,
                    "build_time_delta_pct": delta_pct,
                    "sloc_before": _get_int(tm_before, t, "code_lines_total"),
                    "sloc_after": _get_int(tm_after, t, "code_lines_total"),
                    "dep_count_before": _get_int(tm_before, t, "total_dependency_count"),
                    "dep_count_after": _get_int(tm_after, t, "total_dependency_count"),
                    "dep_count_delta": (
                        (_get_int(tm_after, t, "total_dependency_count") or 0)
                        - (_get_int(tm_before, t, "total_dependency_count") or 0)
                    ),
                }
            )
        elif in_after:
            bt_after = _get_float(tm_after, t, "total_build_time_ms")
            rows.append(
                {
                    "cmake_target": t,
                    "status": "new",
                    "build_time_before_ms": None,
                    "build_time_after_ms": bt_after,
                    "build_time_delta_ms": bt_after or 0,
                    "build_time_delta_pct": float("nan"),
                    "sloc_before": None,
                    "sloc_after": _get_int(tm_after, t, "code_lines_total"),
                    "dep_count_before": None,
                    "dep_count_after": _get_int(tm_after, t, "total_dependency_count"),
                    "dep_count_delta": 0,
                }
            )
        else:
            bt_before = _get_float(tm_before, t, "total_build_time_ms")
            rows.append(
                {
                    "cmake_target": t,
                    "status": "removed",
                    "build_time_before_ms": bt_before,
                    "build_time_after_ms": None,
                    "build_time_delta_ms": -(bt_before or 0),
                    "build_time_delta_pct": float("nan"),
                    "sloc_before": _get_int(tm_before, t, "code_lines_total"),
                    "sloc_after": None,
                    "dep_count_before": _get_int(tm_before, t, "total_dependency_count"),
                    "dep_count_after": None,
                    "dep_count_delta": 0,
                }
            )

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Edge deltas
# ---------------------------------------------------------------------------


def compute_edge_deltas(
    ds_before: "BuildDataset",
    ds_after: "BuildDataset",
) -> dict:
    """Compare dependency edges between two snapshots."""
    el_before = ds_before.edge_list
    el_after = ds_after.edge_list

    before_edges = set(zip(el_before["source_target"], el_before["dest_target"]))
    after_edges = set(zip(el_after["source_target"], el_after["dest_target"]))

    added = after_edges - before_edges
    removed = before_edges - after_edges
    unchanged = before_edges & after_edges

    edge_cols = ["source_target", "dest_target"]
    added_df = pd.DataFrame(list(added), columns=edge_cols) if added else pd.DataFrame(columns=edge_cols)
    removed_df = pd.DataFrame(list(removed), columns=edge_cols) if removed else pd.DataFrame(columns=edge_cols)

    return {
        "edges_added": added_df,
        "edges_removed": removed_df,
        "edges_unchanged": len(unchanged),
        "added_count": len(added),
        "removed_count": len(removed),
    }


# ---------------------------------------------------------------------------
# Critical path comparison
# ---------------------------------------------------------------------------


def compute_critical_path_comparison(
    ds_before: "BuildDataset",
    ds_after: "BuildDataset",
    bg_before: "BuildGraph",
    bg_after: "BuildGraph",
) -> dict:
    """Compare critical paths between two snapshots.

    Requires pre-computed CriticalPathResult for each snapshot.
    """
    from buildanalysis.build import compute_critical_path

    timing_before = ds_before.target_metrics[["cmake_target", "total_build_time_ms"]].copy()
    timing_after = ds_after.target_metrics[["cmake_target", "total_build_time_ms"]].copy()

    cp_before = compute_critical_path(bg_before, timing_before)
    cp_after = compute_critical_path(bg_after, timing_after)

    path_before = set(cp_before.path)
    path_after = set(cp_after.path)

    return {
        "before_critical_path": cp_before.path,
        "after_critical_path": cp_after.path,
        "before_time_s": cp_before.total_time_s,
        "after_time_s": cp_after.total_time_s,
        "delta_s": cp_after.total_time_s - cp_before.total_time_s,
        "path_changed": path_before != path_after,
        "targets_added_to_path": list(path_after - path_before),
        "targets_removed_from_path": list(path_before - path_after),
    }


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


def compute_trend_data(
    snapshots: list[tuple["SnapshotMetadata", "BuildDataset"]],
) -> pd.DataFrame:
    """Compute time-series metrics across all snapshots.

    Returns a DataFrame with one row per snapshot, sorted by date.
    """
    rows = []
    for meta, ds in snapshots:
        tm = ds.target_metrics
        el = ds.edge_list

        def _isum(col):
            return int(tm[col].sum()) if col in tm.columns else 0

        def _fmean(col):
            return float(tm[col].mean()) if col in tm.columns else 0.0

        rows.append(
            {
                "label": meta.label,
                "date": meta.date,
                "total_build_time_ms": _isum("total_build_time_ms"),
                "total_compile_time_ms": _isum("compile_time_sum_ms"),
                "total_link_time_ms": _isum("link_time_ms"),
                "target_count": len(tm),
                "file_count": _isum("file_count"),
                "total_sloc": _isum("code_lines_total"),
                "total_preprocessed_bytes": _isum("preprocessed_bytes_total"),
                "edge_count": len(el),
                "mean_dep_count": _fmean("total_dependency_count"),
                "codegen_ratio": _fmean("codegen_ratio"),
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("date").reset_index(drop=True)
    return df


def compute_module_trends(
    snapshots: list[tuple["SnapshotMetadata", "BuildDataset"]],
    module_config: Optional["ModuleConfig"] = None,
) -> pd.DataFrame:
    """Compute per-module metrics across all snapshots."""
    if module_config is None:
        return pd.DataFrame(
            columns=[
                "label",
                "date",
                "module",
                "target_count",
                "total_build_time_ms",
                "total_sloc",
                "external_dep_count",
            ]
        )

    rows = []
    for meta, ds in snapshots:
        tm = ds.target_metrics
        assignments = module_config.assign_all_targets(tm)

        for module_name, group in assignments.groupby("module"):
            if pd.isna(module_name):
                continue
            bt = int(group["total_build_time_ms"].sum()) if "total_build_time_ms" in group.columns else 0
            sloc = int(group["code_lines_total"].sum()) if "code_lines_total" in group.columns else 0
            rows.append(
                {
                    "label": meta.label,
                    "date": meta.date,
                    "module": module_name,
                    "target_count": len(group),
                    "total_build_time_ms": bt,
                    "total_sloc": sloc,
                    "external_dep_count": 0,
                }
            )

    return pd.DataFrame(rows)


def detect_regressions(
    trend_data: pd.DataFrame,
    threshold_pct: float = 10.0,
) -> pd.DataFrame:
    """Identify metrics that worsened by more than threshold_pct since previous snapshot.

    Returns a DataFrame with flagged regressions.
    """
    if "date" in trend_data.columns:
        trend_data = trend_data.sort_values("date")

    if len(trend_data) < 2:
        return pd.DataFrame(columns=["metric", "previous_value", "current_value", "delta_pct", "severity"])

    prev = trend_data.iloc[-2]
    curr = trend_data.iloc[-1]

    # Metrics where increase = regression
    regression_metrics = {
        "total_build_time_ms",
        "total_compile_time_ms",
        "total_link_time_ms",
        "total_preprocessed_bytes",
        "edge_count",
        "mean_dep_count",
    }

    rows = []
    for metric in regression_metrics:
        if metric not in trend_data.columns:
            continue

        prev_val = float(prev[metric])
        curr_val = float(curr[metric])

        if prev_val == 0:
            continue

        delta_pct = (curr_val - prev_val) / prev_val * 100

        if delta_pct > threshold_pct:
            severity = "critical" if delta_pct > 2 * threshold_pct else "warning"
            rows.append(
                {
                    "metric": metric,
                    "previous_value": prev_val,
                    "current_value": curr_val,
                    "delta_pct": delta_pct,
                    "severity": severity,
                }
            )

    return pd.DataFrame(rows)
