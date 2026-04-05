# Data Dictionary — Complete Attribute Reference

## Overview

This document catalogues every field in every output file produced by the build
optimisation pipeline. It covers three categories:

1. **Primary parquet files** — produced by the collection/consolidation scripts,
   stored in each snapshot's `processed/` directory
2. **Intermediate parquet files** — produced by analysis notebooks, stored in
   `data/intermediate/`
3. **GEXF graph exports** — produced by analysis notebooks for Gephi, stored in
   `data/intermediate/gephi/`

For each file, the document lists every field with its type, source, nullability,
and purpose. Fields introduced by REQ-01 through REQ-05 are tagged with their
requirement reference.

### Conventions

- **PK** = primary key (unique, non-null)
- **FK** = foreign key (references another table)
- **CK** = composite key
- **nullable** = field may contain null/NA values
- Types use pandas/pyarrow conventions: `string`, `int64`, `float64`, `bool`,
  `timestamp[us]`, `large_utf8` (for JSON blobs)

---

## Part 1: Primary Parquet Files

These files are the immutable collected data. They are produced by the
consolidation scripts and stored per-snapshot.

---

### `file_metrics.parquet`

**Grain:** One row per source file (`.cpp`, `.cc`, `.c`)
**Primary key:** `source_file`
**Foreign key:** `cmake_target` → `target_metrics.cmake_target`

#### Identity

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 1 | `source_file` | string | PK | cmake_file_api/files.json | Canonical absolute path to the source file |
| 2 | `cmake_target` | string | FK | cmake_file_api/files.json | CMake target that compiles this file |
| 3 | `is_generated` | bool | no | cmake_file_api/files.json | True for generated files (protobuf, bison, etc.) |
| 4 | `language` | string | no | cmake_file_api/files.json | Compiler language: `C`, `CXX`, etc. |

#### Compile Timing

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 5 | `compile_time_ms` | int64 | no | ninja_log.csv | Wall-clock compile duration in milliseconds |

#### GCC Phase Breakdown

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 6 | `gcc_parse_time_ms` | float64 | yes | ftime_report.json | GCC parsing phase time (ms) |
| 7 | `gcc_template_instantiation_ms` | float64 | yes | ftime_report.json | GCC template instantiation time (ms) |
| 8 | `gcc_codegen_time_ms` | float64 | yes | ftime_report.json | GCC opt-and-generate phase time (ms) |
| 9 | `gcc_optimization_time_ms` | float64 | yes | ftime_report.json | Same phase as codegen — identical values |
| 10 | `gcc_total_time_ms` | float64 | yes | ftime_report.json | GCC total wall-clock time (ms) |

**Note:** Fields 8 and 9 are derived from the same GCC phase. Do not use both
in a regression model — they are perfectly correlated.

#### Source Lines of Code

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 11 | `code_lines` | int64 | no | sloc.csv | Non-blank, non-comment lines (SLOC) |
| 12 | `blank_lines` | int64 | no | sloc.csv | Blank lines |
| 13 | `comment_lines` | int64 | no | sloc.csv | Comment lines |
| 14 | `source_size_bytes` | int64 | no | sloc.csv | Raw file size in bytes |

#### Header Inclusion

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 15 | `header_max_depth` | int64 | yes | header_data.json | Maximum nesting depth of #include directives |
| 16 | `unique_headers` | int64 | yes | header_data.json | Distinct headers included (transitively) |
| 17 | `total_includes` | int64 | yes | header_data.json | Total #include directive count in the TU |
| 18 | `header_tree` | large_utf8 | yes | header_data.json | JSON array of `[depth, path]` pairs — full include tree |

#### Preprocessed and Object Sizes

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 19 | `preprocessed_bytes` | int64 | yes | preprocessed_size.csv | Size of preprocessed output (`-E`) in bytes |
| 20 | `object_size_bytes` | int64 | yes | object_files.csv | Size of compiled `.o` file in bytes |

#### Git History

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 21 | `git_commit_count` | int64 | no | git_history_summary.csv | Total commits touching this file |
| 22 | `git_lines_added` | int64 | no | git_history_summary.csv | Total lines added across all commits |
| 23 | `git_lines_deleted` | int64 | no | git_history_summary.csv | Total lines deleted across all commits |
| 24 | `git_churn` | int64 | no | git_history_summary.csv | `lines_added + lines_deleted` |
| 25 | `git_distinct_authors` | int64 | no | git_history_summary.csv | Unique contributor count |
| 26 | `git_last_change_date` | string | yes | git_history_summary.csv | ISO 8601 timestamp of most recent commit |
| 27 | `git_first_change_date` | string | yes | Stage 0a | ISO 8601 timestamp of earliest commit |

**Note:** All git fields are zeroed for generated files (`is_generated == true`).
Field 27 is added by Stage 0a.

#### Derived Columns

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 28 | `expansion_ratio` | float64 | yes | Computed | `preprocessed_bytes / source_size_bytes` |
| 29 | `compile_rate_lines_per_sec` | float64 | yes | Computed | `code_lines / (compile_time_ms / 1000)` |
| 30 | `object_efficiency` | float64 | yes | Computed | `object_size_bytes / code_lines` |

---

### `target_metrics.parquet`

**Grain:** One row per CMake target
**Primary key:** `cmake_target`

#### Identity

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 1 | `cmake_target` | string | PK | cmake_file_api/targets.json | CMake target name |
| 2 | `target_type` | string | no | cmake_file_api/targets.json | `executable`, `static_library`, `shared_library`, `module_library`, `object_library`, `interface_library`, `custom_target` |
| 3 | `output_artifact` | string | yes | cmake_file_api/targets.json | Primary output filename (e.g., `libfoo.a`) |
| 4 | `source_directory` | string | yes | Stage 0c | Path to the CMakeLists.txt directory |
| 5 | `directory_depth` | int64 | yes | Stage 0c | Path depth relative to project root |

#### Source File Counts

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 6 | `file_count` | int64 | no | Aggregated | Total source files in the target |
| 7 | `authored_file_count` | int64 | no | Aggregated | Hand-written source files |
| 8 | `codegen_file_count` | int64 | no | Aggregated | Generated source files |
| 9 | `codegen_ratio` | float64 | no | Computed | `codegen_file_count / file_count` |

#### SLOC Aggregates

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 10 | `code_lines_total` | int64 | no | Aggregated | Sum of `code_lines` across all files |
| 11 | `code_lines_authored` | int64 | no | Aggregated | Sum from authored files only |
| 12 | `code_lines_generated` | int64 | no | Aggregated | Sum from generated files only |

#### Compile Time — All Files

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 13 | `compile_time_sum_ms` | int64 | no | Aggregated | Sum of per-file compile times |
| 14 | `compile_time_max_ms` | int64 | no | Aggregated | Maximum per-file compile time |
| 15 | `compile_time_mean_ms` | float64 | no | Aggregated | Mean per-file compile time |
| 16 | `compile_time_median_ms` | float64 | no | Aggregated | Median per-file compile time |
| 17 | `compile_time_std_ms` | float64 | yes | Aggregated | Std dev of per-file compile times |
| 18 | `compile_time_p90_ms` | float64 | no | Aggregated | 90th percentile compile time |
| 19 | `compile_time_p99_ms` | float64 | no | Aggregated | 99th percentile compile time |

#### Compile Time — Authored vs Generated

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 20 | `authored_compile_time_sum_ms` | int64 | no | Aggregated | Sum for hand-written files |
| 21 | `authored_compile_time_max_ms` | int64 | no | Aggregated | Max for hand-written files |
| 22 | `codegen_compile_time_sum_ms` | int64 | no | Aggregated | Sum for generated files |
| 23 | `codegen_compile_time_max_ms` | int64 | no | Aggregated | Max for generated files |

#### GCC Phase Breakdown (Aggregated)

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 24 | `gcc_parse_time_sum_ms` | float64 | yes | Aggregated | Sum of parse-phase times |
| 25 | `gcc_template_time_sum_ms` | float64 | yes | Aggregated | Sum of template-instantiation times |
| 26 | `gcc_codegen_phase_sum_ms` | float64 | yes | Aggregated | Sum of opt-and-generate times |
| 27 | `gcc_optimization_time_sum_ms` | float64 | yes | Aggregated | Sum of optimisation times |

#### Header Metrics (Aggregated)

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 28 | `header_depth_max` | int64 | yes | Aggregated | Max include depth across files |
| 29 | `header_depth_mean` | float64 | yes | Aggregated | Mean include depth |
| 30 | `unique_headers_total` | int64 | yes | Aggregated | Sum of per-file unique_headers (approximation) |
| 31 | `total_includes_sum` | int64 | yes | Aggregated | Sum of per-file total_includes |

**Note:** Field 30 is a sum approximation, not a true set union across files.

#### Preprocessed Size (Aggregated)

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 32 | `preprocessed_bytes_total` | int64 | yes | Aggregated | Sum of preprocessed bytes |
| 33 | `preprocessed_bytes_mean` | float64 | yes | Aggregated | Mean preprocessed bytes per file |
| 34 | `expansion_ratio_mean` | float64 | yes | Aggregated | Mean expansion ratio across files |

#### Object Files (Aggregated)

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 35 | `object_size_total_bytes` | int64 | yes | Aggregated | Sum of `.o` file sizes |
| 36 | `object_file_count` | int64 | no | Aggregated | Count of files with non-null object_size |

#### Build Step Timing

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 37 | `codegen_time_ms` | int64 | no | ninja_log.csv | Total code-generation step time |
| 38 | `archive_time_ms` | int64 | no | ninja_log.csv | Total archive/static-link time |
| 39 | `link_time_ms` | int64 | no | ninja_log.csv | Total link step time |
| 40 | `total_build_time_ms` | int64 | no | Computed | `compile + codegen + archive + link` |

#### Git Activity (Aggregated)

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 41 | `git_commit_count_total` | int64 | no | Aggregated | Sum of per-file commit counts (authored only) |
| 42 | `git_churn_total` | int64 | no | Aggregated | Sum of per-file churn (authored only) |
| 43 | `git_distinct_authors` | int64 | no | Aggregated | Max distinct_authors across authored files |
| 44 | `git_hotspot_file_count` | int64 | no | Computed | Files with commits > mean + std_dev |

#### Dependency Graph Metrics

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 45 | `direct_dependency_count` | int64 | no | Computed | Out-degree (direct deps) |
| 46 | `transitive_dependency_count` | int64 | no | Computed | Non-direct transitive deps |
| 47 | `total_dependency_count` | int64 | no | Computed | `direct + transitive` |
| 48 | `direct_dependant_count` | int64 | no | Computed | In-degree (direct dependants) |
| 49 | `transitive_dependant_count` | int64 | no | Computed | All transitive dependants |
| 50 | `topological_depth` | int64 | no | Computed | Longest path from any ancestor |
| 51 | `critical_path_contribution_ms` | int64 | no | Notebook 03 | Time on critical path (0 if not on path) |
| 52 | `fan_in` | int64 | no | Alias | Same as `direct_dependant_count` |
| 53 | `fan_out` | int64 | no | Alias | Same as `direct_dependency_count` |
| 54 | `betweenness_centrality` | float64 | no | Computed | NetworkX betweenness centrality |

#### File Lists (JSON)

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 55 | `source_files` | large_utf8 | yes | cmake_file_api | JSON array of source file paths |
| 56 | `generated_files` | large_utf8 | yes | cmake_file_api | JSON array of generated file paths |
| 57 | `output_files` | large_utf8 | yes | cmake_file_api | JSON array of artifact paths |

---

### `edge_list.parquet`

**Grain:** One row per dependency edge
**Composite key:** `(source_target, dest_target)`
**Convention:** source depends on dest (A → B means "A builds after B")

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 1 | `source_target` | string | CK, FK | cmake_file_api | The dependent target |
| 2 | `dest_target` | string | CK, FK | cmake_file_api | The depended-upon target |
| 3 | `is_direct` | bool | no | cmake_file_api | True if explicitly declared |
| 4 | `dependency_type` | string | no | cmake_file_api | `"direct"` or `"transitive"` |
| 5 | `source_target_type` | string | no | Enriched | Target type of source |
| 6 | `dest_target_type` | string | no | Enriched | Target type of dest |
| 7 | `from_dependency` | string | yes | cmake_file_api | CMake dependency specification |
| 8 | `cmake_visibility` | string | no | Stage 0c | `PUBLIC`, `PRIVATE`, `INTERFACE`, `UNKNOWN`, or `TRANSITIVE` |

---

### `contributor_target_commits.parquet`

**Grain:** One row per contributor × target
**Composite key:** `(contributor, cmake_target)`

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 1 | `contributor` | string | CK | git log | Contributor email address |
| 2 | `cmake_target` | string | CK, FK | Joined | CMake target name |
| 3 | `commit_count` | int64 | no | Aggregated | Commits by this contributor to this target |

---

### `git_commit_log.parquet`

**Grain:** One row per commit × file
**Added by:** Stage 0a

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 1 | `commit_hash` | string | no | git log | Git commit SHA |
| 2 | `timestamp` | timestamp[us] | no | git log | Commit timestamp (UTC) |
| 3 | `contributor` | string | no | git log | Author email |
| 4 | `source_file` | string | FK | git log | Canonical file path |
| 5 | `lines_added` | int64 | no | git log | Lines added in this commit |
| 6 | `lines_deleted` | int64 | no | git log | Lines deleted in this commit |

**Constraints:** Merge commits excluded. Commits touching >500 files excluded.

---

### `header_edges.parquet`

**Grain:** One row per include relationship (deduplicated within each TU)
**Added by:** Stage 0b

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 1 | `includer` | string | no | header_data.json | File containing the #include |
| 2 | `included` | string | no | header_data.json | File being included |
| 3 | `depth` | int64 | no | header_data.json | Nesting depth (0 = root TU) |
| 4 | `source_file` | string | FK | header_data.json | Root translation unit |
| 5 | `is_system` | bool | no | Heuristic | System/third-party header |

---

### `header_metrics.parquet`

**Grain:** One row per unique header file
**Primary key:** `header_file`
**Added by:** Stage 0b

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 1 | `header_file` | string | PK | Extracted | Canonical path to the header |
| 2 | `cmake_target` | string | yes | Heuristic | Owning CMake target (nullable) |
| 3 | `sloc` | int64 | no | SLOC tool | Non-blank, non-comment lines |
| 4 | `source_size_bytes` | int64 | no | File stat | Raw file size in bytes |
| 5 | `is_system` | bool | no | Heuristic | System or third-party header |

---

### `build_schedule.parquet`

**Grain:** One row per build step
**Added by:** Stage 0d

| # | Field | Type | Nullable | Source | Description |
|---|---|---|---|---|---|
| 1 | `output_file` | string | no | .ninja_log | Output file path from ninja |
| 2 | `source_file` | string | yes | Mapped | Source file (compile steps only) |
| 3 | `cmake_target` | string | no | Mapped | CMake target this step belongs to |
| 4 | `step_type` | string | no | Classified | `compile`, `codegen`, `archive`, `link`, `other` |
| 5 | `start_time_ms` | int64 | no | .ninja_log | Start timestamp (ms since build start) |
| 6 | `end_time_ms` | int64 | no | .ninja_log | End timestamp (ms since build start) |
| 7 | `duration_ms` | int64 | no | Computed | `end_time_ms - start_time_ms` |

---

### `snapshot metadata.yaml`

**Grain:** One per snapshot directory
**Added by:** REQ-04

| # | Field | Type | Nullable | Description |
|---|---|---|---|---|
| 1 | `label` | string | no | Unique snapshot identifier |
| 2 | `date` | string | no | ISO 8601 collection date |
| 3 | `git_ref` | string | no | Git commit hash |
| 4 | `git_branch` | string | no | Git branch name |
| 5 | `build_config` | string | no | CMake build configuration (Release, Debug) |
| 6 | `compiler` | string | no | Compiler version string |
| 7 | `compiler_flags` | string | no | Key compiler flags |
| 8 | `core_count` | integer | no | CPU cores used for the build |
| 9 | `build_machine` | string | yes | Build machine identifier |
| 10 | `notes` | string | no | Free-text notes |
| 11 | `interventions_applied` | list[string] | no | Changes since baseline (may be empty) |

---

## Part 2: Configuration Files

---

### `config/teams.yaml`

**Added by:** REQ-01

```
teams:                           # list of team objects
  - name: string                 # unique team name
    modules: list[string]        # optional: declared module ownership
    members:                     # list of member objects
      - name: string             # canonical display name
        emails: list[string]     # all known git email aliases

unaffiliated:                    # optional: known non-team contributors
  - name: string
    emails: list[string]
```

**Constraints:** No duplicate emails across all teams/unaffiliated. No empty
teams. All emails non-empty.

---

### `config/modules.yaml`

**Added by:** REQ-02

```
modules:                         # list of module objects
  - name: string                 # unique module name
    description: string          # optional: human-readable purpose
    category: string             # required: shared | domain | infrastructure | test
    owning_team: string          # optional: team name from teams.yaml
    directories: list[string]    # required: source directory prefixes
    target_patterns: list[string] # optional: fnmatch patterns for target names
```

**Constraints:** No duplicate module names. No overlapping directory prefixes.
Category must be one of the four valid values.

---

## Part 3: Intermediate Parquet Files

These files are produced by analysis notebooks and stored in `data/intermediate/`.
They are derived from the primary parquet files and are reproducible by re-running
the notebooks.

---

### `target_features.parquet`

**Produced by:** Notebook 02 (Global Profile)
**Grain:** One row per CMake target

Contains all columns from `target_metrics.parquet` plus:

| # | Field | Type | Source | Description |
|---|---|---|---|---|
| 1 | `segment` | int64 | k-means | Cluster assignment from segmentation |
| 2 | `segment_label` | string | Manual | Descriptive name for the segment |

---

### `critical_path.parquet`

**Produced by:** Notebook 03 (Build Performance)
**Grain:** One row per CMake target

| # | Field | Type | Nullable | Description |
|---|---|---|---|---|
| 1 | `cmake_target` | string | PK | Target name |
| 2 | `build_time_ms` | int64 | no | Target's own build time |
| 3 | `earliest_start_ms` | float64 | no | Earliest possible start time |
| 4 | `earliest_finish_ms` | float64 | no | Earliest possible finish time |
| 5 | `latest_start_ms` | float64 | no | Latest start without delaying build |
| 6 | `latest_finish_ms` | float64 | no | Latest finish without delaying build |
| 7 | `slack_ms` | float64 | no | `latest_start - earliest_start` |
| 8 | `on_critical_path` | bool | no | True if slack == 0 |

---

### `header_impact.parquet`

**Produced by:** Notebook 04 (Header Analysis)
**Grain:** One row per header file

| # | Field | Type | Nullable | Description |
|---|---|---|---|---|
| 1 | `file` | string | PK | Header file path |
| 2 | `direct_fan_in` | int64 | no | Files directly including this header |
| 3 | `transitive_fan_in` | int64 | no | Files transitively including this header |
| 4 | `direct_fan_out` | int64 | no | Headers this file includes |
| 5 | `sloc` | int64 | yes | Lines of code |
| 6 | `source_size_bytes` | int64 | yes | File size |
| 7 | `preprocessed_bytes` | int64 | yes | Preprocessed contribution |
| 8 | `n_commits` | int64 | no | Git commit count |
| 9 | `impact_score` | float64 | no | `fan_in × size × (1 + commits)` |
| 10 | `pagerank` | float64 | no | PageRank score |
| 11 | `is_header` | bool | no | True for header files |

---

### `graph_analysis.parquet`

**Produced by:** Notebook 05 (Dependency Graph)
**Grain:** One row per CMake target

| # | Field | Type | Nullable | Description |
|---|---|---|---|---|
| 1 | `cmake_target` | string | PK | Target name |
| 2 | `layer` | int64 | no | Architectural layer (0 = leaf) |
| 3 | `betweenness` | float64 | no | Betweenness centrality |
| 4 | `pagerank` | float64 | no | PageRank score |
| 5 | `in_degree` | int64 | no | Dependant count |
| 6 | `out_degree` | int64 | no | Dependency count |
| 7 | `n_transitive_deps` | int64 | no | Transitive dependency count |
| 8 | `transitive_fraction` | float64 | no | Fraction of codebase |

---

### `communities.parquet`

**Produced by:** Notebook 06 (Modularity)
**Grain:** One row per CMake target

| # | Field | Type | Nullable | Description |
|---|---|---|---|---|
| 1 | `cmake_target` | string | PK | Target name |
| 2 | `community` | int64 | no | Community label (best partition) |
| 3 | `detection_method` | string | no | Algorithm used (e.g., `louvain_1.0`) |

---

### `feature_configurations.parquet`

**Produced by:** Notebook 06 (Modularity)
**Grain:** One row per community or module

| # | Field | Type | Nullable | Description |
|---|---|---|---|---|
| 1 | `feature_id` | int64 or string | PK | Community ID or module name |
| 2 | `own_targets` | int64 | no | Targets in the feature itself |
| 3 | `transitive_dep_targets` | int64 | no | External targets needed |
| 4 | `total_build_set` | int64 | no | `own + transitive deps` |
| 5 | `build_fraction` | float64 | no | `total_build_set / total_targets` |
| 6 | `estimated_build_time_ms` | int64 | yes | Sum of build times for the build set |
| 7 | `estimated_build_time_fraction` | float64 | yes | Fraction of total build time |
| 8 | `own_target_list` | large_utf8 | no | JSON array of own target names |
| 9 | `shared_deps_list` | large_utf8 | no | JSON array of shared dep target names |

---

### `target_ownership.parquet`

**Produced by:** Notebook 02 (existing) or Notebook 06 with REQ-01
**Grain:** One row per CMake target

| # | Field | Type | Nullable | Description |
|---|---|---|---|---|
| 1 | `cmake_target` | string | PK | Target name |
| 2 | `owning_team` | string | yes | Team with the most commits (REQ-01) |
| 3 | `owning_team_share` | float64 | no | Fraction of commits by owning team |
| 4 | `contributor_count` | int64 | no | Total unique contributors (canonical) |
| 5 | `team_count` | int64 | no | Number of distinct teams |
| 6 | `total_commits` | int64 | no | Total commits |
| 7 | `ownership_hhi` | float64 | no | Herfindahl-Hirschman Index (REQ-01) |
| 8 | `cross_team_fraction` | float64 | no | `1 - owning_team_share` (REQ-01) |
| 9 | `top_contributor` | string | yes | Individual with most commits |
| 10 | `top_contributor_team` | string | yes | Team of top contributor |
| 11 | `top_contributor_share` | float64 | no | Fraction by top contributor |
| 12 | `unresolved_fraction` | float64 | no | Fraction with unknown emails (REQ-01) |

---

### `module_assignments.parquet`

**Produced by:** Notebook 05 or 06 with REQ-02
**Grain:** One row per CMake target

| # | Field | Type | Nullable | Description |
|---|---|---|---|---|
| 1 | `cmake_target` | string | PK | Target name |
| 2 | `module` | string | yes | Assigned module name (null if unassigned) |
| 3 | `module_category` | string | yes | shared/domain/infrastructure/test |

---

### `module_metrics.parquet`

**Produced by:** Notebook 06 with REQ-02
**Grain:** One row per module

| # | Field | Type | Nullable | Description |
|---|---|---|---|---|
| 1 | `module` | string | PK | Module name |
| 2 | `category` | string | no | shared/domain/infrastructure/test |
| 3 | `owning_team` | string | yes | From module config |
| 4 | `target_count` | int64 | no | Targets in the module |
| 5 | `executable_count` | int64 | no | Executable targets |
| 6 | `library_count` | int64 | no | Library targets |
| 7 | `file_count` | int64 | no | Total source files |
| 8 | `total_sloc` | int64 | no | Total lines of code |
| 9 | `total_build_time_ms` | int64 | no | Sum of build times |
| 10 | `total_compile_time_ms` | int64 | no | Sum of compile times |
| 11 | `total_link_time_ms` | int64 | no | Sum of link times |
| 12 | `codegen_ratio` | float64 | no | Generated code fraction |
| 13 | `internal_dep_count` | int64 | no | Dependencies within module |
| 14 | `external_dep_count` | int64 | no | Dependencies on other modules |
| 15 | `self_containment` | float64 | no | `internal / (internal + external)` |
| 16 | `dependant_module_count` | int64 | no | Modules depending on this one |
| 17 | `dependency_module_count` | int64 | no | Modules this one depends on |
| 18 | `critical_path_target_count` | int64 | no | Targets on critical path |
| 19 | `build_fraction` | float64 | no | Fraction of codebase for this feature |

---

### `pch_analysis.parquet`

**Produced by:** Notebook 04 with REQ-03
**Grain:** One row per target analysed

| # | Field | Type | Nullable | Description |
|---|---|---|---|---|
| 1 | `cmake_target` | string | PK | Target name |
| 2 | `source_file_count` | int64 | no | Files in the target |
| 3 | `current_compile_time_ms` | int64 | no | Current total compile time |
| 4 | `estimated_savings_ms` | float64 | no | Estimated time reduction |
| 5 | `savings_fraction` | float64 | no | `savings / current_compile_time` |
| 6 | `pch_header_count` | int64 | no | Proposed PCH header count |
| 7 | `risk_header_count` | int64 | no | Volatile headers in proposed PCH |
| 8 | `recommendation` | string | no | `recommended`, `marginal`, `not_recommended` |
| 9 | `pch_headers` | large_utf8 | no | JSON array of proposed PCH header paths |

---

### `recommendations.parquet`

**Produced by:** Notebook 07 (Recommendations)
**Grain:** One row per proposed intervention

| # | Field | Type | Nullable | Description |
|---|---|---|---|---|
| 1 | `type` | string | no | InterventionType name |
| 2 | `description` | string | no | Human-readable summary |
| 3 | `targets_affected` | large_utf8 | no | JSON array of target names |
| 4 | `impact_ms` | float64 | no | Estimated build time reduction |
| 5 | `effort_days` | float64 | no | Estimated engineering effort |
| 6 | `confidence` | float64 | no | 0–1 confidence in the estimate |
| 7 | `team` | string | yes | Owning team if determinable |
| 8 | `module` | string | yes | Owning module if determinable |
| 9 | `rationale` | string | no | Why this intervention was suggested |
| 10 | `pareto_optimal` | bool | no | True if on the Pareto frontier |
| 11 | `category` | string | no | `quick_win`, `medium`, `strategic` |

---

### `comparison_global_deltas.parquet`

**Produced by:** Notebook 09 (Comparison) — REQ-04
**Grain:** One row per metric

| # | Field | Type | Nullable | Description |
|---|---|---|---|---|
| 1 | `metric` | string | PK | Metric name |
| 2 | `before` | float64 | no | Value in earlier snapshot |
| 3 | `after` | float64 | no | Value in later snapshot |
| 4 | `delta` | float64 | no | `after - before` |
| 5 | `delta_pct` | float64 | no | Percentage change |
| 6 | `improved` | bool | no | True if the change is an improvement |

---

### `comparison_target_deltas.parquet`

**Produced by:** Notebook 09 (Comparison) — REQ-04
**Grain:** One row per target (union of both snapshots)

| # | Field | Type | Nullable | Description |
|---|---|---|---|---|
| 1 | `cmake_target` | string | PK | Target name |
| 2 | `status` | string | no | `unchanged`, `improved`, `regressed`, `new`, `removed` |
| 3 | `build_time_before_ms` | float64 | yes | Build time in earlier snapshot |
| 4 | `build_time_after_ms` | float64 | yes | Build time in later snapshot |
| 5 | `build_time_delta_ms` | float64 | no | Change in build time |
| 6 | `build_time_delta_pct` | float64 | yes | Percentage change |
| 7 | `sloc_before` | int64 | yes | SLOC in earlier snapshot |
| 8 | `sloc_after` | int64 | yes | SLOC in later snapshot |
| 9 | `dep_count_before` | int64 | yes | Dependency count before |
| 10 | `dep_count_after` | int64 | yes | Dependency count after |
| 11 | `dep_count_delta` | int64 | no | Change in dependency count |

---

### `trend_data.parquet`

**Produced by:** Notebook 10 (Trend Analysis) — REQ-04
**Grain:** One row per snapshot

| # | Field | Type | Nullable | Description |
|---|---|---|---|---|
| 1 | `label` | string | PK | Snapshot label |
| 2 | `date` | string | no | Snapshot date |
| 3 | `total_build_time_ms` | int64 | no | Total build time |
| 4 | `total_compile_time_ms` | int64 | no | Total compile time |
| 5 | `total_link_time_ms` | int64 | no | Total link time |
| 6 | `target_count` | int64 | no | Number of targets |
| 7 | `file_count` | int64 | no | Number of source files |
| 8 | `total_sloc` | int64 | no | Total lines of code |
| 9 | `total_preprocessed_bytes` | int64 | no | Total preprocessed output |
| 10 | `edge_count` | int64 | no | Dependency edge count |
| 11 | `mean_dep_count` | float64 | no | Average deps per target |
| 12 | `codegen_ratio` | float64 | no | Global codegen fraction |

---

## Part 4: GEXF Graph Exports

GEXF files are written by `src/buildanalysis/export.py` and stored in
`data/intermediate/gephi/`. Each is loaded into Gephi for interactive
visual exploration.

GEXF supports typed attributes: `string`, `float`, `integer`, `boolean`.
All values must be native Python types (not numpy). Null/NA values must
be replaced with defaults before writing.

---

### `dependency_graph.gexf`

**Produced by:** Notebook 05 / `export_dependency_graph`
**Graph type:** Directed
**~3,000 nodes, ~8,000 edges**

#### Node Attributes

| # | Attribute | GEXF Type | Default | Source | Gephi Use |
|---|---|---|---|---|---|
| 1 | `label` | string | target name | cmake_target | Display label |
| 2 | `target_type` | string | from metadata | target_metrics | Partition |
| 3 | `module` | string | `"unassigned"` | REQ-02 | Partition/colour |
| 4 | `module_category` | string | `"unknown"` | REQ-02 | Partition |
| 5 | `team` | string | `"unknown"` | REQ-01 | Partition/colour |
| 6 | `source_directory` | string | `""` | target_metrics | Filter/tooltip |
| 7 | `compile_time_s` | float | `0.0` | compile_time_sum_ms / 1000 | Sizing |
| 8 | `total_build_time_s` | float | `0.0` | total_build_time_ms / 1000 | Sizing |
| 9 | `link_time_s` | float | `0.0` | link_time_ms / 1000 | Sizing |
| 10 | `codegen_time_s` | float | `0.0` | codegen_time_ms / 1000 | Sizing |
| 11 | `file_count` | integer | `0` | target_metrics | Sizing |
| 12 | `code_lines` | integer | `0` | code_lines_total | Sizing |
| 13 | `preprocessed_mb` | float | `0.0` | preprocessed_bytes_total / 1e6 | Sizing |
| 14 | `codegen_ratio` | float | `0.0` | target_metrics | Colour gradient |
| 15 | `layer` | integer | `-1` | compute_layer_assignments | Filter/hierarchical layout |
| 16 | `community` | integer | `-1` | detect_communities | Partition/colour |
| 17 | `betweenness` | float | `0.0` | compute_centrality_metrics | Sizing/ranking |
| 18 | `pagerank` | float | `0.0` | compute_centrality_metrics | Sizing/ranking |
| 19 | `in_degree` | integer | `0` | graph.in_degree | Filter/ranking |
| 20 | `out_degree` | integer | `0` | graph.out_degree | Filter/ranking |
| 21 | `transitive_dep_count` | integer | `0` | compute_transitive_deps | Filter |
| 22 | `transitive_dep_fraction` | float | `0.0` | computed | Colour gradient |
| 23 | `on_critical_path` | boolean | `false` | CriticalPathResult | Filter |
| 24 | `slack_s` | float | `0.0` | slack_ms / 1000 | Colour gradient |
| 25 | `git_commit_count` | integer | `0` | git_commit_count_total | Sizing |
| 26 | `git_churn` | integer | `0` | git_churn_total | Colour gradient |
| 27 | `ownership_hhi` | float | `0.0` | REQ-01 target_ownership | Colour gradient |
| 28 | `cross_team_fraction` | float | `0.0` | REQ-01 target_ownership | Colour gradient |
| 29 | `contributor_count` | integer | `0` | target_ownership | Sizing |

#### Edge Attributes

| # | Attribute | GEXF Type | Default | Source | Gephi Use |
|---|---|---|---|---|---|
| 1 | `cmake_visibility` | string | `"unknown"` | edge_list | Filter |
| 2 | `is_cross_community` | boolean | computed | community comparison | Filter |
| 3 | `is_cross_module` | boolean | `false` | REQ-02 module comparison | Filter |
| 4 | `is_cross_team` | boolean | `false` | REQ-01 team comparison | Filter |
| 5 | `is_layer_violation` | boolean | computed | layer comparison | Filter |
| 6 | `source_module` | string | `"unassigned"` | REQ-02 | Colour |
| 7 | `dest_module` | string | `"unassigned"` | REQ-02 | Colour |

---

### `module_graph.gexf`

**Produced by:** Notebook 06 / `export_module_graph`
**Graph type:** Directed
**~15–25 nodes**
**Added by:** REQ-02, REQ-05

#### Node Attributes

| # | Attribute | GEXF Type | Default | Source | Gephi Use |
|---|---|---|---|---|---|
| 1 | `label` | string | module name | module config | Display label |
| 2 | `category` | string | from config | module config | Partition/colour |
| 3 | `owning_team` | string | `"unknown"` | module config | Label |
| 4 | `target_count` | integer | `0` | module_metrics | Sizing |
| 5 | `total_build_time_s` | float | `0.0` | total_build_time_ms / 1000 | Sizing |
| 6 | `total_sloc` | integer | `0` | module_metrics | Sizing |
| 7 | `file_count` | integer | `0` | module_metrics | Sizing |
| 8 | `codegen_ratio` | float | `0.0` | module_metrics | Colour gradient |
| 9 | `self_containment` | float | `0.0` | module_metrics | Colour gradient |
| 10 | `build_fraction` | float | `0.0` | feature_configurations | Colour gradient |
| 11 | `internal_dep_count` | integer | `0` | module_metrics | Tooltip |
| 12 | `external_dep_count` | integer | `0` | module_metrics | Tooltip |
| 13 | `critical_path_target_count` | integer | `0` | module_metrics | Sizing |

#### Edge Attributes

| # | Attribute | GEXF Type | Default | Source | Gephi Use |
|---|---|---|---|---|---|
| 1 | `weight` | integer | `1` | target-level edge count | Sizing |
| 2 | `public_count` | integer | `0` | PUBLIC edge count | Tooltip |
| 3 | `private_count` | integer | `0` | PRIVATE edge count | Tooltip |
| 4 | `is_cross_category` | boolean | computed | both domain modules | Filter |
| 5 | `is_bidirectional` | boolean | computed | deps in both directions | Filter |

---

### `include_graph.gexf`

**Produced by:** Notebook 04 / `export_include_graph`
**Graph type:** Directed
**~30,000 nodes (with system headers excluded)**

#### Node Attributes

| # | Attribute | GEXF Type | Default | Source | Gephi Use |
|---|---|---|---|---|---|
| 1 | `label` | string | basename | filename only | Display label |
| 2 | `full_path` | string | full path | file path | Search/tooltip |
| 3 | `is_header` | boolean | computed | extension check | Partition |
| 4 | `origin` | string | `"unknown"` | HANDWRITTEN/GENERATED | Partition/colour |
| 5 | `cmake_target` | string | `"unknown"` | file/header metrics | Partition/colour |
| 6 | `module` | string | `"unassigned"` | REQ-02 via target | Partition/colour |
| 7 | `team` | string | `"unknown"` | REQ-01 via target | Partition/colour |
| 8 | `sloc` | integer | `0` | header_metrics / file_metrics | Sizing |
| 9 | `source_size_bytes` | integer | `0` | header_metrics / file_metrics | Sizing |
| 10 | `preprocessed_bytes` | integer | `0` | file_metrics (source files only) | Sizing |
| 11 | `pagerank` | float | `0.0` | compute_header_pagerank | Sizing/ranking |
| 12 | `impact_score` | float | `0.0` | compute_header_impact_score | Sizing/ranking |
| 13 | `direct_fan_in` | integer | `0` | compute_include_fan_metrics | Sizing/ranking |
| 14 | `transitive_fan_in` | integer | `0` | compute_include_fan_metrics | Sizing/ranking |
| 15 | `direct_fan_out` | integer | `0` | include count | Sizing |
| 16 | `amplification_ratio` | float | `0.0` | source files only | Colour gradient |
| 17 | `git_commits` | integer | `0` | git churn data | Colour gradient |
| 18 | `git_churn` | integer | `0` | total lines changed | Colour gradient |
| 19 | `compile_time_ms` | integer | `0` | source files only | Sizing |
| 20 | `expansion_ratio` | float | `0.0` | file_metrics (source files) | Colour gradient |
| 21 | `pch_candidate_score` | float | `0.0` | REQ-03 PCH analysis | Colour gradient |

#### Edge Attributes

| # | Attribute | GEXF Type | Default | Source | Gephi Use |
|---|---|---|---|---|---|
| 1 | `weight` | integer | `1` | TU count for this inclusion | Sizing |
| 2 | `is_cross_target` | boolean | computed | different cmake_targets | Filter |
| 3 | `is_cross_module` | boolean | `false` | REQ-02 module comparison | Filter |
| 4 | `source_module` | string | `"unassigned"` | REQ-02 | Colour |
| 5 | `dest_module` | string | `"unassigned"` | REQ-02 | Colour |

---

### `cochange_graph.gexf`

**Produced by:** Notebook 06 / `export_cochange_graph`
**Graph type:** Undirected
**Variable node count (target-level, filtered by PMI threshold)**

#### Node Attributes

| # | Attribute | GEXF Type | Default | Source | Gephi Use |
|---|---|---|---|---|---|
| 1 | `label` | string | target name | cmake_target | Display label |
| 2 | `target_type` | string | from metrics | target_metrics | Partition |
| 3 | `module` | string | `"unassigned"` | REQ-02 | Partition/colour |
| 4 | `team` | string | `"unknown"` | REQ-01 | Partition/colour |
| 5 | `structural_community` | integer | `-1` | dependency graph communities | Partition/colour |
| 6 | `total_build_time_s` | float | `0.0` | target_metrics | Sizing |
| 7 | `n_commits` | integer | `0` | git churn data | Sizing |
| 8 | `total_churn` | integer | `0` | git churn data | Sizing |
| 9 | `contributor_count` | integer | `0` | from ownership | Sizing |
| 10 | `ownership_hhi` | float | `0.0` | REQ-01 ownership | Colour gradient |
| 11 | `codegen_ratio` | float | `0.0` | target_metrics | Colour gradient |
| 12 | `code_lines` | integer | `0` | code_lines_total | Sizing |

#### Edge Attributes

| # | Attribute | GEXF Type | Default | Source | Gephi Use |
|---|---|---|---|---|---|
| 1 | `cochange_count` | integer | computed | co-change matrix | Sizing |
| 2 | `pmi` | float | computed | co-change matrix | Sizing |
| 3 | `jaccard` | float | computed | co-change matrix | Tooltip |
| 4 | `is_cross_module` | boolean | `false` | REQ-02 module comparison | Filter |
| 5 | `is_cross_team` | boolean | `false` | REQ-01 team comparison | Filter |
| 6 | `has_structural_edge` | boolean | `false` | edge_list lookup | Filter |
| 7 | `source_module` | string | `"unassigned"` | REQ-02 | Colour |
| 8 | `dest_module` | string | `"unassigned"` | REQ-02 | Colour |

---

## Part 5: File Relationships

```
PRIMARY PARQUET FILES
=====================

file_metrics ──(cmake_target)──────────────> target_metrics
                                                  │
                                        ┌─────────┼─────────┐
                                  (source_target) │  (dest_target)
                                        │         │         │
                                   edge_list ─────┘─────────┘
                                        │
                              (cmake_visibility ── REQ Stage 0c)

target_metrics <──(cmake_target)──── contributor_target_commits
                                              │
                                        (contributor)
                                              │
git_commit_log ─────(source_file)────> file_metrics
       │
       └──────────(contributor)──────> contributor_target_commits

header_edges ──(source_file)─────────> file_metrics
       │
       └───────(included)────────────> header_metrics

build_schedule ──(cmake_target)──────> target_metrics
       │
       └─────────(source_file)───────> file_metrics


CONFIGURATION FILES
===================

teams.yaml ──(team.name)──────────────> modules.yaml (owning_team)
       │
       └──(member.emails)─────────────> git_commit_log (contributor)
                                        contributor_target_commits (contributor)

modules.yaml ──(directories)──────────> target_metrics (source_directory)
       │
       └───────(target_patterns)──────> target_metrics (cmake_target)


INTERMEDIATE FILES (derived)
============================

target_features ──────────(cmake_target)──> target_metrics
critical_path ────────────(cmake_target)──> target_metrics
header_impact ────────────(file)──────────> header_metrics
graph_analysis ───────────(cmake_target)──> target_metrics
communities ──────────────(cmake_target)──> target_metrics
feature_configurations ───(feature_id)────> communities (community)
target_ownership ─────────(cmake_target)──> target_metrics
module_assignments ───────(cmake_target)──> target_metrics
module_metrics ───────────(module)────────> modules.yaml (name)
pch_analysis ─────────────(cmake_target)──> target_metrics
recommendations ──────────(targets_affected)> target_metrics
trend_data ───────────────(label)─────────> snapshot metadata
comparison_*_deltas ──────(cmake_target)──> target_metrics (both snapshots)


GEPHI EXPORTS (derived)
========================

dependency_graph.gexf ────(nodes)─────────> target_metrics
                          (edges)─────────> edge_list
                          (node attrs)────> graph_analysis, communities,
                                            target_ownership, module_assignments,
                                            critical_path

module_graph.gexf ────────(nodes)─────────> modules.yaml, module_metrics
                          (edges)─────────> edge_list (aggregated)

include_graph.gexf ───────(nodes)─────────> header_metrics, file_metrics,
                                            header_impact
                          (edges)─────────> header_edges

cochange_graph.gexf ──────(nodes)─────────> target_metrics, target_ownership,
                                            communities
                          (edges)─────────> git.compute_cochange_matrix
```

---

## Appendix: Field Count Summary

| File | Field Count | Category |
|---|---|---|
| `file_metrics.parquet` | 30 | Primary |
| `target_metrics.parquet` | 57 | Primary |
| `edge_list.parquet` | 8 | Primary |
| `contributor_target_commits.parquet` | 3 | Primary |
| `git_commit_log.parquet` | 6 | Primary (Stage 0a) |
| `header_edges.parquet` | 5 | Primary (Stage 0b) |
| `header_metrics.parquet` | 5 | Primary (Stage 0b) |
| `build_schedule.parquet` | 7 | Primary (Stage 0d) |
| `metadata.yaml` | 11 | Configuration (REQ-04) |
| `teams.yaml` | ~3 per team | Configuration (REQ-01) |
| `modules.yaml` | ~6 per module | Configuration (REQ-02) |
| `target_features.parquet` | 57 + 2 | Intermediate |
| `critical_path.parquet` | 8 | Intermediate |
| `header_impact.parquet` | 11 | Intermediate |
| `graph_analysis.parquet` | 8 | Intermediate |
| `communities.parquet` | 3 | Intermediate |
| `feature_configurations.parquet` | 9 | Intermediate |
| `target_ownership.parquet` | 12 | Intermediate (REQ-01) |
| `module_assignments.parquet` | 3 | Intermediate (REQ-02) |
| `module_metrics.parquet` | 19 | Intermediate (REQ-02) |
| `pch_analysis.parquet` | 9 | Intermediate (REQ-03) |
| `recommendations.parquet` | 11 | Intermediate |
| `comparison_global_deltas.parquet` | 6 | Intermediate (REQ-04) |
| `comparison_target_deltas.parquet` | 11 | Intermediate (REQ-04) |
| `trend_data.parquet` | 12 | Intermediate (REQ-04) |
| `dependency_graph.gexf` | 29 node + 7 edge | GEXF (REQ-05) |
| `module_graph.gexf` | 13 node + 5 edge | GEXF (REQ-02/05) |
| `include_graph.gexf` | 21 node + 5 edge | GEXF (REQ-05) |
| `cochange_graph.gexf` | 12 node + 8 edge | GEXF (REQ-05) |