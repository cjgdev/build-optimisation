"""Ad-hoc analysis scripts for build engineers.

Each module in this package is a self-contained CLI that answers a specific
question about a collected build snapshot. All scripts read parquet data
produced by ``scripts/consolidate/``.

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
