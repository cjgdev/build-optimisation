# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

C++ build time analysis and optimisation tool with dual objectives: improving build times AND restructuring the codebase into selectable feature groups. Instruments a CMake + Ninja build, collects metrics (compile times, GCC phase breakdowns, preprocessed sizes, git churn, object sizes, header trees), builds a dependency graph, identifies contributor groups and code ownership, discovers feature group structure, and provides analysis notebooks with prioritised recommendations.

## Commands

```zsh
# Install dependencies
uv sync --all-extras

# Run all tests (unit only)
uv run pytest -m "not integration"

# Run a single test file or test
uv run pytest tests/unit/test_graph.py
uv run pytest tests/unit/test_graph.py::test_function_name -v

# Integration tests (require CMake 4.2+, GCC, Ninja installed)
uv run pytest -m integration

# Lint
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/

# Run data collection pipeline (requires a configured config.yaml pointing at a real C++ project)
./scripts/collect_all.sh
```

## Architecture

### Library: `src/build_optimiser/`

Eight modules forming the core library:

- **config.py** — Loads `config.yaml`, resolves paths, renders `toolchain.cmake` with compiler paths, assembles cmake/ninja CLI commands. Single `Config` instance passed to all scripts.
- **cmake_file_api.py** — Creates CMake File API query files; parses codemodel-v2 reply JSON into frozen dataclasses (`Target`, `Edge`, `CodeModel`). Branches on codemodel minor version >= 9 (CMake 4.2+) for direct vs transitive edge classification.
- **graph.py** — NetworkX wrapper. Loads graph from parquet edge list or `CodeModel`. Provides topological depth, critical path, betweenness centrality, metric attachment.
- **metrics.py** — PyArrow schema constants for three output tables (`FILE_METRICS_SCHEMA`, `TARGET_METRICS_SCHEMA`, `EDGE_LIST_SCHEMA`) and aggregation helpers.
- **simulation.py** — Rebuild cost simulation (`rebuild_cost`, `expected_daily_cost`, `simulate_merge`, `simulate_split`) and incremental build modelling (`simulate_incremental_build`, `replay_git_history`, `feature_subset_build_time`, `sensitivity_analysis`). Operates on the NetworkX graph + metrics DataFrames.
- **contributors.py** — Contributor analysis: builds contributor-target matrices, clusters contributors (hierarchical/NMF), computes time-decayed code ownership scores, and bus factor per target.
- **features.py** — Feature group discovery support: computes executable-library dependency matrices, identifies core libraries, computes Jaccard similarity between executables, detects thin dependencies via header inclusion analysis.
- **partitioning.py** — Feature group partitioning: spectral co-clustering, hierarchical Leiden community detection at multiple resolutions, feature group extraction, and simulated annealing optimisation.

### Edge convention

A → B means "A depends on B" (A builds after B). `rebuild_cost()` reverses the graph to find dependants.

### Data pipeline: `scripts/`

Orchestrated by `scripts/collect_all.sh` with controlled parallelism:
1. `cmake_file_api.py` — configure + parse File API (serial, must run first)
2. `git_history.py` — git log analysis including per-contributor-per-file commit counts (parallel)
3. `instrumented_build.py` — ninja build with `-ftime-report -H` via `capture_stderr.sh` wrapper (after step 1)
4-6. `post_build_metrics.py`, `preprocessed_size.py`, `ninja_log.py` (parallel, after step 3)

Consolidation (`scripts/consolidate/`) joins raw data into parquet tables:
- `file_metrics.parquet` — one row per source file
- `target_metrics.parquet` — one row per CMake target (target_type uses lowercase snake_case: `executable`, `static_library`, etc.)
- `edge_list.parquet` — one row per dependency edge
- `contributor_target_commits.parquet` — per-contributor-per-target commit counts (from `build_contributor_metrics.py`)

### Notebooks

Nine sequenced Jupyter notebooks (`notebooks/01-09`) tell a four-part story:

1. **Prerequisite** — 01 Data Cleaning, 02 Contributor Groups & Code Ownership
2. **Part 1: Current State** — 03 Global Codebase Health
3. **Part 2: Build Performance** — 04 Build Performance Analysis
4. **Part 3: Modularity** — 05 Executable Dependency Analysis, 06 Feature Group Discovery, 07 Feature Group Optimisation, 08 Impact Simulation
5. **Part 4: Conclusion** — 09 Recommendations

Notebooks produce intermediate outputs consumed by later notebooks (e.g. `contributor_groups.parquet`, `target_ownership.parquet`, `exe_library_matrix.parquet`, `feature_group_assignments.parquet`). Results are written to `data/results/`.

## Testing notes

- Script modules with digit-leading filenames (e.g. `02_git_history.py`) are imported in tests via `importlib.import_module("scripts.collect.02_git_history")`.
- Test fixtures in `tests/data/cmake_file_api_reply/` contain real CMake 4.x File API JSON output.
- `tests/fixture/` is a mini C++ project covering all CMake target types (STATIC, SHARED, MODULE, OBJECT, INTERFACE, EXECUTABLE).

## Style

- Python 3.13+, ruff for linting (line-length 120, rules E/F/I/W)
- Frozen slotted dataclasses for parsed data structures
- Type hints throughout
