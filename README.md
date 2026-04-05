# Build Optimiser

Analyse C++ codebases to optimise build times and restructure code into selectable feature groups.

Build Optimiser instruments a CMake + Ninja build pipeline, collects comprehensive metrics, builds a dependency graph, and provides analysis notebooks with prioritised recommendations. It combines build performance data with code ownership, community structure, and module analysis to give a full picture of where build time goes and how to reduce it.

## What it measures

- **Compile times** — per-file wall-clock and GCC phase breakdowns (`-ftime-report`)
- **Preprocessed sizes** — expansion ratio per translation unit
- **Header trees** — inclusion graph from `-H` output, PCH candidate identification
- **Dependency graph** — CMake target-level dependencies via the File API
- **Build schedule** — Ninja parallelism timeline from `.ninja_log`
- **Git churn** — file change frequency, co-change patterns, contributor ownership
- **Object sizes** — compiled object file sizes and codegen footprint

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- CMake 4.2+ with [File API](https://cmake.org/cmake/help/latest/manual/cmake-file-api.7.html) support
- Ninja build system
- GCC (for `-ftime-report` and `-H` instrumentation)

## Quick start

```zsh
# Clone and install
git clone <repo-url> && cd build-optimisation
uv sync --all-extras

# Configure — edit config.yaml to point at your C++ project
cp config.yaml config.yaml.local
$EDITOR config.yaml.local

# Collect build data
./scripts/collect_all.sh

# Consolidate into parquet tables
./scripts/consolidate_all.sh

# Launch notebooks
uv run jupyter lab notebooks/optimisation/
```

## Configuration

Copy `config.yaml` and fill in paths for your environment:

```yaml
source_dir: /path/to/your/cpp/project
build_dir: ./data/builds/main
raw_data_dir: ./data/raw
processed_data_dir: ./data/processed

cc: /usr/bin/gcc
cxx: /usr/bin/g++

cmake_prefix_path: []
cmake_cache_variables:
  CMAKE_MAKE_PROGRAM: "/usr/bin/ninja"
  CMAKE_EXPORT_COMPILE_COMMANDS: "ON"

git_history_months: 12
ninja_jobs: 0           # 0 = auto (number of cores)
preprocess_workers: 0   # 0 = auto (cpu_count)
```

Optional team and module configuration files go in the project root:
- `teams.yaml` — map email patterns to teams for ownership analysis
- `modules.yaml` — define logical module boundaries for self-containment metrics

## Data pipeline

Collection (`scripts/collect_all.sh`) runs in stages with controlled parallelism:

1. **CMake File API** — configure build, parse codemodel reply (serial, runs first)
2. **Git history** — extract log for churn/ownership analysis (parallel with 3)
3. **Instrumented build** — Ninja build with `-ftime-report -H` capture (parallel with 2)
4. **Post-build metrics** — object sizes, file counts (parallel, after 2+3)
5. **Preprocessed sizes** — run preprocessor on each TU (parallel, after 2+3)
6. **Ninja log** — parse `.ninja_log` for build schedule (parallel, after 2+3)

Consolidation (`scripts/consolidate_all.sh`) produces parquet tables:

| Table | Granularity |
|---|---|
| `file_metrics.parquet` | One row per source file |
| `target_metrics.parquet` | One row per CMake target |
| `edge_list.parquet` | One row per dependency edge |
| `contributor_target_commits.parquet` | Per-contributor-per-target commits |
| `build_schedule.parquet` | Per-step start/end timestamps |
| `header_edges.parquet` | Header inclusion graph |
| `header_metrics.parquet` | Per-header aggregate metrics |

## Analysis notebooks

Ten sequenced notebooks in `notebooks/optimisation/`:

| # | Notebook | Purpose |
|---|---|---|
| 01 | Data Validation | Schema checks, referential integrity, null analysis, distributions |
| 02 | Teams & Ownership | Team resolution, target ownership (HHI), bus factor, coupling |
| 03 | Global Profile | Codebase shape, target types, preprocessor health, codegen footprint |
| 04 | Build Performance | Time breakdown, critical path, parallelism simulation, what-if |
| 05 | Header & PCH Analysis | Inclusion patterns, PCH candidates, impact simulation, overlap |
| 06 | Dependency Graph | Centrality, layers, communities, transitive dependency analysis |
| 07 | Module Analysis | Module structure, inter-module deps, self-containment, alignment |
| 08 | Recommendations | Prioritised action list synthesising all prior analyses |
| 09 | Comparison | Snapshot A vs B deltas (global, target, edge, critical path) |
| 10 | Trend Analysis | Time-series across snapshots, regression detection |

Notebooks build on each other — earlier notebooks produce intermediate parquet files consumed by later ones.

## Snapshots

Build Optimiser supports named snapshots for tracking progress over time:

```
data/snapshots/
├── baseline-2025-01-15/
│   ├── processed/          # All parquet files
│   └── metadata.yaml
├── snapshot-2025-02-01/
│   ├── processed/
│   └── metadata.yaml
└── latest -> snapshot-2025-02-01/
```

Use notebook 09 (Comparison) to diff any two snapshots and notebook 10 (Trend Analysis) to visualise metrics over time with regression detection.

## Project structure

```
src/buildanalysis/       # Core library — all analysis code
scripts/
├── collect/             # Data collection scripts (01–06)
├── collect_all.sh       # Orchestrates collection
├── consolidate/         # Parquet consolidation scripts
└── consolidate_all.sh   # Orchestrates consolidation
notebooks/optimisation/  # Analysis notebooks (01–10)
tests/                   # Unit and integration tests
data/                    # Collected data, snapshots, results
```

## Development

```zsh
# Install with dev dependencies
uv sync --all-extras

# Run unit tests
uv run pytest -m "not integration"

# Run integration tests (requires CMake, GCC, Ninja)
uv run pytest -m integration

# Lint and format check
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/
```
