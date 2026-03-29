# Consolidated Data Schema

Reference for the parquet files produced by the build-optimisation pipeline.
All files are written to `data/processed/` (configured via `config.yaml`).

---

## Overview

The pipeline consolidates raw instrumentation data into four parquet files:

| File | Script | Grain | Primary / Composite Key |
|---|---|---|---|
| `file_metrics.parquet` | `scripts/consolidate/build_file_metrics.py` | One row per source file | `source_file` |
| `target_metrics.parquet` | `scripts/consolidate/build_target_metrics.py` | One row per CMake target | `cmake_target` |
| `edge_list.parquet` | `scripts/consolidate/build_edge_list.py` | One row per dependency edge | `(source_target, dest_target)` |
| `contributor_target_commits.parquet` | `scripts/consolidate/build_contributor_metrics.py` | One row per contributor × target | `(contributor, cmake_target)` |

The first three are the primary analytical tables. A further set of parquet files
(`contributor_groups`, `target_ownership`, `coupling_metrics`) are produced by
the Jupyter notebooks; see [Notebook-Produced Tables](#notebook-produced-tables).

---

## `file_metrics.parquet`

**Primary key:** `source_file` (canonical absolute path)
**Foreign key:** `cmake_target` → `target_metrics.cmake_target`

Schema defined in `src/build_optimiser/metrics.py` (`FILE_METRICS_SCHEMA`).

### Identity

| Field | Type | Description |
|---|---|---|
| `source_file` | `string` | Canonical absolute path to the source file (join key) |
| `cmake_target` | `string` | CMake target that compiles this file |
| `is_generated` | `bool` | `true` for generated files (e.g. protobuf, bison output) |
| `language` | `string` | Compiler language: `C`, `CXX`, etc. |

Source: `cmake_file_api/files.json` (spine).

### Compile Timing

| Field | Type | Description |
|---|---|---|
| `compile_time_ms` | `int64` | Wall-clock duration for the compile step (from `.ninja_log`) |

Source: `ninja_log.csv` (`step_type == "compile"`, `duration_ms` column).

### GCC Phase Breakdown (`-ftime-report`)

| Field | Type | Description |
|---|---|---|
| `gcc_parse_time_ms` | `float64` | GCC "phase parsing" time, converted from seconds to ms |
| `gcc_template_instantiation_ms` | `float64` | GCC "phase lang. deferred" (template instantiation) time |
| `gcc_codegen_time_ms` | `float64` | GCC "phase opt and generate" time |
| `gcc_optimization_time_ms` | `float64` | GCC "phase opt and generate" time (same phase as codegen) |
| `gcc_total_time_ms` | `float64` | GCC total wall-clock time as reported by `-ftime-report` |

Source: `ftime_report.json` (keyed by `source_file`).

> `gcc_codegen_time_ms` and `gcc_optimization_time_ms` are both derived from
> the single GCC "phase opt and generate" phase.

### Source Lines of Code

| Field | Type | Description |
|---|---|---|
| `code_lines` | `int64` | Non-blank, non-comment lines (SLOC) |
| `blank_lines` | `int64` | Blank lines |
| `comment_lines` | `int64` | Comment lines |
| `source_size_bytes` | `int64` | Raw file size in bytes |

Source: `sloc.csv` (produced by `scripts/collect/04_post_build_metrics.py`).

### Header Inclusion

| Field | Type | Description |
|---|---|---|
| `header_max_depth` | `int64` | Maximum nesting depth of `#include` directives |
| `unique_headers` | `int64` | Number of distinct header files included (transitively) |
| `total_includes` | `int64` | Total count of `#include` directives in the translation unit |
| `header_tree` | `large_utf8` | JSON array of `[depth, path]` pairs representing the full include tree |

Source: `header_data.json` (keyed by `source_file`).

### Preprocessed Size

| Field | Type | Description |
|---|---|---|
| `preprocessed_bytes` | `int64` | Size of preprocessed output (`-E`), a proxy for template expansion cost |

Source: `preprocessed_size.csv`.

### Object File

| Field | Type | Description |
|---|---|---|
| `object_size_bytes` | `int64` | Size of the compiled `.o` file in bytes |

Source: `object_files.csv`.

### Git History

| Field | Type | Description |
|---|---|---|
| `git_commit_count` | `int64` | Total commits touching this file in the analysis window |
| `git_lines_added` | `int64` | Total lines added across all commits |
| `git_lines_deleted` | `int64` | Total lines deleted across all commits |
| `git_churn` | `int64` | Total lines changed (`added + deleted`) |
| `git_distinct_authors` | `int64` | Number of unique contributors |
| `git_last_change_date` | `string` | ISO 8601 timestamp of the most recent commit touching this file |

Source: `git_history_summary.csv` (produced by `scripts/collect/02_git_history.py`).
All git fields are forced to `0` for generated files (`is_generated == true`).

### Derived Columns

| Field | Type | Formula |
|---|---|---|
| `expansion_ratio` | `float64` | `preprocessed_bytes / source_size_bytes` — template bloat multiplier |
| `compile_rate_lines_per_sec` | `float64` | `code_lines / (compile_time_ms / 1000)` — compilation throughput |
| `object_efficiency` | `float64` | `object_size_bytes / code_lines` — output density |

These are computed in `build_file_metrics.py` after all joins are complete.
Division-by-zero inputs are replaced with `NA` before dividing.

---

## `target_metrics.parquet`

**Primary key:** `cmake_target`
**Referenced by:** `edge_list.source_target`, `edge_list.dest_target`, `contributor_target_commits.cmake_target`

Schema defined in `src/build_optimiser/metrics.py` (`TARGET_METRICS_SCHEMA`).
Aggregation helpers live in `metrics.aggregate_file_metrics_for_target()`.

### Identity

| Field | Type | Description |
|---|---|---|
| `cmake_target` | `string` | CMake target name |
| `target_type` | `string` | One of: `executable`, `static_library`, `shared_library`, `module_library`, `object_library`, `interface_library`, `custom_target` |
| `output_artifact` | `string` | Filename of the primary output (e.g. `libfoo.a`, `my_app`) |

Source: `cmake_file_api/targets.json`.

### Source File Counts

| Field | Type | Description |
|---|---|---|
| `file_count` | `int64` | Total source files belonging to the target |
| `authored_file_count` | `int64` | Hand-written source files (`is_generated == false`) |
| `codegen_file_count` | `int64` | Generated source files (`is_generated == true`) |
| `codegen_ratio` | `float64` | `codegen_file_count / file_count` |

### SLOC

| Field | Type | Description |
|---|---|---|
| `code_lines_total` | `int64` | Sum of `code_lines` across all files |
| `code_lines_authored` | `int64` | Sum from authored files only |
| `code_lines_generated` | `int64` | Sum from generated files only |

### Compile Time — All Files

| Field | Type | Description |
|---|---|---|
| `compile_time_sum_ms` | `int64` | Sum of all file compile times |
| `compile_time_max_ms` | `int64` | Maximum per-file compile time |
| `compile_time_mean_ms` | `float64` | Mean per-file compile time |
| `compile_time_median_ms` | `float64` | Median per-file compile time |
| `compile_time_std_ms` | `float64` | Standard deviation of per-file compile times |
| `compile_time_p90_ms` | `float64` | 90th-percentile compile time |
| `compile_time_p99_ms` | `float64` | 99th-percentile compile time |

### Compile Time — Authored vs Generated

| Field | Type | Description |
|---|---|---|
| `authored_compile_time_sum_ms` | `int64` | Sum for hand-written files |
| `authored_compile_time_max_ms` | `int64` | Max for hand-written files |
| `codegen_compile_time_sum_ms` | `int64` | Sum for generated files |
| `codegen_compile_time_max_ms` | `int64` | Max for generated files |

### GCC Phase Breakdown

| Field | Type | Description |
|---|---|---|
| `gcc_parse_time_sum_ms` | `float64` | Sum of parse-phase times across all files |
| `gcc_template_time_sum_ms` | `float64` | Sum of template-instantiation times (`gcc_template_instantiation_ms`) |
| `gcc_codegen_phase_sum_ms` | `float64` | Sum of opt-and-generate times (`gcc_codegen_time_ms`) |
| `gcc_optimization_time_sum_ms` | `float64` | Sum of optimisation times (`gcc_optimization_time_ms`) |

### Header Metrics

| Field | Type | Description |
|---|---|---|
| `header_depth_max` | `int64` | Maximum `header_max_depth` across all files in the target |
| `header_depth_mean` | `float64` | Mean `header_max_depth` |
| `unique_headers_total` | `int64` | Sum of `unique_headers` (approximation — not a true set union) |
| `total_includes_sum` | `int64` | Sum of `total_includes` |

### Preprocessed Size

| Field | Type | Description |
|---|---|---|
| `preprocessed_bytes_total` | `int64` | Sum of preprocessed bytes |
| `preprocessed_bytes_mean` | `float64` | Mean preprocessed bytes per file |
| `expansion_ratio_mean` | `float64` | Mean expansion ratio across files |

### Object Files

| Field | Type | Description |
|---|---|---|
| `object_size_total_bytes` | `int64` | Sum of all `.o` file sizes |
| `object_file_count` | `int64` | Count of files with a non-null `object_size_bytes` |

### Build Step Timing

These timings come from `.ninja_log` for non-compile steps and are aggregated by target.

| Field | Type | Description |
|---|---|---|
| `codegen_time_ms` | `int64` | Total time for code-generation steps (e.g. protobuf runners) |
| `archive_time_ms` | `int64` | Total time for archive/static-link steps |
| `link_time_ms` | `int64` | Total time for link steps |
| `total_build_time_ms` | `int64` | `compile_time_sum_ms + codegen_time_ms + archive_time_ms + link_time_ms` |

### Git Activity

Computed over authored files only (`is_generated == false`).

| Field | Type | Description |
|---|---|---|
| `git_commit_count_total` | `int64` | Sum of per-file commit counts |
| `git_churn_total` | `int64` | Sum of per-file line churn |
| `git_distinct_authors` | `int64` | Maximum `git_distinct_authors` across authored files |
| `git_hotspot_file_count` | `int64` | Files where `git_commit_count > mean + std_dev` of the target's authored files |

### Dependency Graph Metrics

Computed from a NetworkX `DiGraph` built from `dependencies.json`. Edge direction: A → B means "A depends on B".

| Field | Type | Description |
|---|---|---|
| `direct_dependency_count` | `int64` | Targets this target directly depends on (out-degree, direct edges only) |
| `transitive_dependency_count` | `int64` | Targets reachable only via transitive (non-direct) edges |
| `total_dependency_count` | `int64` | `direct + transitive` dependency count |
| `direct_dependant_count` | `int64` | Targets that directly depend on this target (in-degree, direct edges only) |
| `transitive_dependant_count` | `int64` | All ancestors in the graph (targets that transitively depend on this one) |
| `topological_depth` | `int64` | Longest path from any ancestor (longest shortest path from any ancestor node) |
| `critical_path_contribution_ms` | `int64` | Time contribution on the build critical path — populated by notebook 03, initialised to `0` here |
| `fan_in` | `int64` | Alias for `direct_dependant_count` |
| `fan_out` | `int64` | Alias for `direct_dependency_count` |
| `betweenness_centrality` | `float64` | NetworkX betweenness centrality score |

### File Lists (JSON-serialised)

| Field | Type | Description |
|---|---|---|
| `source_files` | `large_utf8` | JSON array of all source file paths belonging to this target |
| `generated_files` | `large_utf8` | JSON array of generated-file paths in this target |
| `output_files` | `large_utf8` | JSON array of artifact paths (from `targets.json` `artifacts` list) |

---

## `edge_list.parquet`

**Composite key:** `(source_target, dest_target)`
**Foreign keys:** both columns reference `target_metrics.cmake_target`

Schema defined in `src/build_optimiser/metrics.py` (`EDGE_LIST_SCHEMA`).

Edge convention: **source depends on dest** (A → B means "A builds after B").

| Field | Type | Description |
|---|---|---|
| `source_target` | `string` | The dependent target (the one that has the dependency) |
| `dest_target` | `string` | The depended-on target |
| `is_direct` | `bool` | `true` if this is a direct (explicitly declared) dependency |
| `dependency_type` | `string` | `"direct"` or `"transitive"` |
| `source_target_type` | `string` | Target type of `source_target` (same values as `target_metrics.target_type`) |
| `dest_target_type` | `string` | Target type of `dest_target` |
| `from_dependency` | `string` | CMake dependency name or specification (nullable) |

Source: `cmake_file_api/dependencies.json` enriched with type lookups from `cmake_file_api/targets.json`.

---

## `contributor_target_commits.parquet`

**Composite key:** `(contributor, cmake_target)`
**Foreign key:** `cmake_target` → `target_metrics.cmake_target`

Schema defined inline in `scripts/consolidate/build_contributor_metrics.py`.

| Field | Type | Description |
|---|---|---|
| `contributor` | `string` | Contributor identifier (email address from git log) |
| `cmake_target` | `string` | CMake target |
| `commit_count` | `int64` | Number of commits by this contributor touching any source file in the target |

Source: `contributor_file_commits.csv` joined to `cmake_file_api/files.json` (file → target mapping), then grouped and summed.
Rows where a file does not map to any known target are dropped.

---

## Notebook-Produced Tables

These files are written by the Jupyter notebooks rather than the consolidation scripts.
They depend on the primary parquets being present and cleaned first (notebook 01).

| File | Produced by | Key | Description |
|---|---|---|---|
| `contributor_groups.parquet` | Notebook 02 | `contributor` | Cluster/group assignment per contributor (hierarchical clustering or NMF on the contributor × target commit matrix) |
| `target_ownership.parquet` | Notebook 02 | `(cmake_target, group_id)` | Ownership score and normalised ownership of each target by each contributor group; `owning_group_id` identifies the dominant group; `hhi` is the Herfindahl-Hirschman Index of ownership concentration |
| `coupling_metrics.parquet` | Notebook 03 | `cmake_target` | Per-target instability, abstractness, and distance-from-main-sequence coupling scores |

---

## Join Relationships

```
file_metrics ──(cmake_target)──> target_metrics
                                     │
                              ┌──────┴──────┐
                    (source_target)    (dest_target)
                              │              │
                         edge_list ──────────┘

target_metrics <──(cmake_target)── contributor_target_commits
                                           │
                                     (contributor)
                                           │
                                  contributor_groups
                                           │
                                    (group_id)
                                           │
                                  target_ownership
```

### Common Join Patterns

#### File → Target (many-to-one)

```python
import pandas as pd

file_df = pd.read_parquet("data/processed/file_metrics.parquet")
target_df = pd.read_parquet("data/processed/target_metrics.parquet")

# Enrich each file row with its target's aggregate metadata
file_with_target = file_df.merge(target_df, on="cmake_target", how="left", suffixes=("_file", "_target"))
```

#### Target → Edges (one-to-many, both directions)

```python
edge_df = pd.read_parquet("data/processed/edge_list.parquet")

# Targets that this target depends on (outgoing edges)
deps_of = edge_df[edge_df["source_target"] == "my_lib"]

# Targets that depend on this target (incoming edges)
users_of = edge_df[edge_df["dest_target"] == "my_lib"]
```

#### Edge List Enriched with Target Metadata

```python
# Attach source-target and dest-target metrics to each edge
enriched_edges = (
    edge_df
    .merge(target_df.add_prefix("src_"), left_on="source_target", right_on="src_cmake_target")
    .merge(target_df.add_prefix("dst_"), left_on="dest_target",   right_on="dst_cmake_target")
)
```

#### Target → Contributor Activity

```python
contrib_df = pd.read_parquet("data/processed/contributor_target_commits.parquet")

# All contributors who have touched a given target
target_contrib = contrib_df[contrib_df["cmake_target"] == "my_lib"]

# All targets a given contributor has touched
contrib_targets = contrib_df[contrib_df["contributor"] == "dev@example.com"]
```

#### Full Cross-Cutting View (file + target + contributor)

```python
# Start from file grain, enrich with target metrics, then join contributor ownership
ownership_df = pd.read_parquet("data/processed/target_ownership.parquet")
groups_df    = pd.read_parquet("data/processed/contributor_groups.parquet")

view = (
    file_df
    .merge(target_df, on="cmake_target", suffixes=("", "_target"))
    .merge(ownership_df[["cmake_target", "owning_group_id"]], on="cmake_target", how="left")
)
```

---

## Granularity Reference

| Analysis Level | Recommended Table(s) | Notes |
|---|---|---|
| Per source file | `file_metrics` | Finest grain; includes all raw measurements |
| Per CMake target | `target_metrics` | Pre-aggregated; avoids manual `groupby` |
| Per CMake target (custom aggregation) | `file_metrics` grouped by `cmake_target` | Useful when you need metrics not in the schema |
| Per dependency edge | `edge_list` | Optionally enrich with `target_metrics` via two joins |
| Per contributor × target | `contributor_target_commits` | Join to `target_metrics` for target context |
| Per contributor group | `target_ownership` joined to `contributor_groups` | Team-level ownership view |
| Whole-project | Aggregate any of the above | Sum/mean across all rows |

---

## Field Source Map

Summary of which raw data file feeds which column group in `file_metrics.parquet`.

| Raw Source | Columns Populated |
|---|---|
| `cmake_file_api/files.json` | `source_file`, `cmake_target`, `is_generated`, `language` (spine) |
| `ninja_log.csv` | `compile_time_ms` |
| `ftime_report.json` | `gcc_parse_time_ms`, `gcc_template_instantiation_ms`, `gcc_codegen_time_ms`, `gcc_optimization_time_ms`, `gcc_total_time_ms` |
| `header_data.json` | `header_max_depth`, `unique_headers`, `total_includes`, `header_tree` |
| `sloc.csv` | `code_lines`, `blank_lines`, `comment_lines`, `source_size_bytes` |
| `object_files.csv` | `object_size_bytes` |
| `preprocessed_size.csv` | `preprocessed_bytes` |
| `git_history_summary.csv` | `git_commit_count`, `git_lines_added`, `git_lines_deleted`, `git_churn`, `git_distinct_authors`, `git_last_change_date` |
| Derived (in script) | `expansion_ratio`, `compile_rate_lines_per_sec`, `object_efficiency` |
