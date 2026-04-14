"""Ad-hoc analysis scripts for build engineers.

Each module in this package is a self-contained CLI that answers a specific
question about a collected build snapshot. All scripts read parquet data
produced by ``scripts/consolidate/``.

Ranking scripts (hotspots, critical_path, slow_files, header_hotlist,
ownership_risk, layer_violations) share a standard scope vocabulary:
identity (``--target`` / ``--target-glob`` / ``--target-type``), structural
(``--source-dir`` / ``--module`` / ``--team``), relationship (``--build-set``
/ ``--impact-set``), and thresholds (``--min-target-build-time-ms``, etc.).
Scope flags compose as intersection, with excludes applied last. See
``_common.add_scope_args`` for the full vocabulary.

Single-target drill-downs (target_summary, rebuild_impact) use their own
``--target`` / ``--file`` selection and do not apply the shared scope.

Scripts
-------
hotspots
    Refactor targeting: rank targets by build cost × churn × blast radius.
rebuild_impact
    Blast radius: what must rebuild if target (or file) X changes, and how
    often does it change?
critical_path
    Critical path duration, parallelism ceiling, and near-critical targets.
target_summary
    Deep-dive report on a single CMake target.
slow_files
    Individual files with pathological compile times, template blowup, or
    preprocessed bloat.
header_hotlist
    Headers ranked by their impact on the build (fan-in × size × churn).
ownership_risk
    Bus-factor / knowledge-concentration risk across targets.
layer_violations
    Upward and lateral dependency edges violating strict layering.
"""
