# Build Optimiser — Technical Specification

## 1. Project Brief

### 1.1 Objective

Build a data science project that analyses a large C++ codebase (hundreds of CMake targets) to optimise build times and make data-driven decisions about library organisation — specifically whether to split, combine, or restructure targets.

The project collects build, code, and source control metrics from the target codebase, stores them as structured datasets, and applies graph analysis, simulation, clustering, and partitioning techniques to produce a prioritised list of refactoring recommendations.

### 1.2 Key Constraint — Non-Invasive Profiling

The target codebase must not be modified in any way. No scripts, toolchain files, profiling tools, custom CMake modules, or flag changes may be committed to the target repository. All instrumentation — toolchain overlays, compiler flag injection, metric collection logic — lives entirely within this build-optimiser project. The collection scripts are responsible for configuring CMake, invoking the build system, and capturing all output.

### 1.3 Target Codebase Environment

| Property | Value |
|---|---|
| Compiler | GCC 12 (absolute path specified in config) |
| Build system | CMake + Ninja |
| Source tree | A git worktree (path specified in config) |
| Environment setup | Normally done via a shell script that sets `PATH`, `CC`, `CXX`, and adds external dependency directories so CMake find modules can resolve them. For this project, all those paths are captured in `config.yaml` and the toolchain file instead. |
| CMake configure flags | Mold linker flag (`-fuse-ld=mold`), `CMAKE_EXPORT_COMPILE_COMMANDS=ON`. Everything else is defaulted. |
| Ninja | Available on the system `PATH` |

---

## 2. Project Structure

```
build-optimiser/
├── README.md
├── pyproject.toml
├── config.yaml
├── toolchain.cmake
├── scripts/
│   ├── collect/
│   │   ├── 01_dependency_graph.py
│   │   ├── 02_compile_times.py
│   │   ├── 03_object_files.py
│   │   ├── 04_sloc.py
│   │   ├── 05_git_history.py
│   │   ├── 06_header_depth.py
│   │   ├── 07_preprocessed_size.py
│   │   └── 08_link_times.py
│   ├── consolidate/
│   │   ├── build_file_metrics.py
│   │   ├── build_target_metrics.py
│   │   └── build_edge_list.py
│   └── collect_all.sh
├── notebooks/
│   ├── 01_data_cleaning.ipynb
│   ├── 02_exploratory_analysis.ipynb
│   ├── 03_critical_path.ipynb
│   ├── 04_community_detection.ipynb
│   ├── 05_change_impact_simulation.ipynb
│   ├── 06_clustering.ipynb
│   ├── 07_spectral_partitioning.ipynb
│   └── 08_recommendations.ipynb
├── src/
│   └── build_optimiser/
│       ├── __init__.py
│       ├── config.py
│       ├── graph.py
│       ├── metrics.py
│       └── simulation.py
├── data/
│   ├── raw/
│   ├── builds/
│   ├── processed/
│   └── results/
└── tests/
```

### 2.1 Directory Purposes

| Directory | Purpose |
|---|---|
| `scripts/collect/` | Numbered data collection scripts. Each configures CMake (if needed), invokes the build, and writes raw output to `data/raw/`. |
| `scripts/consolidate/` | Scripts that read from `data/raw/`, join and aggregate metrics, and write Parquet files to `data/processed/`. |
| `notebooks/` | Ordered Jupyter notebooks for cleaning, exploration, and each analysis technique. |
| `src/build_optimiser/` | Shared Python library imported by both scripts and notebooks. Contains graph utilities, aggregation logic, simulation engines, and config loading. |
| `data/raw/` | Raw collector output (JSON, CSV, dot files, Ninja logs). Treated as immutable once written. |
| `data/builds/` | The single out-of-source CMake/Ninja build tree. Reconfigured between collection passes. Not committed to version control. |
| `data/processed/` | The three canonical Parquet files (file metrics, target metrics, edge list). |
| `data/results/` | Output from analysis notebooks (charts, reports, recommendation tables). |

---

## 3. Configuration

### 3.1 config.yaml

All paths and settings that vary between machines or codebases. Every script reads this file. No paths are hardcoded anywhere else.

```yaml
# Paths
source_dir: /path/to/git/worktree
build_dir: ./data/builds/main
raw_data_dir: ./data/raw
processed_data_dir: ./data/processed

# Compiler (absolute paths — replaces the environment setup script)
cc: /path/to/gcc-12
cxx: /path/to/g++-12

# External dependency directories
# These replace the PATH additions from the environment setup script.
# They are passed to CMake as CMAKE_PREFIX_PATH entries so that
# find_package / find_library / find_path can locate all dependencies.
cmake_prefix_path:
  - /path/to/boost
  - /path/to/protobuf
  - /path/to/other_dep
  # ... add all directories the environment script adds to PATH

# CMake pass-through cache variables
# These are forwarded to every CMake configure invocation unchanged.
cmake_cache_variables:
  CMAKE_EXE_LINKER_FLAGS: "-fuse-ld=mold"
  CMAKE_SHARED_LINKER_FLAGS: "-fuse-ld=mold"
  CMAKE_EXPORT_COMPILE_COMMANDS: "ON"

# Git history
git_history_months: 12

# Build parallelism
ninja_jobs: 0  # 0 means let Ninja decide (number of cores)
```

### 3.2 toolchain.cmake

A CMake toolchain file maintained within the build-optimiser project. It sets the compiler paths and base flags. It does NOT include any instrumentation flags — those are injected per collection pass via `-D CMAKE_CXX_FLAGS_EXTRA` or similar on the CMake command line.

```cmake
# toolchain.cmake — generated/maintained by build-optimiser
# Sets compiler identity only. Instrumentation flags are added per-pass.

set(CMAKE_C_COMPILER   "@CC@")    # Substituted from config.yaml
set(CMAKE_CXX_COMPILER "@CXX@")  # Substituted from config.yaml

set(CMAKE_FIND_USE_SYSTEM_ENVIRONMENT_PATH OFF)
```

The `config.py` module in `src/build_optimiser/` should load `config.yaml`, render the toolchain file with the correct paths substituted, and provide a helper function that builds the full `cmake` configure command line for a given collection pass.

### 3.3 CMake Configure Command Pattern

Every collection script that needs to configure or reconfigure the build tree uses a common pattern. The `config.py` module should provide a function that assembles this:

```bash
cmake \
  -S <source_dir> \
  -B <build_dir> \
  -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE=<path/to/toolchain.cmake> \
  -DCMAKE_PREFIX_PATH="<semicolon-separated prefix paths>" \
  -DCMAKE_EXE_LINKER_FLAGS="-fuse-ld=mold" \
  -DCMAKE_SHARED_LINKER_FLAGS="-fuse-ld=mold" \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
  <pass-specific flags>
```

Pass-specific flags are the only part that changes between collection runs. For example:
- Compile times pass: `-DCMAKE_CXX_FLAGS="-ftime-report"`
- Header depth pass: `-DCMAKE_CXX_FLAGS="-H -fsyntax-only"`
- Preprocessed size pass: `-DCMAKE_CXX_FLAGS="-E"`

---

## 4. Data Collection

### 4.1 Overview

Data collection uses a single build tree (`data/builds/main`) that is reconfigured between passes. Some passes require a full rebuild, some only inspect artefacts from a prior build, and some don't build at all. The ordering is designed to minimise redundant builds.

### 4.2 Collection Ordering and Dependencies

| Step | Script | Reconfigure? | Build? | Depends on |
|---|---|---|---|---|
| 1 | `01_dependency_graph.py` | Yes (with `--graphviz`) | No | Nothing |
| 2 | `02_compile_times.py` | Yes (with `-ftime-report`) | Full build | Nothing |
| 3 | `03_object_files.py` | No | No | Step 2 (reads build artefacts) |
| 4 | `04_sloc.py` | No | No | Step 2 (reads `compile_commands.json`) |
| 5 | `05_git_history.py` | No | No | Nothing (reads git repo) |
| 6 | `06_header_depth.py` | Yes (with `-H`) | Syntax-only build | Nothing |
| 7 | `07_preprocessed_size.py` | Yes (with `-E`) | Preprocess-only build | Nothing |
| 8 | `08_link_times.py` | Yes (normal flags) | Full rebuild | Nothing |

Steps 2–5 share the same build tree state. Steps 3 and 4 must run before the next reconfigure (step 6) because reconfiguring invalidates the artefacts they read. Steps 6, 7, and 8 each reconfigure and are independent of each other.

### 4.3 Collection Script Details

#### 01_dependency_graph.py — CMake Graphviz Dependency Graph

**Purpose:** Extract the full target dependency DAG as dot files.

**Method:**
1. Configure CMake with the `--graphviz=<output_prefix>` flag. This is passed as a CMake argument, not a CXX flag. The configure command looks like:
   ```bash
   cmake -S <source_dir> -B <build_dir> -G Ninja \
     -DCMAKE_TOOLCHAIN_FILE=<toolchain> \
     <standard flags> \
     --graphviz=<build_dir>/graph/dependencies
   ```
2. CMake generates multiple dot files: a main graph and per-target files. This step is slow for large projects.
3. Copy all generated dot files from `<build_dir>/graph/` to `data/raw/dot/`.

**Output:** `data/raw/dot/` — all `.dot` files as generated by CMake.

**Notes:**
- This only runs the configure step, not a build.
- The dot files contain target names and dependency edges with labels indicating dependency scope (PUBLIC, PRIVATE, INTERFACE) where available.
- These dot files are the foundation for the edge list and all graph-based analyses.

#### 02_compile_times.py — Per-File Compile Times

**Purpose:** Measure wall-clock compile time for every source file, and capture GCC's internal timing breakdown.

**Method:**
1. Reconfigure CMake with `-DCMAKE_CXX_FLAGS="-ftime-report"` added to the pass-specific flags.
2. Clean the build tree (`ninja -C <build_dir> clean`) to force a full rebuild.
3. Run `ninja -C <build_dir> -j <ninja_jobs>`. Ninja writes timestamps to `.ninja_log`.
4. Parse `<build_dir>/.ninja_log`. Each line records: `start_time_ms end_time_ms mtime_ms command_hash target_path`. The wall-clock compile time for each file is `end_time_ms - start_time_ms`.
5. Additionally, capture the `-ftime-report` output from stderr. Each compiled file produces a timing breakdown of GCC's internal passes. To capture this, either redirect Ninja's stderr to a file (`ninja ... 2> ftime_report.log`) or use a compiler wrapper script (stored in this project) that logs stderr per file.
6. Map each compiled `.o` file back to its source file and its owning CMake target. Use the build tree structure: object files live under `<build_dir>/CMakeFiles/<target>.dir/` and their paths mirror the source tree.

**Output:**
- `data/raw/ninja_log.tsv` — parsed Ninja log with columns: `target_path`, `source_file`, `cmake_target`, `start_ms`, `end_ms`, `wall_clock_ms`.
- `data/raw/ftime_report.json` — per-file GCC timing breakdown (optional, for deeper analysis of why files are slow).

**Notes:**
- This is the most expensive collection step (full rebuild).
- The build tree is left intact after this step so that steps 03 and 04 can inspect it.
- `-ftime-report` writes to stderr. If Ninja interleaves output from parallel jobs, the per-file breakdown may be jumbled. Consider using `-j1` for the ftime-report capture, or use a wrapper script that redirects each compilation's stderr to a separate file under `data/raw/ftime/`.

#### 03_object_files.py — Object File Count and Size Per Target

**Purpose:** Count object files and measure their on-disk size, per target.

**Method:**
1. No reconfigure. This runs against the build tree left by step 02.
2. Walk the `<build_dir>/CMakeFiles/` directory. Each target has a subdirectory `<target>.dir/` containing its compiled `.o` files.
3. For each target directory, count the `.o` files and `stat` each one to get its size in bytes.
4. Sum sizes per target.

**Output:** `data/raw/object_files.csv` — columns: `cmake_target`, `object_file_path`, `size_bytes`. (Aggregation to per-target totals happens in the consolidation phase.)

**Notes:**
- Must run before the next reconfigure (step 06), which would invalidate these artefacts.

#### 04_sloc.py — Source Lines of Code Per File

**Purpose:** Count non-blank, non-comment source lines for every source file, grouped by target.

**Method:**
1. No reconfigure. This reads `compile_commands.json` from the build tree left by step 02.
2. Parse `<build_dir>/compile_commands.json`. Each entry has a `file` field (absolute path to the source file) and a `directory` field. Group files by their owning CMake target using the same `CMakeFiles/<target>.dir/` mapping from step 03.
3. Run `cloc --by-file --json` over all source files. Alternatively, for simplicity: for each file, count lines that are non-blank and non-comment using a lightweight Python function (strip C/C++ line comments and blank lines; this doesn't need to be perfect — `cloc` is more accurate but adds a dependency).
4. Map results back to targets.

**Output:** `data/raw/sloc.csv` — columns: `source_file`, `cmake_target`, `language`, `blank_lines`, `comment_lines`, `code_lines`.

**Notes:**
- `cloc` is preferred if available (`cloc --by-file --json <file_list>` accepts a file list via stdin or `--list-file`).
- Must run before the next reconfigure.

#### 05_git_history.py — Change Frequency Per File

**Purpose:** Count how often each source file has been modified over a configurable time window.

**Method:**
1. No build or configure needed. This reads from the git repository at `source_dir`.
2. Run:
   ```bash
   git -C <source_dir> log \
     --since="<git_history_months> months ago" \
     --name-only \
     --pretty=format:"" \
     -- '*.cpp' '*.cc' '*.cxx' '*.h' '*.hpp' '*.hxx'
   ```
3. Parse the output: each non-blank line is a file that was changed in a commit. Count occurrences per file.
4. Optionally, also collect per-file churn (lines added + lines deleted) using `--numstat` instead of `--name-only`.

**Output:** `data/raw/git_history.csv` — columns: `source_file`, `commit_count`, `lines_added` (optional), `lines_deleted` (optional).

**Notes:**
- File paths from git are relative to the repo root. These need to match the absolute paths from `compile_commands.json`. The consolidation step handles this alignment.

#### 06_header_depth.py — Header Inclusion Depth Per File

**Purpose:** Measure the maximum header inclusion depth for each source file.

**Method:**
1. Reconfigure CMake with `-DCMAKE_CXX_FLAGS="-H -fsyntax-only"` as the pass-specific flag. `-fsyntax-only` skips code generation so this pass is fast. `-H` causes GCC to print the include hierarchy to stderr, with each level indented by one `.` character.
2. Run the build: `ninja -C <build_dir> -j <ninja_jobs>`.
3. Capture stderr. As with `-ftime-report`, Ninja may interleave output from parallel compilations. Two approaches:
   - Use `-j1` for clean serial output (slower but simpler).
   - Use a compiler wrapper script (stored in this project, e.g. `scripts/collect/wrappers/capture_stderr.sh`) that redirects each invocation's stderr to a separate file named after the source file. The wrapper is injected by setting `CMAKE_CXX_COMPILER_LAUNCHER` (not by modifying the toolchain file).
4. Parse the `-H` output per file. Each line looks like `... path/to/header.h` where the number of leading dots indicates the inclusion depth. The maximum dot count for a file is its maximum inclusion depth.

**Output:** `data/raw/header_depth.csv` — columns: `source_file`, `cmake_target`, `max_depth`, `unique_headers`, `total_includes`.

#### 07_preprocessed_size.py — Preprocessed Output Size Per File

**Purpose:** Measure the size of the preprocessed translation unit for each source file. This is a proxy for how much work the compiler does after macro expansion and include resolution.

**Method:**
1. Reconfigure CMake with `-DCMAKE_CXX_FLAGS="-E"`. The `-E` flag tells GCC to preprocess only and write the result to stdout (or a file).
2. The challenge: with `-E`, GCC writes preprocessed output to stdout instead of producing `.o` files. Ninja will still invoke the compiler for each source file, but the output goes to stdout and the `.o` targets won't be produced. Two approaches:
   - **Approach A (recommended):** Use a compiler wrapper script that invokes GCC with `-E`, pipes stdout to `wc -c` to count bytes, and logs the result to a per-file output file. Set this wrapper via `CMAKE_CXX_COMPILER_LAUNCHER`.
   - **Approach B:** Reconfigure with `-DCMAKE_CXX_FLAGS="-E -o /dev/null"` just to avoid errors, and instead run each compilation command manually (extracted from `compile_commands.json`) with `-E` piped to `wc -c`.
3. The wrapper or manual invocation should log: source file path, preprocessed size in bytes.

**Output:** `data/raw/preprocessed_size.csv` — columns: `source_file`, `cmake_target`, `preprocessed_bytes`.

**Notes:**
- Approach B using `compile_commands.json` entries is more robust. Extract each compile command, replace the output flag with `-E`, pipe to `wc -c`. This avoids Ninja confusion about missing outputs.
- This pass can be parallelised with Python's `subprocess` + `concurrent.futures.ThreadPoolExecutor`.

#### 08_link_times.py — Link Time Per Target

**Purpose:** Measure the wall-clock time for the link step of each target.

**Method:**
1. Reconfigure CMake with normal flags (no instrumentation). This is a clean configure to produce a standard build.
2. Clean and do a full rebuild: `ninja -C <build_dir> clean && ninja -C <build_dir> -j <ninja_jobs>`.
3. Parse `<build_dir>/.ninja_log`. Link steps are identifiable because their output paths are libraries (`.a`, `.so`) or executables (no extension or specific known names), as opposed to `.o` files which are compile steps.
4. For each link step, compute `end_time_ms - start_time_ms`.
5. Map the linked output to its CMake target name.

**Output:** `data/raw/link_times.csv` — columns: `cmake_target`, `output_path`, `link_time_ms`.

**Notes:**
- Distinguishing link steps from compile steps in `.ninja_log`: link outputs are typically in the top-level build directory or a `lib/` subdirectory, and have `.a`, `.so`, or no extension. Compile outputs are `.o` files under `CMakeFiles/`. The heuristic can be validated against the list of known targets from the dot files.

### 4.4 collect_all.sh — Orchestration Script

A shell script that runs the collection scripts in order with error handling. Features:

- Reads `config.yaml` for paths (or takes them as arguments).
- Supports `--skip` flags to skip expensive steps when iterating (e.g. `--skip compile_times`).
- Exits on first failure (with `set -e`) but logs which step failed.
- Prints elapsed time for each step.
- Example usage:
  ```bash
  ./scripts/collect_all.sh                    # Run all steps
  ./scripts/collect_all.sh --skip 02 --skip 08  # Skip compile_times and link_times
  ```

### 4.5 Compiler Wrapper Scripts

For collection steps that need to capture per-file stderr (steps 06, 07), the project includes wrapper scripts under `scripts/collect/wrappers/`. These are injected via `CMAKE_CXX_COMPILER_LAUNCHER` during the relevant configure pass — this avoids modifying the toolchain file or the target codebase.

Example wrapper (`scripts/collect/wrappers/capture_stderr.sh`):
```bash
#!/bin/bash
# Wraps a compiler invocation, capturing stderr to a per-file log.
# Usage: CMAKE_CXX_COMPILER_LAUNCHER=<path/to/capture_stderr.sh>
# The wrapper receives the compiler and all arguments.

OUTPUT_DIR="${BUILD_OPTIMISER_STDERR_DIR:-.}"
COMPILER="$1"
shift

# Derive a log filename from the source file argument
SOURCE_FILE=""
for arg in "$@"; do
    if [[ "$arg" == *.cpp || "$arg" == *.cc || "$arg" == *.cxx ]]; then
        SOURCE_FILE="$arg"
        break
    fi
done

LOG_FILE="${OUTPUT_DIR}/$(echo "$SOURCE_FILE" | tr '/' '_').stderr"
"$COMPILER" "$@" 2> "$LOG_FILE"
EXIT_CODE=$?
exit $EXIT_CODE
```

---

## 5. Data Consolidation

### 5.1 Overview

Three consolidation scripts read from `data/raw/`, join and aggregate the per-file and per-target data, and produce three Parquet files in `data/processed/`. The file-level script runs first, since the target-level script aggregates from it.

### 5.2 build_file_metrics.py — File-Level DataFrame

Joins all per-file data by source file path. File paths from different collectors may be absolute or relative; this script canonicalises them.

**Columns:**

| Column | Type | Source |
|---|---|---|
| `source_file` | str | All collectors (canonical absolute path) |
| `cmake_target` | str | Derived from `CMakeFiles/<target>.dir/` mapping |
| `compile_time_ms` | int | `ninja_log.tsv` |
| `code_lines` | int | `sloc.csv` |
| `blank_lines` | int | `sloc.csv` |
| `comment_lines` | int | `sloc.csv` |
| `header_max_depth` | int | `header_depth.csv` |
| `unique_headers` | int | `header_depth.csv` |
| `total_includes` | int | `header_depth.csv` |
| `preprocessed_bytes` | int | `preprocessed_size.csv` |
| `object_size_bytes` | int | `object_files.csv` |
| `git_commit_count` | int | `git_history.csv` |
| `git_lines_added` | int | `git_history.csv` (optional) |
| `git_lines_deleted` | int | `git_history.csv` (optional) |

**Output:** `data/processed/file_metrics.parquet`

### 5.3 build_target_metrics.py — Target-Level DataFrame

Aggregates file-level metrics to one row per CMake target. Also incorporates link times and graph-derived metrics.

**Columns:**

| Column | Type | Derivation |
|---|---|---|
| `cmake_target` | str | Target name |
| `compile_time_sum_ms` | int | Sum of file compile times |
| `compile_time_max_ms` | int | Max single-file compile time |
| `file_count` | int | Count of source files |
| `object_file_count` | int | Count of `.o` files |
| `code_lines_total` | int | Sum of `code_lines` |
| `header_depth_mean` | float | Mean of `header_max_depth` |
| `header_depth_max` | int | Max of `header_max_depth` |
| `preprocessed_bytes_total` | int | Sum of `preprocessed_bytes` |
| `object_size_total_bytes` | int | Sum of `object_size_bytes` |
| `link_time_ms` | int | From `link_times.csv` |
| `git_commit_count_total` | int | Sum of file commit counts |
| `direct_dependency_count` | int | From dependency graph (successors) |
| `transitive_dependency_count` | int | From dependency graph (`nx.descendants`) |
| `direct_dependant_count` | int | From dependency graph (predecessors) |
| `transitive_dependant_count` | int | From dependency graph (`nx.ancestors`) |
| `topological_depth` | int | Longest path from a root to this node |
| `critical_path_length_ms` | int | Longest weighted path through this node |

**Output:** `data/processed/target_metrics.parquet`

### 5.4 build_edge_list.py — Edge List DataFrame

Parses the dot files from `data/raw/dot/` into a clean edge table.

**Columns:**

| Column | Type | Source |
|---|---|---|
| `source_target` | str | The depending target |
| `dest_target` | str | The dependency |
| `scope` | str | PUBLIC / PRIVATE / INTERFACE (if extractable from dot labels) |

**Output:** `data/processed/edge_list.parquet`

### 5.5 Persistence Format

All three files are stored as Parquet using PyArrow. Parquet is chosen over CSV because it preserves column types, compresses well, and is fast to read in both Pandas and DuckDB.

---

## 6. Shared Library — `src/build_optimiser/`

Code shared between collection scripts, consolidation scripts, and notebooks.

### 6.1 config.py

- Loads `config.yaml`.
- Renders `toolchain.cmake` with substituted compiler paths.
- Provides `build_cmake_command(pass_flags: dict) -> list[str]` that assembles the full CMake configure command line for a given collection pass.
- Provides `build_ninja_command() -> list[str]`.

### 6.2 graph.py

- `load_graph(dot_dir: str) -> nx.DiGraph` — reads the main dot file and returns a NetworkX directed graph.
- `direct_dependencies(G, target) -> list[str]`
- `transitive_dependencies(G, target) -> set[str]`
- `direct_dependants(G, target) -> list[str]`
- `transitive_dependants(G, target) -> set[str]`
- `topological_depth(G, target) -> int`
- `critical_path(G, weight_attr) -> list[str]` — longest weighted path through the DAG.
- `node_centrality(G) -> dict` — betweenness centrality for all nodes.
- `attach_metrics(G, df: pd.DataFrame)` — sets target-level metrics as node attributes from the target DataFrame.

### 6.3 metrics.py

- File-to-target mapping logic (parsing `CMakeFiles/<target>.dir/` paths).
- Aggregation functions that roll up file metrics to target metrics.
- Path canonicalisation (aligning relative git paths with absolute compile_commands paths).

### 6.4 simulation.py

- `rebuild_cost(G, target, metrics_df) -> int` — total transitive rebuild cost if a target changes.
- `expected_daily_cost(G, target, metrics_df, git_df) -> float` — rebuild cost weighted by change probability.
- `simulate_merge(G, targets: list[str], metrics_df) -> dict` — simulates merging targets and returns before/after build cost metrics.
- `simulate_split(G, target: str, file_groups: list[list[str]], metrics_df) -> dict` — simulates splitting a target and returns before/after metrics.

---

## 7. Analysis Notebooks

All notebooks share a common data loading preamble: read the three Parquet files, load the dependency graph with `graph.py`, and attach metrics as node attributes.

### 7.1 Notebook 01 — Data Cleaning

**Purpose:** Validate, clean, and prepare the datasets for analysis.

**Tasks:**
- **Missing data:** Identify targets with missing compile times (header-only libraries, interface targets, imported targets). Decide whether to exclude them or fill with zero.
- **Outlier detection:** Flag files with anomalous compile times (caused by build machine load, swapping, etc.). Use IQR or Z-score methods. Visualise outliers before removing them.
- **Path alignment:** Verify that all file paths from different collectors match after canonicalisation. Report any files present in one dataset but not another.
- **Target validation:** Cross-reference the target list from the dot files with targets found in the build tree. Identify phantom targets (in the graph but not built) and unlisted targets (built but not in the graph).
- **Type casting and normalisation:** Ensure all columns have correct types. Normalise time units (everything in milliseconds).
- **Output:** Cleaned versions of all three Parquet files, overwriting the originals in `data/processed/`. Log a summary of rows removed/modified.

### 7.2 Notebook 02 — Exploratory Data Analysis

**Purpose:** Build intuition about the codebase structure before formal analysis.

**Tasks:**
- **Distribution plots:** Histograms of compile time, SLOC, header depth, preprocessed size, object size, git change count. Use log scale where distributions are heavily skewed.
- **Pareto analysis:** Which 20% of targets account for 80% of total compile time? Plot cumulative compile time vs target rank.
- **Correlation analysis:** Scatter plots and Pearson/Spearman correlations between SLOC and compile time (to find template-heavy files that are disproportionately slow), between header depth and preprocessed size, between git change frequency and dependant count.
- **Dependency structure overview:** Degree distribution (in-degree and out-degree). DAG depth distribution. Identify the widest level of the DAG (maximum parallelism potential).
- **Heatmap:** Dependency adjacency matrix (or a sampled version if hundreds of targets make it too large), ordered by topological sort.

### 7.3 Notebook 03 — Critical Path Analysis

**Purpose:** Identify the theoretical minimum build time and the targets that constrain it.

**Tasks:**
- **Compute the critical path:** The longest weighted path through the DAG, where weights are per-target compile times (use `compile_time_max_ms` for the bottleneck file in each target, or `compile_time_sum_ms / parallelism` for a more nuanced estimate). Use `nx.dag_longest_path` with weight attribute.
- **Critical path length:** This is the theoretical minimum build time with infinite parallelism.
- **Slack analysis:** For each target, compute its slack — how much its compile time could increase before it becomes part of the critical path. Targets with zero slack are critical. Formula: `slack = critical_path_length - longest_path_through(target)`.
- **Visualisation:** Render the DAG with critical path highlighted (red nodes/edges). Annotate with compile times and slack values. Use Graphviz or pyvis.
- **Bottleneck ranking:** Rank targets by their contribution to the critical path, weighted by compile time. This is the prioritised list of "if you could make one target compile faster, which should it be."

### 7.4 Notebook 04 — Community Detection

**Purpose:** Find natural clusters of tightly coupled targets that could be merged, and identify bridging targets that couple otherwise separate clusters.

**Tasks:**
- **Community detection:** Apply the Louvain algorithm (via `python-louvain` / `community` package) to the undirected version of the dependency graph. Also try Leiden (via `leidenalg`) for comparison, as it produces better-connected communities.
- **Resolution parameter tuning:** Sweep the resolution parameter and evaluate modularity at each level. Choose the resolution that produces communities of actionable size (not too large, not singletons).
- **Community characterisation:** For each detected community, report: number of targets, total compile time, total SLOC, internal edge count vs external edge count (cohesion vs coupling ratio).
- **Bridging targets:** Compute betweenness centrality. Targets with high betweenness that connect two or more communities are coupling separate domains and are candidates for splitting or interface extraction.
- **Visualisation:** Render the DAG coloured by community. Use a force-directed layout (e.g. Graphviz `neato` or `sfdp`, or pyvis) so that communities cluster visually. Also produce a community-level summary graph where each node is a community and edges represent cross-community dependencies.
- **Merge candidates:** Communities with high internal coupling and low external coupling are candidates for merging into a single library. Rank by internal/external edge ratio.

### 7.5 Notebook 05 — Change Impact Simulation

**Purpose:** Quantify the actual developer pain caused by the current library structure, and evaluate the build time impact of proposed structural changes.

**Tasks:**
- **Change probability model:** Using git history, compute per-target change probability as `target_commit_count / total_commits_in_window`. This is the empirical probability that a given target changes in any given commit.
- **Expected rebuild cost:** For each target, compute `change_probability × transitive_rebuild_cost`. The transitive rebuild cost is the sum of compile times of all transitive dependants (everything that must rebuild when this target changes). Rank targets by expected rebuild cost — this is the "pain score."
- **Merge simulation:** For proposed merges (from community detection), simulate the new graph and recompute expected rebuild costs. A merge increases the change probability of the merged target (union of both targets' change sets) but may reduce the total target count. Report the net change in total expected daily rebuild cost.
- **Split simulation:** For proposed splits (of high-centrality bridging targets), simulate partitioning the target's files into two new targets. Only dependants of the changed partition need to rebuild. Report the net change.
- **Monte Carlo simulation:** For more robust estimates, sample from the git history to simulate N random workdays. For each day, randomly select which targets change (based on empirical probabilities), compute the rebuild cost, and aggregate. Compare current structure vs proposed structures.
- **Sensitivity analysis:** How sensitive are the recommendations to the git history window? Re-run with 3, 6, and 12 month windows.

### 7.6 Notebook 06 — Clustering and Dimensionality Reduction

**Purpose:** Identify targets that are structurally similar in feature space (not just graph-connected), revealing consolidation opportunities that community detection misses.

**Tasks:**
- **Feature matrix construction:** Each target becomes a row. Features: `compile_time_sum_ms`, `code_lines_total`, `file_count`, `header_depth_max`, `preprocessed_bytes_total`, `object_size_total_bytes`, `direct_dependency_count`, `transitive_dependency_count`, `direct_dependant_count`, `git_commit_count_total`, `link_time_ms`. Normalise all features (StandardScaler).
- **Dimensionality reduction:** Apply PCA to identify the principal axes of variation. Plot explained variance ratio to choose the number of components. Then apply t-SNE or UMAP (2D) for visualisation, coloured by community (from notebook 04) to see if graph communities align with feature-space clusters.
- **Clustering:** Apply DBSCAN (density-based, doesn't require pre-specifying k) and hierarchical clustering (Ward linkage, with dendrogram). Compare cluster assignments with community detection results.
- **Interpretation:** For each cluster, examine the centroid feature values. What makes targets in this cluster similar? Are they small utility libraries? Large monolithic targets? Template-heavy but small? This informs consolidation strategy — targets with the same profile in different parts of the codebase might share infrastructure.
- **Outlier detection:** DBSCAN naturally identifies outliers (noise points). These are targets that don't fit any profile and may need individual attention.

### 7.7 Notebook 07 — Spectral Graph Partitioning

**Purpose:** For specific targets identified as split candidates (high centrality, large, coupling separate domains), find the mathematically optimal way to divide their source files into new targets.

**Tasks:**
- **Intra-target dependency graph:** For each split candidate, build a file-level dependency graph within the target. Nodes are source files, edges are `#include` relationships (extractable from the `-H` output or from a lightweight header-scan pass). Weight edges by co-change frequency from git history (files that change together should stay together).
- **Spectral partitioning:** Compute the graph Laplacian and its Fiedler vector (second-smallest eigenvector). The sign of the Fiedler vector entries gives a 2-way partition that minimises edge cut. For k-way partitions, use the first k eigenvectors and apply k-means to the spectral embedding.
- **METIS partitioning:** As an alternative/comparison, use pymetis to partition the file-level graph. METIS uses multilevel recursive bisection and is well-suited to this problem. Weight nodes by SLOC or compile time.
- **Constraint handling:** Some files cannot be separated (e.g. a `.cpp` and its corresponding `.h`). These should be contracted into a single node before partitioning.
- **Evaluation:** For each proposed partition, compute: number of cross-partition includes (these become new inter-target dependencies), compile time balance between partitions, and the estimated change in critical path length.

### 7.8 Notebook 08 — Recommendations

**Purpose:** Synthesise findings from all analyses into a prioritised, actionable refactoring plan.

**Tasks:**
- **Compile a candidate list:** Merge candidates (from community detection), split candidates (from centrality analysis and spectral partitioning), and individual target optimisation opportunities (from critical path and EDA).
- **Score each candidate:** Using the change impact simulation, compute the expected build time improvement for each proposed action. Factor in estimated implementation effort (rough heuristic: splitting is harder than merging, and effort scales with SLOC).
- **Rank by ROI:** Sort candidates by (expected build time saved per day) / (estimated implementation effort). This gives the team a clear priority order.
- **Quick wins:** Separately flag low-effort improvements: removing unused dependencies (edges in the graph with no actual `#include` backing), targets on the critical path with high preprocessed size (candidates for include-what-you-use cleanup), and targets with high header depth (precompiled header candidates).
- **Output:** A summary table written to `data/results/recommendations.csv` and a formatted report (Markdown or HTML) with visualisations.

---

## 8. Dependencies

### 8.1 pyproject.toml

```toml
[project]
name = "build-optimiser"
version = "0.1.0"
requires-python = ">=3.10"

dependencies = [
    # Core data handling
    "pandas>=2.0",
    "pyarrow>=14.0",

    # Graph analysis
    "networkx>=3.0",
    "pydot>=2.0",

    # Community detection
    "python-louvain>=0.16",  # provides 'community' module
    "leidenalg>=0.10",
    "igraph>=0.11",          # required by leidenalg

    # Clustering and dimensionality reduction
    "scikit-learn>=1.3",
    "umap-learn>=0.5",

    # Graph partitioning
    "pymetis>=2023.1",

    # Visualisation
    "matplotlib>=3.7",
    "seaborn>=0.13",
    "pyvis>=0.3",

    # Configuration
    "pyyaml>=6.0",

    # Notebooks
    "jupyterlab>=4.0",

    # Code metrics (optional, can use system cloc instead)
    "pygments>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "ruff>=0.1",
]
```

---

## 9. Implementation Order

The recommended implementation order for Claude Code:

1. **Project skeleton:** Create the directory structure, `pyproject.toml`, `config.yaml` template, empty `__init__.py`.
2. **`src/build_optimiser/config.py`:** Config loading, toolchain rendering, CMake command builder.
3. **Collection scripts 01–08:** In numbered order. Each should be independently testable.
4. **`collect_all.sh`:** Orchestration wrapper.
5. **Compiler wrapper scripts:** `scripts/collect/wrappers/capture_stderr.sh` and any variants.
6. **`src/build_optimiser/metrics.py`:** File-to-target mapping, path canonicalisation, aggregation functions.
7. **Consolidation scripts:** `build_file_metrics.py`, `build_target_metrics.py`, `build_edge_list.py`.
8. **`src/build_optimiser/graph.py`:** Graph loading and analysis utilities.
9. **`src/build_optimiser/simulation.py`:** Rebuild cost and simulation logic.
10. **Notebooks 01–08:** In numbered order, as each builds on prior results.
11. **Tests:** Unit tests for `config.py`, `metrics.py`, `graph.py`, `simulation.py`.
