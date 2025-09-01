# Build Optimiser — Technical Specification v2

## 1. Project Brief

### 1.1 Objective

Build a data science project that analyses a large C++ codebase (3000+ CMake targets, 8000+ source files) to optimise build times — both incremental builds for development and full rebuilds for CI — and make data-driven decisions about library organisation. Specifically: whether to split, combine, or restructure targets to minimise build cost.

The project collects build, code, and source control metrics from the target codebase, stores them as structured datasets, and applies graph analysis, simulation, clustering, and partitioning techniques to produce a prioritised list of refactoring recommendations.

### 1.2 Key Constraint — Non-Invasive Profiling

The target codebase must not be modified in any way. No scripts, toolchain files, profiling tools, custom CMake modules, or flag changes may be committed to the target repository. All instrumentation — toolchain overlays, compiler flag injection, metric collection logic — lives entirely within this build-optimiser project. The collection scripts are responsible for configuring CMake, invoking the build system, and capturing all output.

### 1.3 Target Codebase Environment

| Property | Value |
|---|---|
| Compiler | GCC 12 (absolute path specified in config) |
| Build system | CMake 4.2+ / Ninja |
| Source tree | A git worktree (path specified in config) |
| Environment setup | All paths captured in `config.yaml` and the toolchain file |
| CMake configure flags | Mold linker flag (`-fuse-ld=mold`), `CMAKE_EXPORT_COMPILE_COMMANDS=ON` |
| Ninja | Available on the system `PATH` |

### 1.4 What Changed from v1

The original specification (v1) used 8 collection scripts requiring multiple configure/build passes, with CMake's `--graphviz` flag as the foundation for dependency extraction. Real-world testing revealed three critical problems:

1. **Graphviz generation is prohibitively slow.** On the target codebase (3000+ targets), `cmake --graphviz` takes hours to complete — far longer than a full build.
2. **Multiple configure/build passes are wasteful.** Each reconfigure + rebuild cycle takes upwards of 2 hours. The v1 spec required at least 3 full build passes (compile times, header depth via syntax-only build, link times) plus separate configures for graphviz and preprocessed size.
3. **The CMake File API provides strictly superior data.** The codemodel-v2 reply (generated at configure time in seconds) provides targets, dependencies, source files per target, compile flags, include paths, defines, generated-file markers, and link command fragments — all structured as JSON with backtraces to the originating CMakeLists.txt commands.

This v2 specification replaces graphviz with the CMake File API as the foundational data source, reduces the collection process from 8 steps to 6, requires only **one full build pass**, and properly integrates codegen tracking throughout the metrics pipeline.

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
│   │   ├── 01_cmake_file_api.py
│   │   ├── 02_git_history.py
│   │   ├── 03_instrumented_build.py
│   │   ├── 04_post_build_metrics.py
│   │   ├── 05_preprocessed_size.py
│   │   ├── 06_ninja_log.py
│   │   └── wrappers/
│   │       └── capture_stderr.sh
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
│   ├── 08_codegen_analysis.ipynb
│   └── 09_recommendations.ipynb
├── src/
│   └── build_optimiser/
│       ├── __init__.py
│       ├── config.py
│       ├── cmake_file_api.py
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
| `scripts/collect/` | Numbered data collection scripts. Each writes raw output to `data/raw/`. Only step 03 performs a full build. |
| `scripts/consolidate/` | Scripts that read from `data/raw/`, join and aggregate metrics, and write Parquet files to `data/processed/`. |
| `notebooks/` | Ordered Jupyter notebooks for cleaning, exploration, and each analysis technique. Notebook 08 is new: dedicated codegen analysis. |
| `src/build_optimiser/` | Shared Python library. Includes a new `cmake_file_api.py` module for parsing the File API reply. |
| `data/raw/` | Raw collector output (JSON, CSV, Ninja logs). Treated as immutable once written. |
| `data/builds/` | The single out-of-source CMake/Ninja build tree. Configured once and built once. Not committed to version control. |
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
cmake_prefix_path:
  - /path/to/boost
  - /path/to/protobuf
  - /path/to/other_dep

# CMake pass-through cache variables
cmake_cache_variables:
  CMAKE_EXE_LINKER_FLAGS: "-fuse-ld=mold"
  CMAKE_SHARED_LINKER_FLAGS: "-fuse-ld=mold"
  CMAKE_EXPORT_COMPILE_COMMANDS: "ON"

# CMake File API client name
cmake_file_api_client: "build-optimiser"

# Git history
git_history_months: 12

# Build parallelism
ninja_jobs: 0  # 0 means let Ninja decide (number of cores)

# Preprocessed size parallelism
preprocess_workers: 0  # 0 means use cpu_count()
```

### 3.2 toolchain.cmake

A CMake toolchain file maintained within the build-optimiser project. It sets the compiler paths and base flags. Instrumentation flags are injected per collection pass via the CMake command line.

```cmake
# toolchain.cmake — generated/maintained by build-optimiser
set(CMAKE_C_COMPILER   "@CC@")    # Substituted from config.yaml
set(CMAKE_CXX_COMPILER "@CXX@")  # Substituted from config.yaml
set(CMAKE_FIND_USE_SYSTEM_ENVIRONMENT_PATH OFF)
```

### 3.3 CMake Configure Command Pattern

The `config.py` module assembles the configure command. Unlike v1, only **one configure invocation** is needed for the entire data collection pipeline:

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
  -DCMAKE_CXX_FLAGS="-ftime-report -H" \
  -DCMAKE_CXX_COMPILER_LAUNCHER=<path/to/capture_stderr.sh>
```

The single configure pass includes `-ftime-report` (GCC internal timing breakdown) and `-H` (header inclusion hierarchy) combined into one flag set. The `capture_stderr.sh` wrapper is injected via `CMAKE_CXX_COMPILER_LAUNCHER` to capture both outputs per file. This eliminates two separate configure/build passes from v1.

---

## 4. Data Collection

### 4.1 Overview

Data collection uses 6 steps with a single build tree (`data/builds/main`), configured once and built once. The CMake File API database, generated at configure time, serves as the authoritative reference that drives all subsequent steps.

### 4.2 Collection Ordering and Dependencies

| Step | Script | Requires Configure? | Requires Build? | Depends on |
|---|---|---|---|---|
| 1 | `01_cmake_file_api.py` | Yes (also creates File API query) | No | Nothing |
| 2 | `02_git_history.py` | No | No | Step 1 (uses file list for scope) |
| 3 | `03_instrumented_build.py` | No (uses configure from step 1) | **Full build** | Step 1 (configure must exist) |
| 4 | `04_post_build_metrics.py` | No | No | Step 3 (reads build artefacts) |
| 5 | `05_preprocessed_size.py` | No | No | Step 3 (needs codegen files to exist) |
| 6 | `06_ninja_log.py` | No | No | Step 3 (reads `.ninja_log`) |

**Key efficiency gains over v1:**
- Steps 1+3 replace v1 steps 01 (graphviz), 02 (compile times), 06 (header depth), and 08 (link times) — all in a single configure + single build.
- Step 2 (git history) runs in parallel with step 3 since it only needs the source tree and the file list from step 1.
- Steps 4, 5, and 6 run after the build and can execute in parallel with each other.

### 4.3 Collection Script Details

#### Step 1: 01_cmake_file_api.py — CMake File API Database

**Purpose:** Configure the build tree and extract the complete project model — targets, dependencies, source files, compile flags, include paths, defines, generated file markers, link commands, and target types — from the CMake File API codemodel-v2 reply.

**Method:**

1. Create the File API query directory and client query files before running cmake:
   ```
   <build_dir>/.cmake/api/v1/query/client-build-optimiser/codemodel-v2
   <build_dir>/.cmake/api/v1/query/client-build-optimiser/toolchains-v1
   ```
   Both files are created empty (shared stateless query style).

2. Run the cmake configure command (see §3.3). This is the **only configure invocation** in the entire pipeline. The configure includes instrumentation flags (`-ftime-report`, `-H`) and the compiler launcher wrapper, so the build tree is ready for the instrumented build in step 3.

3. After cmake completes, parse the File API reply:
   - Glob `<build_dir>/.cmake/api/v1/reply/index-*.json`, select the lexicographically last file.
   - Load the index, find the codemodel-v2 entry in `objects`.
   - Load the codemodel JSON via its `jsonFile` path.
   - Select the first configuration from `configurations` (single-config generator).
   - For each target in `configurations[0].targets`, load its target object via `jsonFile`.

4. For each target object, extract and store:
   - **Target identity:** `name`, `id`, `type` (EXECUTABLE, STATIC_LIBRARY, SHARED_LIBRARY, MODULE_LIBRARY, OBJECT_LIBRARY, INTERFACE_LIBRARY, UTILITY).
   - **Target paths:** `nameOnDisk`, `artifacts[].path`, `paths.source`, `paths.build`.
   - **Source files:** From `sources[]`, extract `path` (canonicalised to absolute), `compileGroupIndex`, `isGenerated` (boolean — critical for codegen tracking).
   - **Compile groups:** From `compileGroups[]`, extract `language`, `languageStandard`, `compileCommandFragments[]` (concatenated), `includes[]` (with `isSystem` flag), `defines[]`.
   - **Dependencies:** From `dependencies[]`, extract `id` and optional `backtrace`. On CMake 4.2+, also extract `linkLibraries[]` (direct link deps), `orderDependencies[]` (direct order deps), `compileDependencies[]`, and `objectDependencies[]`. Compute transitive-only dependencies as: items in `dependencies` not present in `linkLibraries ∪ orderDependencies ∪ objectDependencies`.
   - **Link information:** From `link.commandFragments[]`, extract library paths and linker flags.
   - **Backtrace graph:** Store the full `backtraceGraph` for later provenance queries.
   - **Generator-provided flag:** Filter out targets with `isGeneratorProvided: true` (ALL_BUILD, INSTALL, ZERO_CHECK, etc.).

5. Build a **target-to-files mapping** and its inverse (**file-to-target mapping**). This is the master index used by all subsequent collection steps to associate per-file metrics with targets.

6. Build the **codegen inventory**: all source files where `isGenerated == true`, grouped by target. Record which targets contain generated files and which targets are pure codegen targets (all sources generated).

7. Build the **dependency graph** as an adjacency list keyed by target name. For each target, store:
   - `direct_dependencies`: from `linkLibraries[]` (CMake 4.2+ codemodel 2.9)
   - `transitive_dependencies`: items in `dependencies[]` not in direct sets
   - `all_dependencies`: the full `dependencies[]` list
   - `dependency_scope`: for each direct dependency in `linkLibraries[]`, whether it has `fromDependency` (injected by transitive interface) or not (genuine direct link).

**Output:** `data/raw/cmake_file_api/` containing:
- `targets.json` — array of target objects with all extracted fields.
- `files.json` — array of all source files with their target association, compile group, generated flag, and canonical path.
- `dependencies.json` — edge list with source target, destination target, direct/transitive classification, and scope.
- `compile_commands_enriched.json` — per-file compile commands reconstructed from compile groups (compiler path from toolchains + fragments + includes + defines + source path). This supplements `compile_commands.json` with target association and structured fields.
- `codegen_inventory.json` — list of generated files with their owning target and any available metadata.

**Notes:**
- The File API reply is generated at configure time and takes seconds even for 3000+ target projects, replacing the hours-long graphviz generation.
- The `isGenerated` flag from the File API is the authoritative marker for codegen files. No heuristic detection is needed.
- All file paths are canonicalised to absolute paths using `os.path.realpath()` at extraction time. This canonical path becomes the universal join key across all collection steps.
- The codemodel-v2 does not expose `add_custom_command()` details — it marks files as generated but does not record what command produces them. The ninja build file or `ninja -t commands` can be used post-build to recover this information if needed for deeper codegen analysis.

#### Step 2: 02_git_history.py — File Change History

**Purpose:** Collect the complete git change history for every known source file, preserving all commit-level metadata for later statistical analysis.

**Method:**

1. Load the file list from `data/raw/cmake_file_api/files.json` to scope the collection to files that actually participate in the build. This avoids collecting history for dead or removed files.

2. Run git log with full metadata per commit:
   ```bash
   git -C <source_dir> log \
     --since="<git_history_months> months ago" \
     --numstat \
     --pretty=format:"COMMIT:%H|%aI|%an|%s" \
     -- '*.cpp' '*.cc' '*.cxx' '*.h' '*.hpp' '*.hxx'
   ```

3. Parse the output to produce a **per-file change log** with all commit metadata preserved:
   - `commit_hash`: full SHA for traceability
   - `commit_date`: ISO 8601 timestamp
   - `author`: committer name
   - `message`: first line of commit message (for categorising change types later)
   - `lines_added`: from `--numstat`
   - `lines_deleted`: from `--numstat`
   - `source_file`: canonical path (aligned with File API paths)

4. Also compute summary statistics per file:
   - `commit_count`: total commits touching this file
   - `total_lines_added`: sum of all additions
   - `total_lines_deleted`: sum of all deletions
   - `total_churn`: `total_lines_added + total_lines_deleted`
   - `distinct_authors`: count of unique committers
   - `first_change_date`: earliest commit in window
   - `last_change_date`: most recent commit in window

**Output:**
- `data/raw/git_history_detail.csv` — one row per (file, commit) pair with all metadata. This is the raw change log.
- `data/raw/git_history_summary.csv` — one row per file with aggregated statistics.

**Notes:**
- File paths from git are relative to the repo root. The script resolves them to absolute paths using `source_dir` and `os.path.realpath()` to align with the File API canonical paths.
- Generated files (identified from `codegen_inventory.json`) will have no git history since they don't exist in the repository. This is expected and useful — it confirms which files are generated.
- This step has no dependency on the build and can run **in parallel** with step 3.

#### Step 3: 03_instrumented_build.py — Single Instrumented Build

**Purpose:** Execute one full build with all instrumentation flags active, capturing compile timing data, header inclusion trees, and producing all build artefacts (object files, archives, binaries, generated source files) needed by subsequent steps.

**Method:**

1. The build tree was configured in step 1 with:
   - `-DCMAKE_CXX_FLAGS="-ftime-report -H"` — GCC timing breakdown and header hierarchy, both written to stderr.
   - `-DCMAKE_CXX_COMPILER_LAUNCHER=<path/to/capture_stderr.sh>` — wrapper that captures each compilation's stderr to a separate file.

2. Set the environment variable for the wrapper:
   ```bash
   export BUILD_OPTIMISER_STDERR_DIR=<raw_data_dir>/stderr_logs
   mkdir -p $BUILD_OPTIMISER_STDERR_DIR
   ```

3. Clean and build:
   ```bash
   ninja -C <build_dir> clean
   ninja -C <build_dir> -j <ninja_jobs>
   ```

4. After the build completes, the following artefacts are available:
   - **stderr logs** in `data/raw/stderr_logs/` — one file per compiled source, containing both `-ftime-report` output and `-H` output.
   - **`.ninja_log`** in `<build_dir>/.ninja_log` — timing data for every build step.
   - **Object files** under `<build_dir>/` — `.o` files for every compiled source.
   - **Archives and binaries** — `.a`, `.so`, executables produced by the linker.
   - **Generated source files** — codegen outputs now exist on disk.
   - **`compile_commands.json`** — the compilation database (also generated at configure time, but confirmed present after build).

5. Parse each stderr log file to extract:
   - **`-ftime-report` data:** GCC internal pass timings (parsing, template instantiation, code generation, optimisation). Store as structured JSON per file.
   - **`-H` data:** Header inclusion tree. Each line is `[dots] path/to/header.h` where dot count = depth. Store the full tree (not just max depth) per file, preserving the inclusion order and hierarchy.

6. For the `-H` output, compute per file:
   - `max_include_depth`: maximum number of dots (deepest nesting level)
   - `unique_headers`: count of distinct header paths
   - `total_includes`: total number of inclusion lines (includes duplicates from different paths)
   - `header_tree`: the full ordered list of (depth, header_path) tuples — preserved for later include graph analysis

**Output:**
- `data/raw/stderr_logs/` — raw per-file stderr captures.
- `data/raw/ftime_report.json` — parsed GCC timing breakdown per file.
- `data/raw/header_data.json` — parsed header inclusion data per file, including the full inclusion tree and computed summary metrics.

**Notes:**
- Combining `-ftime-report` and `-H` into a single build pass is the key efficiency gain over v1. Both write to stderr and the wrapper captures everything per file, so there is no interleaving problem.
- The wrapper script must extract the source file path from the compiler arguments to name the log file. The same wrapper from v1 is used (see §4.5).
- This is the only build step. All data that requires built artefacts must be collected from this single build.
- The build produces codegen artefacts. Steps 4 and 5 depend on these existing.

#### Step 4: 04_post_build_metrics.py — Object File Sizes and SLOC

**Purpose:** Collect object file sizes and source lines of code for every file, now that all artefacts (including generated source files) exist.

**Method:**

1. **Object file sizes:** Walk the build tree to find all `.o` files. Map each `.o` back to its source file and owning target using the File API database (`files.json` provides the target→file mapping; the `.o` path structure under `CMakeFiles/<target>.dir/` confirms the mapping).
   - Record: `source_file`, `cmake_target`, `object_file_path`, `object_size_bytes`.

2. **SLOC:** Use `cloc --by-file --json` (preferred) or a lightweight Python line counter over all source files from `files.json`. This includes both regular and generated source files.
   - Record: `source_file`, `cmake_target`, `language`, `blank_lines`, `comment_lines`, `code_lines`, `is_generated`.

3. For generated files specifically, also record the file size in bytes of the generated source itself (before compilation). This is a proxy for codegen output volume and useful for analysing codegen impact.

**Output:**
- `data/raw/object_files.csv` — columns: `source_file`, `cmake_target`, `object_file_path`, `object_size_bytes`.
- `data/raw/sloc.csv` — columns: `source_file`, `cmake_target`, `language`, `blank_lines`, `comment_lines`, `code_lines`, `is_generated`, `source_size_bytes`.

**Notes:**
- Must run after the build (step 3) because generated source files and object files must exist on disk.
- The `is_generated` flag is carried from the File API data, not inferred.

#### Step 5: 05_preprocessed_size.py — Preprocessed Translation Unit Size

**Purpose:** Measure the preprocessed output size for each source file. This is a proxy for template expansion cost and include bloat. Run after the build so that generated source files and generated headers exist.

**Method:**

1. Load `compile_commands.json` from the build tree (or use the enriched version from `compile_commands_enriched.json`).

2. For each compilation entry, extract the compile command and modify it:
   - Replace the output file flag (`-o <file>.o`) with `-E -o /dev/null` (preprocess only, discard output).
   - Remove flags that conflict with preprocessing: `-ftime-report`, `-H`, any launcher prefix.
   - Pipe the actual output through `wc -c` to count preprocessed bytes, or write to a temp file and stat it.

3. Execute all commands in parallel using `concurrent.futures.ProcessPoolExecutor` with `preprocess_workers` from config. Processing order doesn't matter since all codegen files already exist from step 3.

4. Record: `source_file`, `cmake_target`, `preprocessed_bytes`, `is_generated`.

**Output:** `data/raw/preprocessed_size.csv` — columns: `source_file`, `cmake_target`, `preprocessed_bytes`, `is_generated`.

**Notes:**
- This step runs the compiler as a subprocess for each file. It is I/O-bound and benefits from high parallelism.
- The compile commands from `compile_commands.json` contain the exact flags used during the real build, ensuring the preprocessed output matches what the compiler actually processed.
- Generated files are preprocessed with the same flags as regular files, giving comparable metrics.

#### Step 6: 06_ninja_log.py — Build Step Timing from Ninja Log

**Purpose:** Extract wall-clock timing data for every build step — compilations, codegen commands, archiver invocations, and linker invocations — from Ninja's build log. This is the authoritative source for build step durations.

**Method:**

1. Run `ninja -t recompact` in the build directory to compact the log. The `.ninja_log` is append-only; recompact removes all redundant entries, keeping only the latest for each output file. **This step is critical** — without it, the log may contain stale entries from interrupted or partial builds.

2. Parse `<build_dir>/.ninja_log`. The format is v5: five tab-separated fields per line after the `# ninja log v5` header:
   - `start_ms`: milliseconds since ninja process start when the command began.
   - `end_ms`: milliseconds since ninja process start when the command finished.
   - `restat_mtime`: output file mtime (can be 0 for restat rules).
   - `output`: canonicalised output file path (relative to build dir).
   - `command_hash`: MurmurHash64A hex string.

3. Classify each log entry by its output path:
   - **Compile step:** output is a `.o` file (typically under `CMakeFiles/<target>.dir/`). Map to source file and target using the File API database.
   - **Archive step:** output is a `.a` file. Map to the target that produces this archive.
   - **Link step:** output is an executable or `.so` file. Map to the target.
   - **Codegen step:** output matches a generated source file from `codegen_inventory.json`, or is a utility target's output. These are `CUSTOM_COMMAND` build edges.
   - **Other:** any unclassified step (e.g., cmake utility commands, phony targets). Logged but not critical.

4. For each log entry, compute:
   - `duration_ms`: `end_ms - start_ms`
   - `wall_clock_start_ms`: `start_ms` (for parallelism analysis)
   - `wall_clock_end_ms`: `end_ms` (for parallelism analysis)

5. To map output paths to targets, use the File API database:
   - For `.o` files: the path structure `CMakeFiles/<target>.dir/...` encodes the target name. Cross-reference with `files.json`.
   - For archives/binaries: cross-reference with `targets.json` where `artifacts[].path` or `nameOnDisk` matches the output.
   - For codegen outputs: cross-reference with `codegen_inventory.json`.

**Output:** `data/raw/ninja_log.csv` — columns: `output_path`, `source_file` (if applicable), `cmake_target`, `step_type` (compile/archive/link/codegen/other), `start_ms`, `end_ms`, `duration_ms`, `command_hash`.

**Notes:**
- The `start_ms` and `end_ms` fields are relative to the ninja process start, not absolute wall-clock time. However, they are consistent within a single build invocation, so they can be used directly for parallelism analysis (overlapping intervals reveal concurrent build steps).
- Codegen steps in the ninja log are particularly valuable — they reveal how long code generation takes and where it sits in the build timeline. Combined with dependency information, this enables analysis of whether codegen is on the critical path.
- For multi-output build edges (e.g., a codegen step that produces multiple files), Ninja writes one log line per output with the same `start_ms`, `end_ms`, and `command_hash`. Group by `command_hash` and overlapping times to identify these.

### 4.4 collect_all.sh — Orchestration Script

A shell script that runs the collection scripts in order with error handling.

```bash
#!/bin/bash
set -euo pipefail

# Step 1: CMake File API (configure + extract)
python scripts/collect/01_cmake_file_api.py

# Step 2 and 3 can run in parallel (git history doesn't need the build)
python scripts/collect/02_git_history.py &
GIT_PID=$!

# Step 3: Instrumented build
python scripts/collect/03_instrumented_build.py
wait $GIT_PID  # Ensure git history completes

# Steps 4, 5, 6 can run in parallel (all read from completed build)
python scripts/collect/04_post_build_metrics.py &
python scripts/collect/05_preprocessed_size.py &
python scripts/collect/06_ninja_log.py &
wait

echo "Collection complete."
```

Features:
- Supports `--skip` flags to skip expensive steps when iterating.
- Exits on first failure (with `set -e`) but logs which step failed.
- Prints elapsed time for each step.
- Steps 2+3 and 4+5+6 exploit natural parallelism.

### 4.5 Compiler Wrapper Script

The same wrapper from v1, used to capture per-file stderr (containing both `-ftime-report` and `-H` output). Injected via `CMAKE_CXX_COMPILER_LAUNCHER`.

```bash
#!/bin/bash
# scripts/collect/wrappers/capture_stderr.sh
# Wraps a compiler invocation, capturing stderr to a per-file log.

OUTPUT_DIR="${BUILD_OPTIMISER_STDERR_DIR:-.}"
COMPILER="$1"
shift

# Derive a log filename from the source file argument
SOURCE_FILE=""
for arg in "$@"; do
    if [[ "$arg" == *.cpp || "$arg" == *.cc || "$arg" == *.cxx || "$arg" == *.c ]]; then
        SOURCE_FILE="$arg"
        break
    fi
done

if [ -n "$SOURCE_FILE" ]; then
    LOG_FILE="${OUTPUT_DIR}/$(echo "$SOURCE_FILE" | tr '/' '_').stderr"
    "$COMPILER" "$@" 2> "$LOG_FILE"
    EXIT_CODE=$?
else
    # Not a compilation (e.g., linking) — don't capture
    "$COMPILER" "$@"
    EXIT_CODE=$?
fi

exit $EXIT_CODE
```

---

## 5. Data Consolidation

### 5.1 Overview

Three consolidation scripts read from `data/raw/`, join and aggregate the per-file and per-target data, and produce three Parquet files in `data/processed/`. The file-level script runs first, since the target-level script aggregates from it. All data is preserved — both raw metrics and derived convenience columns — to support deep follow-on analysis.

### 5.2 Path Canonicalisation

File paths are the universal join key. All consolidation scripts use the canonical absolute path established in step 1 (`os.path.realpath()`). The canonicalisation rules:

1. Git paths (relative to repo root) → prepend `source_dir`, then `realpath()`.
2. File API paths (relative to source root or absolute) → if relative, prepend source root, then `realpath()`.
3. Build artefact paths (relative to build dir) → prepend `build_dir`, then `realpath()`.
4. Object file paths → mapped to source files via the File API `files.json`, not by path manipulation.

### 5.3 build_file_metrics.py — File-Level DataFrame

Joins all per-file data by canonical source file path. This is the most granular dataset.

**Columns:**

| Column | Type | Source | Notes |
|---|---|---|---|
| `source_file` | str | File API | Canonical absolute path (primary key) |
| `cmake_target` | str | File API | Owning target name |
| `is_generated` | bool | File API | True for codegen output files |
| `language` | str | File API | CXX, C, etc. |
| `compile_time_ms` | int | ninja_log.csv | Wall-clock compile time from ninja log |
| `gcc_parse_time_ms` | float | ftime_report.json | GCC parsing phase time |
| `gcc_template_instantiation_ms` | float | ftime_report.json | GCC template instantiation time |
| `gcc_codegen_time_ms` | float | ftime_report.json | GCC code generation phase time |
| `gcc_optimization_time_ms` | float | ftime_report.json | GCC optimization phase time |
| `gcc_total_time_ms` | float | ftime_report.json | GCC total reported time |
| `code_lines` | int | sloc.csv | Non-blank, non-comment lines |
| `blank_lines` | int | sloc.csv | Blank lines |
| `comment_lines` | int | sloc.csv | Comment lines |
| `source_size_bytes` | int | sloc.csv | Raw source file size |
| `header_max_depth` | int | header_data.json | Maximum inclusion depth |
| `unique_headers` | int | header_data.json | Count of distinct included headers |
| `total_includes` | int | header_data.json | Total inclusion count (with duplicates) |
| `header_tree` | json | header_data.json | Full inclusion tree as list of (depth, path) |
| `preprocessed_bytes` | int | preprocessed_size.csv | Size after macro expansion |
| `object_size_bytes` | int | object_files.csv | Compiled object file size |
| `git_commit_count` | int | git_history_summary.csv | Commits touching this file |
| `git_lines_added` | int | git_history_summary.csv | Total lines added |
| `git_lines_deleted` | int | git_history_summary.csv | Total lines deleted |
| `git_churn` | int | git_history_summary.csv | lines_added + lines_deleted |
| `git_distinct_authors` | int | git_history_summary.csv | Unique committers |
| `git_last_change_date` | datetime | git_history_summary.csv | Most recent modification |
| `expansion_ratio` | float | Derived | `preprocessed_bytes / source_size_bytes` |
| `compile_rate_lines_per_sec` | float | Derived | `code_lines / (compile_time_ms / 1000)` |
| `object_efficiency` | float | Derived | `object_size_bytes / code_lines` |

**Output:** `data/processed/file_metrics.parquet`

**Notes:**
- Generated files will have `git_commit_count = 0` and null git fields. This is correct and expected.
- The `header_tree` column stores the full inclusion hierarchy as JSON. While not used for aggregate statistics, it enables per-file include graph analysis in notebooks.
- The `expansion_ratio` is particularly informative for generated files, which often have high expansion due to generated boilerplate pulling in many headers.

### 5.4 build_target_metrics.py — Target-Level DataFrame

Aggregates file-level metrics to one row per CMake target. Incorporates dependency graph metrics. Includes separate sub-aggregations for codegen and non-codegen files.

**Columns:**

| Column | Type | Derivation |
|---|---|---|
| `cmake_target` | str | Target name (primary key) |
| `target_type` | str | EXECUTABLE, STATIC_LIBRARY, etc. from File API |
| `output_artifact` | str | `nameOnDisk` from File API |
| **Source file counts** | | |
| `file_count` | int | Total source files |
| `codegen_file_count` | int | Count where `is_generated == True` |
| `authored_file_count` | int | `file_count - codegen_file_count` |
| `codegen_ratio` | float | `codegen_file_count / file_count` |
| **SLOC metrics** | | |
| `code_lines_total` | int | Sum of `code_lines` (all files) |
| `code_lines_authored` | int | Sum of `code_lines` (authored files only) |
| `code_lines_generated` | int | Sum of `code_lines` (generated files only) |
| **Compile time metrics (all files)** | | |
| `compile_time_sum_ms` | int | Sum of compile times |
| `compile_time_max_ms` | int | Max single-file compile time |
| `compile_time_mean_ms` | float | Mean compile time |
| `compile_time_median_ms` | float | Median compile time |
| `compile_time_std_ms` | float | Standard deviation |
| `compile_time_p90_ms` | float | 90th percentile |
| `compile_time_p99_ms` | float | 99th percentile |
| **Compile time metrics (authored files)** | | |
| `authored_compile_time_sum_ms` | int | Sum for authored files |
| `authored_compile_time_max_ms` | int | Max for authored files |
| **Compile time metrics (generated files)** | | |
| `codegen_compile_time_sum_ms` | int | Sum for generated files |
| `codegen_compile_time_max_ms` | int | Max for generated files |
| **GCC phase breakdown (target aggregates)** | | |
| `gcc_parse_time_sum_ms` | float | Sum of parsing time |
| `gcc_template_time_sum_ms` | float | Sum of template instantiation |
| `gcc_codegen_phase_sum_ms` | float | Sum of code generation phase |
| `gcc_optimization_time_sum_ms` | float | Sum of optimization time |
| **Header metrics** | | |
| `header_depth_max` | int | Max of `header_max_depth` across files |
| `header_depth_mean` | float | Mean of `header_max_depth` |
| `unique_headers_total` | int | Count of distinct headers across all files in target |
| `total_includes_sum` | int | Sum of `total_includes` |
| **Preprocessed size** | | |
| `preprocessed_bytes_total` | int | Sum of `preprocessed_bytes` |
| `preprocessed_bytes_mean` | float | Mean |
| `expansion_ratio_mean` | float | Mean of `expansion_ratio` |
| **Object file metrics** | | |
| `object_size_total_bytes` | int | Sum of `object_size_bytes` |
| `object_file_count` | int | Count of `.o` files |
| **Build step timing (from ninja log)** | | |
| `codegen_time_ms` | int | Sum of codegen step durations for this target |
| `archive_time_ms` | int | Duration of the archive step (if STATIC_LIBRARY) |
| `link_time_ms` | int | Duration of the link step (if EXECUTABLE or SHARED_LIBRARY) |
| `total_build_time_ms` | int | `compile_time_sum_ms + codegen_time_ms + archive_time_ms + link_time_ms` |
| **Git activity** | | |
| `git_commit_count_total` | int | Sum of file commit counts (authored files only) |
| `git_churn_total` | int | Sum of churn (authored files only) |
| `git_distinct_authors` | int | Union of authors across files |
| `git_hotspot_file_count` | int | Files with commit count > mean + 1σ |
| **Dependency graph metrics** | | |
| `direct_dependency_count` | int | From `linkLibraries` (successors) |
| `transitive_dependency_count` | int | From `dependencies` minus direct |
| `total_dependency_count` | int | Total from `dependencies` |
| `direct_dependant_count` | int | Predecessors in the graph |
| `transitive_dependant_count` | int | `nx.ancestors` in the reversed graph |
| `topological_depth` | int | Longest path from a root to this node |
| `critical_path_contribution_ms` | int | This target's weight on the critical path |
| `fan_in` | int | Synonym for direct_dependant_count |
| `fan_out` | int | Synonym for direct_dependency_count |
| `betweenness_centrality` | float | Betweenness centrality in the DAG |
| **Input/output file lists** | | |
| `source_files` | list[str] | List of all source file paths (from File API) |
| `generated_files` | list[str] | Subset where `is_generated == True` |
| `output_files` | list[str] | `artifacts[].path` from File API |

**Output:** `data/processed/target_metrics.parquet`

**Notes:**
- Compile time distribution metrics (mean, median, std, p90, p99) enable analysis of whether a target's build cost is dominated by a few heavy files or spread evenly — informing split decisions.
- The separate authored/generated breakdowns for file counts, SLOC, and compile time enable direct measurement of codegen impact per target.
- `total_build_time_ms` is the serial cost of building the target. The actual wall-clock time depends on parallelism, which is analysed via the ninja log start/end times in the notebooks.
- The `source_files` and `generated_files` lists are stored to enable drill-down from target to file metrics without re-joining.

### 5.5 build_edge_list.py — Edge List DataFrame

Builds the edge list from the CMake File API dependency data, replacing the v1 graphviz dot-file parser.

**Columns:**

| Column | Type | Source |
|---|---|---|
| `source_target` | str | The depending target (has the dependency) |
| `dest_target` | str | The dependency (depended upon) |
| `is_direct` | bool | True if from `linkLibraries`/`orderDependencies`, False if transitive-only |
| `dependency_type` | str | `link` (from linkLibraries), `compile` (from compileDependencies), `object` (from objectDependencies), `order` (from orderDependencies), `transitive` (in dependencies but not in any direct set) |
| `source_target_type` | str | Target type of the source |
| `dest_target_type` | str | Target type of the destination |
| `from_dependency` | str | If present in linkLibraries with `fromDependency`, the target that injected this dependency |

**Output:** `data/processed/edge_list.parquet`

**Notes:**
- The `is_direct` classification is reliable on CMake 4.2+ (codemodel 2.9) using the `linkLibraries` field. This is a major improvement over v1, where the graphviz output provided scope labels (PUBLIC/PRIVATE/INTERFACE) but did not distinguish direct from transitive.
- The `dependency_type` column enables filtering edges by their semantic meaning. Link dependencies affect the linker command; compile dependencies affect include paths and defines; order dependencies only affect build ordering.
- The `from_dependency` column identifies dependencies that were injected by a transitive interface rather than explicitly written in `target_link_libraries()`. These are candidates for analysis: they may be unnecessarily coupled.

### 5.6 Persistence Format

All three files are stored as Parquet using PyArrow. Parquet is chosen for type preservation, compression, and fast columnar access. The `header_tree` and list columns are stored as JSON strings within Parquet for compatibility.

---

## 6. Shared Library — `src/build_optimiser/`

### 6.1 config.py

Same as v1:
- Loads `config.yaml`.
- Renders `toolchain.cmake` with substituted compiler paths.
- Provides `build_cmake_command(pass_flags: dict) -> list[str]`.
- Provides `build_ninja_command() -> list[str]`.

### 6.2 cmake_file_api.py (NEW)

This module encapsulates all CMake File API interaction:

- `create_query_files(build_dir: str, client_name: str)` — creates the query directory and empty query files.
- `parse_reply(build_dir: str) -> CodeModel` — finds the index file, loads the codemodel, loads all target objects, and returns a structured `CodeModel` object.
- `CodeModel` dataclass containing:
  - `targets: dict[str, Target]` — keyed by target name
  - `files: list[FileEntry]` — all source files with metadata
  - `edges: list[Edge]` — dependency edges
- `Target` dataclass containing all fields from §4.3 step 1.
- `FileEntry` dataclass: `path`, `cmake_target`, `compile_group_index`, `is_generated`, `language`.
- `build_file_index(codemodel: CodeModel) -> dict[str, str]` — maps canonical file path → target name.
- `build_target_index(codemodel: CodeModel) -> dict[str, Target]` — maps target name → Target object.
- `build_codegen_inventory(codemodel: CodeModel) -> dict[str, list[str]]` — maps target name → list of generated file paths.
- `reconstruct_compile_command(file_entry: FileEntry, target: Target, compiler_path: str) -> str` — builds a complete compile command from structured File API data.

### 6.3 graph.py

Updated to use `cmake_file_api.py` instead of dot-file parsing:

- `load_graph(edge_list_path: str) -> nx.DiGraph` — reads the edge list Parquet and returns a NetworkX directed graph. Edges carry attributes: `is_direct`, `dependency_type`.
- `load_graph_from_codemodel(codemodel: CodeModel) -> nx.DiGraph` — builds the graph directly from the parsed File API data.
- `direct_dependencies(G, target) -> list[str]` — filters edges where `is_direct == True`.
- `transitive_dependencies(G, target) -> set[str]` — `nx.descendants` minus direct dependencies.
- `direct_dependants(G, target) -> list[str]`
- `transitive_dependants(G, target) -> set[str]`
- `topological_depth(G, target) -> int`
- `critical_path(G, weight_attr) -> list[str]` — longest weighted path through the DAG.
- `node_centrality(G) -> dict` — betweenness centrality for all nodes.
- `attach_metrics(G, df: pd.DataFrame)` — sets target-level metrics as node attributes from the target DataFrame.
- `subgraph_for_target(G, target, depth: int = 1) -> nx.DiGraph` — extract the local neighbourhood for visualisation.

### 6.4 metrics.py

Updated to use File API data for file-to-target mapping:

- `map_file_to_target(file_path: str, file_index: dict) -> str` — uses the File API file index instead of `CMakeFiles/<target>.dir/` path parsing.
- `canonicalise_path(path: str, base_dir: str) -> str` — standard path canonicalisation.
- Aggregation functions that roll up file metrics to target metrics, with separate codegen/authored sub-aggregations.
- Distribution summary functions: computes mean, median, std, p90, p99 for any metric series.

### 6.5 simulation.py

Same core functions as v1, updated to account for codegen:

- `rebuild_cost(G, target, metrics_df) -> int` — total transitive rebuild cost if a target changes. Now includes codegen time in the cost.
- `expected_daily_cost(G, target, metrics_df, git_df) -> float` — rebuild cost weighted by change probability.
- `simulate_merge(G, targets: list[str], metrics_df) -> dict` — simulates merging targets and returns before/after build cost metrics. Updated to handle codegen files: if a target being merged contains codegen, the codegen time is carried into the merged target.
- `simulate_split(G, target: str, file_groups: list[list[str]], metrics_df) -> dict` — simulates splitting a target. Special handling: generated files should stay with the files that consume them (identified via include analysis).
- `codegen_cascade_cost(G, target, metrics_df) -> int` — **new**: computes the total downstream rebuild cost triggered by a codegen step. This answers: "if this codegen is slow or changes frequently, how much build time does it cause?"

---

## 7. Analysis Notebooks

All notebooks share a common data loading preamble: read the three Parquet files, load the dependency graph, and attach metrics as node attributes.

### 7.1 Notebook 01 — Data Cleaning

Same scope as v1, updated for new data sources:

**Tasks:**
- **Missing data:** Identify targets with missing compile times (INTERFACE_LIBRARY, UTILITY, imported targets). Decide whether to exclude or fill with zero. Generated files with no git history should have git fields set to 0/null, not treated as missing.
- **Outlier detection:** Flag files with anomalous compile times using IQR or Z-score methods. Visualise outliers. Compare `-ftime-report` totals against ninja log wall-clock times for consistency.
- **Path alignment:** Verify that all file paths across collectors match the canonical paths from the File API. Report any files present in one dataset but not another.
- **Target validation:** Cross-reference the target list from the File API with targets found in the ninja log. Identify targets that appear in the graph but were not built (e.g., excluded by CMake conditions), and built outputs that don't map to any File API target.
- **Codegen validation:** Verify that every file marked `is_generated` in the File API either (a) has no git history, or (b) is a generated file that also exists in the source tree (rare but possible). Flag anomalies.
- **Type casting and normalisation:** Ensure all columns have correct types. Normalise time units (everything in milliseconds).
- **Output:** Cleaned versions of all three Parquet files.

### 7.2 Notebook 02 — Exploratory Data Analysis

Same scope as v1, expanded with codegen dimensions:

**Tasks:**
- **Distribution plots:** Histograms of compile time, SLOC, header depth, preprocessed size, object size, git change count. Use log scale where distributions are heavily skewed. **New: overlay codegen vs authored distributions** to see if they differ.
- **Pareto analysis:** Which 20% of targets account for 80% of total compile time? Include a **codegen Pareto**: which 20% of codegen steps account for 80% of codegen time?
- **Correlation analysis:** Scatter plots and correlations between:
  - SLOC and compile time (find template-heavy files)
  - Header depth and preprocessed size (include bloat)
  - Git change frequency and dependant count (change impact)
  - **New: preprocessed size and GCC template instantiation time** (template cost)
  - **New: expansion ratio and compile time** (include/macro bloat correlation)
  - **New: codegen output volume (SLOC of generated files) and downstream compile time**
- **GCC phase breakdown:** Stacked bar charts showing how each target's compile time breaks down into parsing, template instantiation, code generation, and optimisation. Identify targets where template instantiation dominates.
- **Dependency structure overview:** Degree distribution (in-degree and out-degree). DAG depth distribution. Identify the widest level (maximum parallelism potential). **New: highlight codegen targets in the DAG** to see where they sit.
- **Codegen overview:** Summary statistics of codegen impact: total codegen files, total codegen SLOC, total codegen compile time, codegen as percentage of total build cost.

### 7.3 Notebook 03 — Critical Path Analysis

Same scope as v1, expanded with codegen awareness:

**Tasks:**
- **Compute the critical path:** Longest weighted path through the DAG. Weights should incorporate the **full target build cost**: `codegen_time_ms + compile_time_max_ms + archive_time_ms + link_time_ms`. Use the max single-file compile time because files within a target compile in parallel.
- **Critical path with codegen:** If a target has codegen steps, those must complete before any of its source files can compile (codegen outputs are inputs to compilation). The effective weight for a target with codegen is: `codegen_time_ms + compile_time_max_ms + archive_or_link_time_ms`. This may significantly change the critical path compared to v1 which ignored codegen.
- **Slack analysis:** For each target, compute slack — how much its build time could increase before it becomes part of the critical path. Targets with zero slack are critical.
- **Codegen on the critical path:** Identify codegen steps that sit on the critical path. These are high-priority optimisation targets: reducing codegen time directly reduces the minimum build time.
- **Visualisation:** Render the DAG with critical path highlighted. Annotate codegen targets distinctly (different colour/shape). Show compile times and slack values.
- **Bottleneck ranking:** Rank targets by contribution to the critical path. Separate ranking for codegen bottlenecks vs compilation bottlenecks.
- **Build parallelism analysis (NEW):** Using the ninja log `start_ms` and `end_ms` data, compute the actual achieved parallelism over the build timeline. Plot the number of concurrent build steps over time. Identify periods of low parallelism (serialisation bottlenecks). Compare actual build time against theoretical critical path time to compute the parallelism efficiency ratio.

### 7.4 Notebook 04 — Community Detection

Same scope as v1, with refinements:

**Tasks:**
- **Community detection:** Apply Louvain and Leiden algorithms to the undirected dependency graph. **Refinement: use only direct dependency edges** (`is_direct == True`) for community detection, since transitive edges add noise. This is a direct benefit of the File API's `linkLibraries` data.
- **Resolution parameter tuning:** Sweep the resolution parameter. Evaluate modularity at each level.
- **Community characterisation:** Per community: target count, total compile time, total SLOC, internal vs external edge count (cohesion vs coupling ratio), **codegen target count, codegen compile time**.
- **Bridging targets:** Betweenness centrality. High-centrality targets connecting communities are split candidates.
- **Codegen community patterns (NEW):** Do codegen targets cluster within specific communities, or are they spread across the graph? If clustered, the community may be a codegen-heavy subsystem where codegen optimisation has outsized impact.
- **Visualisation:** DAG coloured by community. Codegen targets marked distinctly. Community-level summary graph.
- **Merge candidates:** Communities with high internal coupling and low external coupling.

### 7.5 Notebook 05 — Change Impact Simulation

Same scope as v1, with codegen refinements:

**Tasks:**
- **Change probability model:** Per-target change probability from git history. **Refinement: generated files are excluded from change probability** since they don't change independently — they change when their generator inputs change. The change probability for a codegen target's generated files should be modelled as the change probability of the codegen inputs (if identifiable) or the target itself.
- **Expected rebuild cost:** For each target: `change_probability × transitive_rebuild_cost`. Include codegen cascade cost — if a target's codegen outputs change, all downstream targets that compile those outputs must rebuild.
- **Merge simulation:** Updated to handle codegen: merging targets that share codegen inputs may eliminate redundant generation steps.
- **Split simulation:** Updated: generated files should stay with the partition that consumes them.
- **Monte Carlo simulation:** Sample random workdays, simulate rebuilds, compare structures.
- **Sensitivity analysis:** Re-run with 3, 6, 12 month git windows.

### 7.6 Notebook 06 — Clustering and Dimensionality Reduction

Same scope as v1, with expanded feature set:

**Tasks:**
- **Feature matrix construction:** Each target is a row. Features (all normalised): `compile_time_sum_ms`, `code_lines_total`, `file_count`, `header_depth_max`, `preprocessed_bytes_total`, `object_size_total_bytes`, `direct_dependency_count`, `transitive_dependency_count`, `direct_dependant_count`, `git_commit_count_total`, `link_time_ms`, **`codegen_ratio`** (new), **`codegen_compile_time_sum_ms`** (new), **`expansion_ratio_mean`** (new), **`gcc_template_time_sum_ms`** (new).
- **Dimensionality reduction:** PCA, then t-SNE/UMAP for 2D visualisation. Colour by community.
- **Clustering:** DBSCAN and hierarchical clustering. Compare with communities.
- **Interpretation:** Centroid feature values per cluster. Are there clusters of codegen-heavy targets? Template-heavy targets? Include-bloated targets?
- **Outlier detection:** DBSCAN noise points. Individual attention needed.

### 7.7 Notebook 07 — Spectral Graph Partitioning

Same scope as v1:

**Tasks:**
- **Intra-target dependency graph:** For split candidates, build a file-level include graph using the header trees from `header_data.json` (preserved in file metrics). Weight edges by co-change frequency.
- **Spectral partitioning:** Fiedler vector for 2-way partition. k eigenvectors + k-means for k-way.
- **METIS partitioning:** pymetis as alternative. Weight nodes by compile time or SLOC.
- **Constraint handling:** `.cpp`/`.h` pairs contracted into single nodes. **New constraint: generated files and their consumers should be co-located** — split along the codegen boundary if possible, not across it.
- **Evaluation:** Cross-partition includes (new inter-target deps), compile time balance, critical path impact.

### 7.8 Notebook 08 — Codegen Analysis (NEW)

**Purpose:** Dedicated analysis of code generation's impact on build performance, providing specific recommendations for codegen optimisation.

**Tasks:**

- **Codegen inventory summary:** Total generated files, total generated SLOC, total codegen compile time, codegen as a percentage of total build cost. Break down by codegen type if identifiable (protobuf, thrift, MOC, custom generators).
- **Codegen timing analysis:** Using ninja log data, analyse codegen step durations. Which generators are slowest? Are any codegen steps on the critical path? What is the total wall-clock time spent in codegen vs compilation vs linking?
- **Codegen fan-out analysis:** For each codegen step, how many targets consume its outputs? A codegen step with high fan-out that sits on the critical path is a prime optimisation target — parallelising or caching it would benefit many downstream targets.
- **Generated file compilation cost:** Compare compilation metrics (compile time, preprocessed size, object size, header depth) between generated and authored files. Generated files often have worse metrics due to machine-generated code being verbose, including unnecessary headers, or triggering excessive template instantiation. Identify the worst offenders.
- **Codegen-triggered rebuild analysis:** When a codegen input changes, all generated outputs change, triggering recompilation of everything that includes them. Compute the total rebuild cost triggered by each codegen step. Rank by rebuild cost × change frequency.
- **Codegen dependency analysis:** Using the File API dependency data, trace which targets depend on targets with codegen. Compute the transitive codegen exposure — how many targets are affected (directly or transitively) by a given codegen step changing.
- **Recommendations:**
  - **Codegen caching:** Identify codegen steps that could benefit from output caching (e.g., protobuf generates the same output for the same input).
  - **Codegen parallelism:** Identify independent codegen steps that could run in parallel but are currently serialised due to dependency structure.
  - **Generated file optimisation:** Identify generated files with excessive preprocessed size or header depth — these may benefit from forward declarations or precompiled headers.
  - **Codegen consolidation:** Could multiple small codegen steps be batched into fewer, larger steps to reduce per-step overhead?
  - **Codegen isolation:** Could codegen outputs be wrapped in a header-only interface library to limit recompilation scope?

### 7.9 Notebook 09 — Recommendations

Synthesises findings from all analyses (formerly notebook 08 in v1).

**Tasks:**
- **Compile a candidate list:** Merge candidates, split candidates, individual target optimisations, and **codegen optimisations** (from notebook 08).
- **Score each candidate:** Expected build time improvement from change impact simulation. Factor in implementation effort.
- **Rank by ROI:** `(expected build time saved per day) / (estimated implementation effort)`.
- **Quick wins:** Flag low-effort improvements:
  - Removing unused dependencies (edges in the graph with no actual `#include` backing — detectable by comparing `linkLibraries` edges against actual include analysis from header trees).
  - Targets on the critical path with high `expansion_ratio` (candidates for include-what-you-use cleanup).
  - Targets with high header depth (precompiled header candidates).
  - **New: codegen steps on the critical path** (candidates for caching or parallelisation).
  - **New: generated files with high preprocessed size** (candidates for include optimisation in the generator templates).
  - **New: targets with high codegen ratio where generated files dominate compile time** (indicates generator output quality issues).
- **Incremental vs CI recommendations:** Separate recommendations for incremental build optimisation (which targets change frequently and cause expensive rebuilds?) and CI full-rebuild optimisation (which targets dominate the critical path?).
- **Output:** `data/results/recommendations.csv` and a formatted Markdown/HTML report with visualisations.

---

## 8. Dependencies

### 8.1 pyproject.toml

```toml
[project]
name = "build-optimiser"
version = "0.2.0"
requires-python = ">=3.10"

dependencies = [
    # Core data handling
    "pandas>=2.0",
    "pyarrow>=14.0",

    # Graph analysis
    "networkx>=3.0",
    # pydot no longer needed — graphviz parsing removed

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

**Change from v1:** `pydot>=2.0` removed — no longer needed since graphviz dot files are not used. The CMake File API JSON is parsed directly with Python's built-in `json` module.

---

## 9. Implementation Order

1. **Project skeleton:** Create the directory structure, `pyproject.toml`, `config.yaml` template, empty `__init__.py`.
2. **`src/build_optimiser/config.py`:** Config loading, toolchain rendering, CMake command builder.
3. **`src/build_optimiser/cmake_file_api.py`:** File API query creation, reply parsing, target/file/edge extraction. This is the new foundational module.
4. **`scripts/collect/01_cmake_file_api.py`:** Configure build tree, parse File API, write raw JSON outputs.
5. **`scripts/collect/02_git_history.py`:** Git history collection with full metadata.
6. **Compiler wrapper script:** `scripts/collect/wrappers/capture_stderr.sh`.
7. **`scripts/collect/03_instrumented_build.py`:** Orchestrate the single instrumented build, parse stderr logs.
8. **`scripts/collect/04_post_build_metrics.py`:** Object file sizes and SLOC.
9. **`scripts/collect/05_preprocessed_size.py`:** Parallel preprocessing.
10. **`scripts/collect/06_ninja_log.py`:** Ninja log parsing with target classification.
11. **`scripts/collect/collect_all.sh`:** Orchestration wrapper.
12. **`src/build_optimiser/metrics.py`:** Path canonicalisation, aggregation functions with codegen sub-aggregations.
13. **Consolidation scripts:** `build_file_metrics.py`, `build_target_metrics.py`, `build_edge_list.py`.
14. **`src/build_optimiser/graph.py`:** Graph loading from edge list, analysis utilities.
15. **`src/build_optimiser/simulation.py`:** Rebuild cost and simulation logic with codegen support.
16. **Notebooks 01–09:** In numbered order, as each builds on prior results.
17. **Tests:** Unit tests for all modules in `src/build_optimiser/`.

---

## 10. Summary of Changes from v1

| Aspect | v1 | v2 |
|---|---|---|
| Dependency extraction | CMake `--graphviz` (hours for 3000+ targets) | CMake File API codemodel-v2 (seconds) |
| Configure passes | 4 (graphviz, compile times, header depth, link times) | 1 (single configure with all flags) |
| Full build passes | 2+ (compile times, link times, plus syntax-only) | 1 (single instrumented build) |
| Total collection steps | 8 | 6 |
| Codegen handling | Not tracked | First-class: `isGenerated` flag, codegen inventory, codegen timing, dedicated notebook |
| Direct vs transitive deps | Not distinguished (graphviz labels only) | Explicit via codemodel 2.9 `linkLibraries` |
| Dependency types | Single edge type | link, compile, object, order, transitive |
| File-to-target mapping | `CMakeFiles/<target>.dir/` path parsing | Authoritative File API `sources[]` array |
| GCC phase data | Optional `-ftime-report` | Integrated into single build, stored per file |
| Header data | Separate `-H` pass | Integrated into single build, full trees preserved |
| Compile time distribution | sum, max only | mean, median, std, p90, p99 |
| Ninja log analysis | Per-file compile times only | Full step classification: compile, codegen, archive, link |
| Build parallelism analysis | Not performed | Ninja log start/end times enable parallelism profiling |
| Community detection input | All edges (noisy) | Direct edges only (from `linkLibraries`) |
| Git history | Summary counts only | Full commit-level detail preserved |
| Analysis notebooks | 8 | 9 (new: dedicated codegen analysis) |
| Python dep: pydot | Required | Removed |
