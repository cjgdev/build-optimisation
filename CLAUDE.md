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
uv run pytest tests/buildanalysis/test_snapshots.py
uv run pytest tests/buildanalysis/test_snapshots.py::TestSnapshotManager::test_list_snapshots -v

# Integration tests (require CMake 4.2+, GCC, Ninja installed)
uv run pytest -m integration

# Lint
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/

# Run data collection pipeline (requires a configured config.yaml pointing at a real C++ project)
./scripts/collect_all.sh
```

## Architecture

### Single library: `src/buildanalysis/`

All analysis code lives in the `buildanalysis` package. The former `build_optimiser` package has been consolidated into this single package.

#### Core modules (from original build_optimiser)

- **config.py** — Loads `config.yaml`, resolves paths, renders `toolchain.cmake`, assembles cmake/ninja CLI commands.
- **cmake_file_api.py** — CMake File API parser: codemodel-v2 reply JSON → frozen dataclasses (`Target`, `Edge`, `CodeModel`).
- **graph.py** — Consolidated graph module: graph construction (`build_dependency_graph`, `build_include_graph`), node-level queries (direct/transitive deps/dependants, topological depth), centrality, layers, violations, graph summary. Accepts both `BuildGraph` and raw `nx.DiGraph`.
- **metrics.py** — PyArrow schema constants and aggregation helpers for parquet tables.
- **simulation.py** — Rebuild cost simulation, merge/split what-if, incremental build modelling.
- **contributors.py** — Contributor-target matrices, hierarchical/NMF clustering, ownership scores, bus factor.
- **features.py** — Feature group discovery: exe-library matrices, core library identification, Jaccard similarity.
- **partitioning.py** — Spectral co-clustering, Leiden communities, simulated annealing partitioning.

#### Analysis framework modules

- **types.py** — Core types: `BuildGraph`, `AnalysisScope`, `TargetType`, `FileOrigin`.
- **loading.py** — `BuildDataset` lazy-loader with Pandera validation, snapshot-aware class methods (`from_snapshot`, `from_latest`, `from_baseline`).
- **build.py** — Critical path computation, build simulation, what-if analysis.
- **git.py** — File churn, co-change analysis, ownership concentration.
- **modularity.py** — Community detection (Louvain, spectral, hierarchical), clustering metrics.
- **recommend.py** — Recommendation generation from analysis results.

#### REQ modules (new functionality)

- **teams.py** — (REQ-01) Team configuration from YAML, email alias resolution, target/file ownership, team coupling.
- **modules.py** — (REQ-02) Module configuration from YAML, pattern-based target assignment, module dependency graph, self-containment metrics, community alignment comparison.
- **headers.py** — (REQ-03) Header impact analysis plus PCH candidate identification, impact simulation, batch analysis, cross-target overlap.
- **snapshots.py** — (REQ-04) `SnapshotMetadata` and `SnapshotManager` for named snapshot directories with metadata.yaml.
- **comparison.py** — (REQ-04) Snapshot comparison (global deltas, target deltas, edge deltas, critical path) and trend analysis with regression detection.
- **export.py** — (REQ-05) Enhanced GEXF exports for Gephi: dependency graph, module graph, include graph, co-change graph with full attribute sets.

### Edge convention

A → B means "A depends on B" (A builds after B). `rebuild_cost()` reverses the graph to find dependants.

### Data layout

```
modules.yaml                             # Module boundary config
teams.yaml                               # Team ownership config
data/
├── raw/                             # Raw collection outputs (JSON, CSV)
│   ├── cmake_file_api/              # targets.json, files.json, dependencies.json, etc.
│   └── stderr_logs/                 # Per-file compiler stderr captures
├── processed/                       # Consolidated parquet tables (current run)
├── intermediate/                    # Analysis outputs from notebooks
├── results/                         # Final recommendations and summaries
├── builds/                          # Build tree artifacts
└── snapshots/
    ├── baseline-YYYY-MM-DD/
    │   ├── processed/               # All parquet files for this snapshot
    │   └── metadata.yaml
    ├── snapshot-YYYY-MM-DD/
    │   ├── processed/
    │   └── metadata.yaml
    └── latest -> snapshot-...       # Symlink to most recent
```

### Data pipeline: `scripts/`

Collection is orchestrated by `scripts/collect_all.sh` with controlled parallelism:
1. `01_cmake_file_api.py` — configure + parse File API (serial, must run first)
2. `02_git_history.py` — git log analysis (parallel with step 3)
3. `03_instrumented_build.py` — ninja build with `-ftime-report -H` via `scripts/collect/wrappers/capture_stderr.sh` (parallel with step 2)
4-6. `04_post_build_metrics.py`, `05_preprocessed_size.py`, `06_ninja_log.py` (parallel, after steps 2+3)

Consolidation is orchestrated by `scripts/consolidate_all.sh` in tiered dependency order:
- **Tier 1** (parallel): `build_schedule.py`, `build_edge_list.py`, `build_file_metrics.py`, `build_contributor_metrics.py`
- **Tier 2** (serial, needs file_metrics): `build_target_metrics.py`
- **Tier 3** (serial, needs file_metrics + target_metrics): `build_header_edges.py`

Output parquet tables:
- `file_metrics.parquet` — one row per source file
- `target_metrics.parquet` — one row per CMake target (target_type uses lowercase snake_case: `executable`, `static_library`, etc.)
- `edge_list.parquet` — one row per dependency edge
- `contributor_target_commits.parquet` — per-contributor-per-target commit counts
- `build_schedule.parquet` — per-step start/end timestamps for parallelism analysis
- `header_edges.parquet` + `header_metrics.parquet` — header inclusion graph and per-header metrics

### Notebooks: `notebooks/optimisation/`

Ten sequenced notebooks covering the full analysis:

1. **01_data_validation** — Schema validation, referential integrity, null analysis, distribution checks
2. **02_teams_ownership** — Team resolution, target ownership (HHI), bus factor, team coupling
3. **03_global_profile** — Codebase shape, target type distribution, preprocessor health, codegen footprint
4. **04_build_performance** — Build time breakdown, critical path, parallelism simulation, what-if analysis
5. **05_header_pch_analysis** — Header inclusion patterns, PCH candidates, impact simulation, cross-target overlap
6. **06_dependency_graph** — Graph structure, centrality, layers, communities, transitive dependencies
7. **07_module_analysis** — Module structure, inter-module deps, self-containment, community alignment
8. **08_recommendations** — Prioritised action list synthesising all prior analyses, Gephi exports
9. **09_comparison** — Snapshot A vs B comparison (global, target, edge, critical path deltas)
10. **10_trend_analysis** — Time-series metrics across all snapshots, regression detection

Notebooks produce intermediate outputs consumed by later notebooks (e.g. `target_ownership.parquet`, `pch_candidates.parquet`, `centrality.parquet`, `module_metrics.parquet`).

## Testing notes

- Tests are organised by package: `tests/buildanalysis/` (20 files, ~378 tests), `tests/collect/` (5 files, ~41 tests), `tests/consolidate/` (1 file, ~32 tests).
- Script modules with digit-leading filenames (e.g. `02_git_history.py`) are imported in tests via `importlib.import_module("scripts.collect.02_git_history")`.
- Test fixtures in `tests/data/cmake_file_api_reply/` contain real CMake 4.x File API JSON output.
- `tests/fixture/` is a mini C++ project covering all CMake target types (STATIC, SHARED, MODULE, OBJECT, INTERFACE, EXECUTABLE).
- Shared fixtures are in `tests/conftest.py` (graph topologies, synthetic git/include data) and `tests/buildanalysis/conftest.py` (mock snapshot directories).

## Code change requirements

All code changes must satisfy the following before being considered complete:

1. **Linting** — Both Pylance and Ruff must run cleanly with zero warnings or errors. Run `uv run ruff check src/ tests/ scripts/` and `uv run ruff format --check src/ tests/ scripts/` to verify. Pylance is configured via `pyrightconfig.json` — ensure no type errors are introduced.
2. **Test coverage** — Every code change must include or update tests. New functions need new tests; bug fixes need regression tests; refactors must not reduce coverage. Run `uv run pytest -m "not integration"` to verify.
3. **Notebook consistency** — Notebooks are code, not documentation. Any change to data collection scripts (`scripts/collect/`, `scripts/consolidate/`) or `buildanalysis` modules that alters schemas, function signatures, return types, or data semantics **must** also update the notebooks in `notebooks/optimisation/` that consume them. Verify by reviewing notebook imports and cell references against changed APIs.

## Style

- Python 3.13+, ruff for linting (line-length 120, rules E/F/I/W)
- Frozen slotted dataclasses for parsed data structures
- Type hints throughout
