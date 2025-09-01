# Example CMake Project — Fixture Design

## 1. Purpose

This document specifies a minimal CMake project that lives within the build-optimiser source tree at `tests/fixture/`. It serves two roles:

1. **Ground truth for collection script development.** Running the 6 collection steps against this project produces real File API JSON, ninja logs, stderr captures, and git history — providing concrete examples of every data format the scripts must parse.
2. **Test suite foundation.** Because the project is small and deterministic, its expected outputs (target count, file count, dependency edges, codegen files, etc.) can be asserted in automated tests.

The project is designed so that every analysis pattern from the v2 specification is demonstrable at miniature scale. Each deliberate pathology is documented below with the notebook it exercises.

---

## 2. Design Constraints

- **Portable.** Must compile with any GCC 10+ or Clang 14+ on Linux/macOS. No external dependencies. No platform-specific system calls.
- **Deterministic.** No randomness, no network, no filesystem access beyond what CMake/Ninja provides. Compile times are obviously tiny, but the _structure_ of the metrics (which files are slow relative to others) is controlled by deliberate template and include bloat.
- **Self-contained.** Python codegen script included. No submodules.
- **Git-historied.** The fixture directory is committed to the build-optimiser repo with a synthetic git history (a script creates the commits). This gives the git history collector real data to parse.
- **CMake 3.16+ compatible for build, 4.2+ for File API features.** The CMakeLists.txt uses only standard CMake. The codemodel 2.9 features (linkLibraries, direct vs transitive) are tested by running cmake 4.2+ against this project.

---

## 3. Target Dependency Graph

Note: `plugin_api` (SHARED_LIBRARY, depends on core+logging) and `math_objs` (OBJECT_LIBRARY, consumed by math_lib via $<TARGET_OBJECTS>) are not shown in the diagram for clarity. See §3.1 for the complete target list.

```
                          ┌──────────┐
                          │   core   │  (STATIC_LIBRARY, leaf, high fan-out)
                          └────┬─────┘
               ┌───────────┬───┼───────────┬──────────────┐
               ▼           ▼   ▼           ▼              ▼
          ┌────────┐  ┌────────┐  ┌──────────┐   ┌──────────────┐
          │logging │  │platform│  │ math_lib │   │ proto_gen     │
          │        │  │        │  │(template │   │ (UTILITY,     │
          │        │  │        │  │ heavy)   │   │  codegen step)│
          └───┬────┘  └───┬────┘  └────┬─────┘   └──────┬───────┘
              │            │           │                 │ generates
              │            │           │           ┌─────▼───────┐
              │            │           │           │ proto_msgs  │
              │            │           │           │ (has codegen │
              │            │           │           │  + authored) │
              │            │           │           └──────┬──────┘
              │            │           │                  │
              │            │      ┌────▼─────┐    ┌──────▼──────┐
              │            │      │ compute  │    │serialization│
              │            │      │          │    │             │
              │            └──────┤          │    └──────┬──────┘
              │                   └────┬─────┘           │
              │                        │          ┌──────▼──────┐
              │                        │          │  protocol   │
              │                        │          │             │
              └────────────────────────┤          └──────┬──────┘
                                       │                 │
                                  ┌────▼─────────────────▼──┐
                                  │      middleware          │
                                  │  (bridging, high        │
                                  │   centrality, split     │
                                  │   candidate)            │
                                  └──────────┬──────────────┘
                                             │
                                       ┌─────▼──────┐
                                       │   engine   │
                                       └─────┬──────┘
                              ┌──────────────┼──────────────┐
                              ▼              ▼              ▼
                        ┌─────────┐   ┌───────────┐  ┌───────────┐
                        │   app   │   │test_runner│  │  benchmark│
                        │  (EXE)  │   │  (EXE)    │  │  (EXE)    │
                        └─────────┘   └───────────┘  └───────────┘
```

### 3.1 Target Summary

| # | Target | Type | Direct Dependencies | Role in Analysis |
|---|--------|------|---------------------|-----------------|
| 1 | `core` | STATIC_LIBRARY | none | Leaf node, highest fan-out (7 direct dependants). Critical path root. |
| 2 | `logging` | STATIC_LIBRARY | `core` | Small utility. Merge candidate with `core` (community detection). |
| 3 | `platform` | STATIC_LIBRARY | `core` | Small utility. Part of core community. |
| 4 | `math_lib` | STATIC_LIBRARY | `core` | **Template-heavy.** Deliberately slow compile (high GCC template instantiation time). Dominates its own compile cost. |
| 5 | `proto_gen` | UTILITY (custom target) | none | **Codegen step.** Runs `python3 generate_messages.py`. Produces generated .h/.cpp files consumed by `proto_msgs`. |
| 6 | `proto_msgs` | STATIC_LIBRARY | `core`, `proto_gen` (order dep) | **Mixed codegen+authored target.** Contains both generated and hand-written files. Exercises `is_generated` tracking. |
| 7 | `serialization` | STATIC_LIBRARY | `proto_msgs`, `core` | Protocol community. Has transitive dep on `core` via `proto_msgs`. |
| 8 | `protocol` | STATIC_LIBRARY | `serialization`, `logging` | Protocol community. Bridges into logging. |
| 9 | `compute` | STATIC_LIBRARY | `math_lib`, `platform` | Engine community. Inherits template cost from `math_lib`. |
| 10 | `middleware` | STATIC_LIBRARY | `protocol`, `compute`, `logging` | **Bridging target.** Highest betweenness centrality. Connects protocol community to engine community. Split candidate (6 source files spanning two functional areas). |
| 11 | `engine` | STATIC_LIBRARY | `middleware` | Aggregator. Deep in the DAG. |
| 12 | `app` | EXECUTABLE | `engine`, `logging` | Final executable. `logging` is a **direct dep that's also transitive** (via engine→middleware→logging). Exercises direct-vs-transitive classification. |
| 13 | `test_runner` | EXECUTABLE | `engine`, `protocol` | Second executable. Exercises multiple paths to same leaf. |
| 14 | `benchmark` | EXECUTABLE | `engine` | Third executable. **Declares a dependency on `math_lib` that it never actually `#include`s.** Exercises unused dependency detection. |
| 15 | `plugin_api` | SHARED_LIBRARY | `core`, `logging` | **Shared library.** Exercises SHARED_LIBRARY target type, produces `.so` with link step (distinct from archive step for static libs). |
| 16 | `math_objs` | OBJECT_LIBRARY | `core` | **Object library.** Contains 2 helper files consumed by `math_lib` via `$<TARGET_OBJECTS:math_objs>`. Exercises OBJECT_LIBRARY type and `objectDependencies[]` in codemodel 2.9. |

**Total: 16 targets** (11 STATIC + 1 SHARED + 1 OBJECT + 3 EXECUTABLE + 1 UTILITY + 1 INTERFACE, but 17 if you include config_iface), **~45 source files** (see §5), **~35 dependency edges**.

### 3.2 Dependency Properties Exercised

| Property | Where in the fixture |
|---|---|
| Direct link dependency | Every `target_link_libraries(... PRIVATE ...)` call |
| Transitive dependency | `app` depends on `core` transitively through `engine→middleware→protocol→serialization→proto_msgs→core`. This chain produces multiple transitive edges in the codemodel `dependencies[]` that are absent from `linkLibraries[]`. |
| PUBLIC propagation | `proto_msgs` links `core` as PUBLIC so that `serialization` inherits it. The `from_dependency` field in codemodel 2.9 records that serialization's link dep on `core` was injected by `proto_msgs`. |
| Order-only dependency | `proto_msgs` depends on `proto_gen` via `add_dependencies()`, not `target_link_libraries()`. This appears in `orderDependencies[]` in codemodel 2.9. |
| Unused dependency | `benchmark` links `math_lib` but never includes any of its headers. Quick-win detection in notebook 09. |
| INTERFACE_LIBRARY | One header-only `config_iface` interface library providing project-wide `#define`s. All targets link it. It has no source files and no compile time. Exercises missing-data handling in notebook 01. |
| SHARED_LIBRARY link step | `plugin_api` produces a `.so` file. The ninja log contains a link step (not an archive step) for this target. Exercises link step classification distinct from static library archiving. |
| OBJECT_LIBRARY and objectDependencies | `math_objs` is an OBJECT_LIBRARY. `math_lib` consumes it via `target_link_libraries(math_lib PRIVATE math_objs)` which uses `$<TARGET_OBJECTS:math_objs>`. This appears in `objectDependencies[]` in codemodel 2.9, exercising a third dependency type. |

---

## 4. Community Structure

The dependency graph is designed to produce three natural communities under Louvain/Leiden:

**Community A — Core/Platform** (high cohesion, low external coupling):
`core`, `logging`, `platform`, `config_iface`

**Community B — Protocol/Codegen** (codegen-heavy subsystem):
`proto_gen`, `proto_msgs`, `serialization`, `protocol`

**Community C — Engine/Compute** (template-heavy subsystem):
`math_lib`, `compute`, `engine`

**Bridging target:** `middleware` connects communities B and C, with an additional edge into community A (via `logging`). It should have the highest betweenness centrality.

**Executables** (`app`, `test_runner`, `benchmark`) sit at the periphery and may form a fourth community or be absorbed into C.

---

## 5. File Inventory

### 5.1 core (STATIC_LIBRARY)

| File | Purpose | Pathology |
|---|---|---|
| `core/types.h` | Basic type aliases, error codes | None (small, fast) |
| `core/types.cpp` | Type utility implementations | None |
| `core/assert.h` | Assertion macros | None |
| `core/assert.cpp` | Assertion implementation | None |
| `core/string_utils.h` | String helper declarations | None |
| `core/string_utils.cpp` | String helper implementations | None |

**6 files.** Small, fast-compiling baseline. Sets the floor for compile time distributions.

### 5.2 logging (STATIC_LIBRARY)

| File | Purpose | Pathology |
|---|---|---|
| `logging/logger.h` | Logger interface | None |
| `logging/logger.cpp` | Logger implementation | None |
| `logging/sink.h` | Output sink abstraction | None |
| `logging/sink.cpp` | File + console sinks | None |

**4 files.** Small. Merge candidate with `core` in community detection.

### 5.3 platform (STATIC_LIBRARY)

| File | Purpose | Pathology |
|---|---|---|
| `platform/filesystem.h` | File path utilities | None |
| `platform/filesystem.cpp` | Implementation | None |
| `platform/thread_pool.h` | Simple thread pool | None |
| `platform/thread_pool.cpp` | Implementation | None |

**4 files.** Small. Part of core community.

### 5.4 math_lib (STATIC_LIBRARY) — Template Heavy

| File | Purpose | Pathology |
|---|---|---|
| `math/matrix.h` | NxM matrix template with full implementation in header | **Template-heavy.** Variadic template operations, SFINAE, compile-time dimension checks. Large header that forces high GCC template instantiation time in any file that includes it. |
| `math/matrix.cpp` | Explicit instantiations for common sizes | **Slow compile.** Instantiates Matrix<float,2,2> through Matrix<float,8,8> plus double variants. High `gcc_template_instantiation_ms`. |
| `math/vector.h` | Vector template, includes matrix.h | **Deep include.** Includes matrix.h, creating depth-2 template chain. |
| `math/vector.cpp` | Explicit instantiations | Moderate compile time. |
| `math/transforms.h` | Transform operations on matrices/vectors | Includes both matrix.h and vector.h. |
| `math/transforms.cpp` | Implementation, heavy template use | **Highest compile time file in the project.** Instantiates many transform operations across multiple type/dimension combinations. |

**6 files.** This target is designed to dominate compile time and demonstrate:
- High `gcc_template_instantiation_ms` vs low `gcc_parse_time_ms` (template cost dominates)
- High `preprocessed_bytes` due to template expansion
- High `expansion_ratio`
- Being on the critical path due to compile cost

### 5.5 proto_gen (UTILITY) — Code Generator

Not a compiled target. This is a `add_custom_target` + `add_custom_command` that runs a Python script.

| File | Purpose |
|---|---|
| `codegen/generate_messages.py` | Python script that reads `codegen/messages.def` and generates C++ source/header files |
| `codegen/messages.def` | Message definition file (simple DSL: message name, field names and types) |

The generator produces:
- `${CMAKE_CURRENT_BINARY_DIR}/generated/messages.h` — message struct declarations, includes many standard headers
- `${CMAKE_CURRENT_BINARY_DIR}/generated/messages.cpp` — serialization implementations
- `${CMAKE_CURRENT_BINARY_DIR}/generated/message_registry.h` — type registry header
- `${CMAKE_CURRENT_BINARY_DIR}/generated/message_registry.cpp` — registry implementation

**4 generated files.** The generator deliberately produces verbose code with excessive includes (similar to real protobuf output). This exercises:
- `isGenerated == true` in File API
- High `preprocessed_bytes` on generated files (expansion ratio analysis)
- Codegen step timing in ninja log
- Codegen fan-out (proto_msgs consumes the output, which feeds serialization, protocol, etc.)

### 5.6 proto_msgs (STATIC_LIBRARY) — Mixed Codegen + Authored

| File | Purpose | Pathology |
|---|---|---|
| `proto/registry.h` | Hand-written registry wrapper | None (authored) |
| `proto/registry.cpp` | Hand-written, includes generated message_registry.h | Authored, but depends on codegen output |
| `proto/validation.h` | Hand-written message validation | None (authored) |
| `proto/validation.cpp` | Validates message fields | None (authored) |
| `generated/messages.h` | **Generated** | High preprocessed size, verbose includes |
| `generated/messages.cpp` | **Generated** | High preprocessed size |
| `generated/message_registry.h` | **Generated** | Verbose |
| `generated/message_registry.cpp` | **Generated** | Verbose |

**8 files (4 authored + 4 generated).** This target exercises:
- `codegen_ratio = 0.5` (half generated)
- Separate authored vs generated compile time metrics
- Generated files with no git history (codegen validation in notebook 01)
- Codegen cascade cost: changing `messages.def` triggers regeneration, which triggers recompilation of all 4 generated files + anything that includes them

### 5.7 serialization (STATIC_LIBRARY)

| File | Purpose | Pathology |
|---|---|---|
| `serialization/encoder.h` | Encoding interface | None |
| `serialization/encoder.cpp` | Implementation, includes generated/messages.h | Downstream of codegen |
| `serialization/decoder.h` | Decoding interface | None |
| `serialization/decoder.cpp` | Implementation | None |

**4 files.** Part of protocol community. Exercises transitive codegen exposure.

### 5.8 protocol (STATIC_LIBRARY)

| File | Purpose | Pathology |
|---|---|---|
| `protocol/handler.h` | Request handler interface | None |
| `protocol/handler.cpp` | Implementation | None |
| `protocol/connection.h` | Connection management | **Deep include chain:** connection.h → serialization/encoder.h → proto/registry.h → generated/messages.h → core/types.h. Depth 5. |
| `protocol/connection.cpp` | Implementation | High `header_max_depth` due to include chain |

**4 files.** Exercises header depth analysis.

### 5.9 compute (STATIC_LIBRARY)

| File | Purpose | Pathology |
|---|---|---|
| `compute/pipeline.h` | Compute pipeline interface | Includes math/matrix.h (template propagation) |
| `compute/pipeline.cpp` | Implementation using matrix operations | **High template instantiation time** inherited from math_lib |
| `compute/scheduler.h` | Work scheduler | Includes platform/thread_pool.h |
| `compute/scheduler.cpp` | Implementation | Moderate compile time |

**4 files.** Inherits template cost from math_lib.

### 5.10 middleware (STATIC_LIBRARY) — Split Candidate

| File | Purpose | Pathology |
|---|---|---|
| `middleware/request_router.h` | Routes requests to handlers | Protocol-facing (includes protocol/handler.h) |
| `middleware/request_router.cpp` | Implementation | Protocol-facing |
| `middleware/metrics_collector.h` | Collects performance metrics | Protocol-facing (includes serialization/encoder.h) |
| `middleware/metrics_collector.cpp` | Implementation | Protocol-facing |
| `middleware/service_registry.h` | Registers compute services | Engine-facing (includes compute/pipeline.h) |
| `middleware/service_registry.cpp` | Implementation | Engine-facing |
| `middleware/rate_limiter.h` | Rate limiting | Engine-facing (includes compute/scheduler.h) |
| `middleware/rate_limiter.cpp` | Implementation | Engine-facing |

**8 files.** Deliberately large and spanning two functional domains:
- **Protocol-facing:** request_router, metrics_collector (include into protocol community)
- **Engine-facing:** service_registry, rate_limiter (include into compute community)

This exercises spectral partitioning (notebook 07): the Fiedler vector should separate the protocol-facing files from the engine-facing files. METIS should find the same split. The split would reduce coupling by creating two smaller targets.

### 5.11 engine (STATIC_LIBRARY)

| File | Purpose | Pathology |
|---|---|---|
| `engine/engine.h` | Main engine facade | None |
| `engine/engine.cpp` | Orchestrates middleware components | None |

**2 files.** Thin aggregator. Deep in the DAG (high topological depth).

### 5.12 app (EXECUTABLE)

| File | Purpose | Pathology |
|---|---|---|
| `app/main.cpp` | Entry point, creates engine and runs | None |

**1 file.**

### 5.13 test_runner (EXECUTABLE)

| File | Purpose | Pathology |
|---|---|---|
| `test/test_main.cpp` | Test harness entry point | None |
| `test/test_protocol.cpp` | Protocol tests | None |
| `test/test_compute.cpp` | Compute tests | Includes math/matrix.h (template cost) |

**3 files.** Second executable, exercises multiple DAG paths to same leaf.

### 5.14 benchmark (EXECUTABLE)

| File | Purpose | Pathology |
|---|---|---|
| `benchmark/bench_main.cpp` | Benchmark entry point | None |

**1 file.** Links `math_lib` in CMakeLists.txt but **never includes any math_lib headers**. This is the unused dependency for quick-win detection.

### 5.15 plugin_api (SHARED_LIBRARY)

| File | Purpose | Pathology |
|---|---|---|
| `plugin_api/plugin_api.h` | Plugin interface (exported symbols) | None |
| `plugin_api/plugin_api.cpp` | Plugin loading and dispatch | None |
| `plugin_api/plugin_registry.h` | Registry of loaded plugins | None |
| `plugin_api/plugin_registry.cpp` | Implementation | None |

**4 files.** SHARED_LIBRARY target. Produces a `.so` (or `.dylib`). The link step in the ninja log is distinct from the `ar` archive step used for STATIC_LIBRARY targets. Exercises SHARED_LIBRARY type handling in File API parsing, and link-step classification in ninja log parsing.

### 5.16 math_objs (OBJECT_LIBRARY)

| File | Purpose | Pathology |
|---|---|---|
| `math/helpers/interpolation.h` | Interpolation routines | None |
| `math/helpers/interpolation.cpp` | Implementation | None |
| `math/helpers/constants.h` | Mathematical constants | None |
| `math/helpers/constants.cpp` | Implementation | None |

**4 files.** OBJECT_LIBRARY target. Produces `.o` files but no archive or linked binary — the objects are consumed directly by `math_lib` via `$<TARGET_OBJECTS:math_objs>`. This exercises OBJECT_LIBRARY type handling and `objectDependencies[]` in codemodel 2.9. In the ninja log, there are compile steps but no archive/link step for this target.

### 5.17 config_iface (INTERFACE_LIBRARY)

No source files. Provides `target_compile_definitions(config_iface INTERFACE PROJECT_VERSION="1.0.0" DEBUG_LEVEL=0)` and is linked by all other targets via `target_link_libraries(... PUBLIC config_iface)` on `core`.

Exercises: INTERFACE_LIBRARY type, no compile time (missing data handling), transitive define propagation.

### 5.18 File Count Summary

| Target | Type | Authored | Generated | Total |
|--------|------|----------|-----------|-------|
| core | STATIC | 6 | 0 | 6 |
| logging | STATIC | 4 | 0 | 4 |
| platform | STATIC | 4 | 0 | 4 |
| math_lib | STATIC | 6 | 0 | 6 |
| math_objs | OBJECT | 4 | 0 | 4 |
| proto_gen | UTILITY | 0 | 0 | 0 |
| proto_msgs | STATIC | 4 | 4 | 8 |
| serialization | STATIC | 4 | 0 | 4 |
| protocol | STATIC | 4 | 0 | 4 |
| compute | STATIC | 4 | 0 | 4 |
| middleware | STATIC | 8 | 0 | 8 |
| engine | STATIC | 2 | 0 | 2 |
| plugin_api | SHARED | 4 | 0 | 4 |
| app | EXECUTABLE | 1 | 0 | 1 |
| test_runner | EXECUTABLE | 3 | 0 | 3 |
| benchmark | EXECUTABLE | 1 | 0 | 1 |
| config_iface | INTERFACE | 0 | 0 | 0 |
| **Total** | | **59** | **4** | **63** |

---

## 6. Codegen Design

### 6.1 Generator Script: `codegen/generate_messages.py`

A Python script that reads a simple message definition file and produces C++ code. The definition format is deliberately simple:

```
# messages.def
message StatusUpdate {
    uint32 id;
    string name;
    int64 timestamp;
    uint32 status_code;
    string payload;
}

message ConfigChange {
    string key;
    string value;
    int64 effective_time;
    uint32 version;
}

message MetricReport {
    string metric_name;
    double value;
    int64 timestamp;
    uint32 source_id;
    string unit;
    uint32 count;
}
```

### 6.2 Generated Output Characteristics

The generator deliberately produces **verbose** output to simulate real-world codegen (protobuf, thrift, etc.):

- **messages.h**: Each message becomes a struct with constructors, comparison operators, serialization methods, a static type name, and a factory function. Includes `<string>`, `<cstdint>`, `<vector>`, `<memory>`, `<functional>`, `<stdexcept>`, `<algorithm>`, `<sstream>`, `<iostream>` — deliberately over-inclusive to inflate preprocessed size. Approximately 150-200 lines per message.
- **messages.cpp**: Serialization/deserialization method implementations. Uses stringstream operations that generate moderate template instantiation. ~100-150 lines per message.
- **message_registry.h**: A type registry that maps message type names to factory functions. Includes messages.h plus `<map>`, `<typeindex>`.
- **message_registry.cpp**: Registry implementation with static initialization.

Expected metrics for generated files:
- `preprocessed_bytes`: 3-5× higher than authored files of similar SLOC (due to verbose includes)
- `expansion_ratio`: 10-20× (generated code is small but pulls in many headers)
- `header_max_depth`: moderate (2-3 levels from standard library headers)
- `gcc_template_instantiation_ms`: moderate (stringstream usage triggers template work)
- `git_commit_count`: 0 (correctly, since these files don't exist in git)

### 6.3 CMake Integration

```cmake
# codegen/CMakeLists.txt

find_package(Python3 REQUIRED COMPONENTS Interpreter)

set(GENERATED_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated")
file(MAKE_DIRECTORY "${GENERATED_DIR}")

set(GENERATED_SOURCES
    "${GENERATED_DIR}/messages.h"
    "${GENERATED_DIR}/messages.cpp"
    "${GENERATED_DIR}/message_registry.h"
    "${GENERATED_DIR}/message_registry.cpp"
)

add_custom_command(
    OUTPUT ${GENERATED_SOURCES}
    COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/generate_messages.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/messages.def"
        "${GENERATED_DIR}"
    DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/generate_messages.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/messages.def"
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    COMMENT "Generating message classes from messages.def"
)

add_custom_target(proto_gen DEPENDS ${GENERATED_SOURCES})

add_library(proto_msgs STATIC
    proto/registry.h
    proto/registry.cpp
    proto/validation.h
    proto/validation.cpp
    ${GENERATED_SOURCES}
)
target_include_directories(proto_msgs PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}"
    "${GENERATED_DIR}"
)
target_link_libraries(proto_msgs PUBLIC core)
add_dependencies(proto_msgs proto_gen)
```

This CMake pattern ensures:
- `proto_gen` is a UTILITY target visible in the File API
- Generated files are marked `isGenerated: true` in the codemodel because they are `OUTPUT` of `add_custom_command()`
- `proto_msgs` has an order dependency on `proto_gen` (via `add_dependencies`), which appears in `orderDependencies[]` in codemodel 2.9
- The codegen step appears as a `CUSTOM_COMMAND` build edge in ninja, with timing captured in `.ninja_log`

---

## 7. Deliberate Pathologies

Each pathology is designed to produce a measurable signal in the collected data and exercise a specific analysis pattern.

### 7.1 Template Bloat (math_lib)

**What:** `math/matrix.h` contains a fully header-implemented `Matrix<T,Rows,Cols>` class template with:
- Element-wise operations (`+`, `-`, `*`, `/`) via SFINAE
- Matrix multiplication with compile-time dimension checking
- Transpose, determinant (recursive template), inverse
- Stream insertion operator
- Explicit instantiations in `matrix.cpp` for `{float, double} × {2,3,4,5,6,7,8}×{2,3,4,5,6,7,8}` (98 instantiations)

`transforms.cpp` instantiates transform operations (rotate, scale, project) across multiple type/dimension combinations — another ~50 instantiations.

**Expected signal:**
- `math_lib` has highest `compile_time_sum_ms` among libraries
- `transforms.cpp` has highest `compile_time_ms` of any single file
- `gcc_template_instantiation_ms` dominates the GCC phase breakdown for math_lib files
- `preprocessed_bytes` is high due to expanded templates
- `compute/pipeline.cpp` inherits slow compile via `#include "math/matrix.h"`

**Exercises:** Notebook 02 (EDA: correlation between template time and compile time), Notebook 03 (critical path: math_lib likely on critical path), Notebook 06 (clustering: math_lib clusters with compute as template-heavy targets).

### 7.2 Deep Include Chains (protocol)

**What:** `protocol/connection.cpp` includes `protocol/connection.h`, which includes `serialization/encoder.h`, which includes `proto/registry.h`, which includes `generated/messages.h`, which includes `core/types.h`. Maximum depth: 5.

By contrast, `core/types.cpp` includes only `core/types.h` (depth 1).

**Expected signal:**
- `protocol/connection.cpp` has `header_max_depth = 5` (highest in the project)
- `core/types.cpp` has `header_max_depth = 1` (lowest)
- Clear correlation between `header_max_depth` and `preprocessed_bytes` across files
- `protocol` target has `header_depth_max = 5`, `header_depth_mean ≈ 3`

**Exercises:** Notebook 02 (EDA: header depth vs preprocessed size correlation), Notebook 09 (recommendations: protocol files as precompiled header candidates).

### 7.3 Codegen Cascade Cost (proto_msgs → serialization → protocol → middleware → engine → app)

**What:** The generated files in `proto_msgs` are included by `serialization/encoder.cpp`. Changes to `messages.def` trigger:
1. `proto_gen` reruns (codegen step)
2. All 4 generated files are regenerated
3. `proto_msgs`' generated .cpp files recompile
4. `serialization/encoder.cpp` recompiles (includes generated header)
5. `protocol` recompiles (depends on serialization)
6. `middleware` recompiles (depends on protocol)
7. `engine`, `app`, `test_runner` recompile (downstream)

**Expected signal:**
- High `codegen_cascade_cost` for `proto_gen`
- `proto_msgs` has moderate `codegen_time_ms` (the generation step itself)
- The transitive rebuild cost from proto_msgs is much larger than its own compile time

**Exercises:** Notebook 05 (change impact simulation), Notebook 08 (codegen analysis: cascade cost, fan-out, codegen isolation recommendation).

### 7.4 Unused Dependency (benchmark → math_lib)

**What:** `benchmark/CMakeLists.txt` contains `target_link_libraries(benchmark PRIVATE math_lib)` but `benchmark/bench_main.cpp` never `#include`s any `math/` header.

**Expected signal:**
- `benchmark → math_lib` edge exists in `edge_list.parquet` with `is_direct = true`
- But the header trees for `benchmark/bench_main.cpp` contain no path matching `math/`
- This is detectable by comparing declared link deps against actual include analysis

**Exercises:** Notebook 09 (recommendations: quick-win unused dependency removal).

### 7.5 Bridging Target / Split Candidate (middleware)

**What:** `middleware` has 8 source files spanning two functional areas:
- **Protocol-facing** (request_router, metrics_collector): include headers from `protocol/` and `serialization/`
- **Engine-facing** (service_registry, rate_limiter): include headers from `compute/`

The intra-target include graph has two clusters with minimal cross-cluster includes (only `middleware/service_registry.cpp` includes `middleware/request_router.h` for dispatching).

**Expected signal:**
- Highest betweenness centrality of any target
- Spectral partitioning (Fiedler vector) cleanly separates the two groups
- Splitting middleware into `middleware_protocol` and `middleware_compute` would reduce the coupling between communities B and C

**Exercises:** Notebook 04 (community detection: bridging target identification), Notebook 07 (spectral partitioning: clean 2-way split).

### 7.6 High Fan-Out Leaf (core)

**What:** `core` has 7 direct dependants and is a leaf node (no dependencies except `config_iface`). Every target in the project depends on it transitively.

**Expected signal:**
- `direct_dependant_count = 7` (or more, depending on exact wiring)
- `transitive_dependant_count = 13` (all other targets)
- Any change to core triggers a full rebuild
- Highest `expected_daily_cost` if it has moderate git churn

**Exercises:** Notebook 03 (critical path: core is on every path), Notebook 05 (change impact: core has highest rebuild cost), Notebook 09 (recommendations: core changes are expensive, should be stable).

### 7.7 INTERFACE_LIBRARY with No Compilation (config_iface)

**What:** Header-only interface target with no source files, only compile definitions propagated transitively.

**Expected signal:**
- `file_count = 0`, `compile_time_sum_ms = 0`
- Target exists in dependency graph but has null/zero for most metrics
- Must be handled in data cleaning (notebook 01) without being treated as an error

**Exercises:** Notebook 01 (data cleaning: missing data handling for interface libraries).

---

## 8. Synthetic Git History

A script (`tests/fixture/create_git_history.sh`) creates a series of synthetic commits that simulate realistic development patterns:

### 8.1 Commit Pattern Design

| Phase | Commits | Files Affected | Purpose |
|-------|---------|----------------|---------|
| Initial import | 1 | All authored files | Baseline |
| Core stabilisation | 3 | core/*.cpp, core/*.h | Core changes early, then stabilises |
| Protocol feature work | 8 | proto/*, serialization/*, protocol/* | Active development in protocol community (high churn) |
| Middleware refactoring | 4 | middleware/*.cpp, middleware/*.h | Moderate churn, spans both domains |
| Compute optimisation | 2 | math/transforms.cpp, compute/pipeline.cpp | Targeted changes to hot files |
| Bug fixes | 5 | Scattered (connection.cpp, scheduler.cpp, logger.cpp, engine.cpp, registry.cpp) | Spread across codebase, single-file changes |
| Logging improvements | 3 | logging/*.cpp, logging/*.h | Moderate churn in small target |

**Total: ~26 commits** over a simulated 6-month window.

### 8.2 Expected Git Metrics

| File | Expected commit_count | Expected churn | Notes |
|------|----------------------|----------------|-------|
| `proto/registry.cpp` | 6 | High | Hotspot (feature work + bug fixes) |
| `serialization/encoder.cpp` | 5 | High | Active development |
| `middleware/request_router.cpp` | 4 | Moderate | Refactoring |
| `core/types.cpp` | 2 | Low | Stable after early changes |
| `math/transforms.cpp` | 3 | Moderate | Optimisation rounds |
| `benchmark/bench_main.cpp` | 1 | Zero after initial | Rarely touched |
| Generated files | 0 | 0 | Not in git |

### 8.3 Author Diversity

Three synthetic authors to exercise `git_distinct_authors`:
- `alice` — core and platform work
- `bob` — protocol and codegen work
- `charlie` — middleware and engine work

---

## 9. Directory Layout

```
tests/fixture/
├── CMakeLists.txt                  # Top-level CMake, minimum_required(3.16)
├── create_git_history.sh           # Script to create synthetic git commits
├── src/
│   ├── core/
│   │   ├── CMakeLists.txt
│   │   ├── types.h
│   │   ├── types.cpp
│   │   ├── assert.h
│   │   ├── assert.cpp
│   │   ├── string_utils.h
│   │   └── string_utils.cpp
│   ├── logging/
│   │   ├── CMakeLists.txt
│   │   ├── logger.h
│   │   ├── logger.cpp
│   │   ├── sink.h
│   │   └── sink.cpp
│   ├── platform/
│   │   ├── CMakeLists.txt
│   │   ├── filesystem.h
│   │   ├── filesystem.cpp
│   │   ├── thread_pool.h
│   │   └── thread_pool.cpp
│   ├── math/
│   │   ├── CMakeLists.txt          # math_lib (STATIC) + math_objs (OBJECT)
│   │   ├── matrix.h
│   │   ├── matrix.cpp
│   │   ├── vector.h
│   │   ├── vector.cpp
│   │   ├── transforms.h
│   │   ├── transforms.cpp
│   │   └── helpers/
│   │       ├── interpolation.h
│   │       ├── interpolation.cpp
│   │       ├── constants.h
│   │       └── constants.cpp
│   ├── codegen/
│   │   ├── CMakeLists.txt          # proto_gen (UTILITY) + proto_msgs (STATIC)
│   │   ├── generate_messages.py
│   │   ├── messages.def
│   │   └── proto/
│   │       ├── registry.h
│   │       ├── registry.cpp
│   │       ├── validation.h
│   │       └── validation.cpp
│   ├── serialization/
│   │   ├── CMakeLists.txt
│   │   ├── encoder.h
│   │   ├── encoder.cpp
│   │   ├── decoder.h
│   │   └── decoder.cpp
│   ├── protocol/
│   │   ├── CMakeLists.txt
│   │   ├── handler.h
│   │   ├── handler.cpp
│   │   ├── connection.h
│   │   └── connection.cpp
│   ├── compute/
│   │   ├── CMakeLists.txt
│   │   ├── pipeline.h
│   │   ├── pipeline.cpp
│   │   ├── scheduler.h
│   │   └── scheduler.cpp
│   ├── middleware/
│   │   ├── CMakeLists.txt
│   │   ├── request_router.h
│   │   ├── request_router.cpp
│   │   ├── metrics_collector.h
│   │   ├── metrics_collector.cpp
│   │   ├── service_registry.h
│   │   ├── service_registry.cpp
│   │   ├── rate_limiter.h
│   │   └── rate_limiter.cpp
│   ├── engine/
│   │   ├── CMakeLists.txt
│   │   ├── engine.h
│   │   └── engine.cpp
│   ├── plugin_api/
│   │   ├── CMakeLists.txt          # SHARED_LIBRARY
│   │   ├── plugin_api.h
│   │   ├── plugin_api.cpp
│   │   ├── plugin_registry.h
│   │   └── plugin_registry.cpp
│   ├── app/
│   │   ├── CMakeLists.txt
│   │   └── main.cpp
│   ├── test/
│   │   ├── CMakeLists.txt
│   │   ├── test_main.cpp
│   │   ├── test_protocol.cpp
│   │   └── test_compute.cpp
│   └── benchmark/
│       ├── CMakeLists.txt
│       └── bench_main.cpp
└── config_iface/
    └── CMakeLists.txt              # INTERFACE library, no sources
```

---

## 10. Collection Step Coverage Matrix

Verification that every collection step and every analysis notebook gets meaningful exercise from this fixture.

### 10.1 Collection Steps

| Collection Step | What it collects from the fixture | Verification |
|---|---|---|
| **01 cmake_file_api** | 17 targets, 63 files (59 authored + 4 generated), ~35 dependency edges, `isGenerated` flags on 4 files, compile groups with flags, all target types (STATIC, SHARED, OBJECT, EXECUTABLE, UTILITY, INTERFACE), `objectDependencies[]` for math_objs, `linkLibraries[]` vs `dependencies[]` for direct vs transitive classification | Assert target count, file count, generated file count, edge count, presence of each target type (STATIC_LIBRARY, SHARED_LIBRARY, OBJECT_LIBRARY, EXECUTABLE, UTILITY, INTERFACE_LIBRARY) |
| **02 git_history** | 26 commits across ~59 authored files, 3 authors, varying churn per file | Assert commit counts for known hotspot files, zero history for generated files |
| **03 instrumented_build** | stderr logs for all compiled .cpp files, `-ftime-report` with measurably different template instantiation times, `-H` output with varying depths 1-5 | Assert log file count, parse a known log for ftime-report fields, verify max include depth |
| **04 post_build_metrics** | Object files with sizes for all compiled sources, SLOC for all 63 files including generated, `is_generated` flag carried through | Assert object count, verify generated files have SLOC > 0, verify source_size_bytes |
| **05 preprocessed_size** | Preprocessed bytes for all compiled files, generated files should have higher expansion ratio | Assert all files have preprocessed_bytes > 0, generated files > authored files on average |
| **06 ninja_log** | Compile steps for all .cpp files, 1 codegen step (proto_gen), archive steps (STATIC_LIBRARY targets), link steps (SHARED_LIBRARY + EXECUTABLE targets), no archive/link for OBJECT_LIBRARY, start/end times for parallelism analysis | Assert step type counts, verify codegen step exists, verify SHARED link is distinct from STATIC archive, verify OBJECT_LIBRARY has compile steps but no archive/link |

### 10.2 Analysis Notebooks

| Notebook | Pattern exercised by fixture |
|---|---|
| **01 Data Cleaning** | config_iface has zero compile time (missing data). Generated files have zero git history. All paths should align. |
| **02 EDA** | math_lib files are outliers in compile time. Skewed distributions. Template time vs compile time correlation. Codegen vs authored distributions differ. |
| **03 Critical Path** | math_lib or proto_gen→proto_msgs chain likely on critical path. Codegen time adds to critical path weight. Slack is zero for critical targets. Parallelism analysis from ninja log shows concurrent compile steps. |
| **04 Community Detection** | Three communities (core/platform, protocol/codegen, engine/compute). middleware is the bridging target. Codegen targets cluster in protocol community. |
| **05 Change Impact** | proto/registry.cpp is a hotspot. core has highest transitive rebuild cost. Codegen cascade from proto_gen is expensive. |
| **06 Clustering** | math_lib + compute cluster together (template-heavy). core + logging + platform cluster (small, fast). proto_msgs is an outlier (mixed codegen). |
| **07 Spectral Partitioning** | middleware splits cleanly into protocol-facing and engine-facing groups. Generated files in proto_msgs stay together (constraint). |
| **08 Codegen Analysis** | proto_gen timing in ninja log. 4 generated files, ~0.5 codegen ratio in proto_msgs. Cascade through serialization→protocol→middleware. Generated files have higher preprocessed_bytes. |
| **09 Recommendations** | Unused dep (benchmark→math_lib). Split middleware. Codegen isolation for proto_msgs. High header depth in protocol (PCH candidate). math_lib on critical path (template optimisation candidate). |

---

## 11. Test Strategy

### 11.1 Unit Tests (pytest)

Tests in `tests/test_collection/` validate each collection script against the fixture:

```python
# tests/conftest.py
@pytest.fixture(scope="session")
def fixture_build(tmp_path_factory):
    """Configure and build the fixture project once per test session."""
    build_dir = tmp_path_factory.mktemp("build")
    source_dir = Path(__file__).parent / "fixture"
    # Create File API query, configure, build
    # Return paths to build_dir, raw_data_dir, etc.
```

| Test Module | Assertions |
|---|---|
| `test_cmake_file_api.py` | Target count == 17. File count == 63. Generated file count == 4. Edge count within expected range. All 6 target types present (STATIC_LIBRARY, SHARED_LIBRARY, OBJECT_LIBRARY, EXECUTABLE, UTILITY, INTERFACE_LIBRARY). config_iface has no sources. proto_msgs has isGenerated files. Direct vs transitive deps correctly classified. math_objs appears in `objectDependencies[]` of math_lib. plugin_api has `nameOnDisk` ending in `.so`/`.dylib`. |
| `test_git_history.py` | Known hotspot files have commit_count > 3. Generated files have 0 commits. Author count == 3. Summary stats match detailed log. |
| `test_instrumented_build.py` | All expected stderr log files exist. Each log contains `-ftime-report` section. Each log contains `-H` section. math/transforms.cpp has higher template_instantiation time than core/types.cpp. |
| `test_post_build_metrics.py` | All compiled files have object file entries. All files have SLOC entries. Generated files have `is_generated == True`. |
| `test_preprocessed_size.py` | All compiled files have preprocessed_bytes > 0. Generated files have higher mean preprocessed_bytes than authored files. |
| `test_ninja_log.py` | Step type counts match expectations. Codegen step present. All targets have at least one log entry. Start/end times are monotonically non-decreasing within each step. plugin_api has a link step (not archive). math_objs has compile steps but no archive or link step. STATIC_LIBRARY targets have archive steps. |

### 11.2 Integration Tests

| Test | What it validates |
|---|---|
| `test_consolidation.py` | File metrics parquet has expected columns and row count. Target metrics parquet has expected columns and target count. Edge list has expected edges. Derived columns (expansion_ratio, compile_rate) are computed correctly. |
| `test_graph.py` | Graph has correct node and edge count. Critical path includes expected targets. Betweenness centrality ranks middleware highest. Topological depth is correct for known targets. |

### 11.3 Fixture Build Time Target

The fixture is designed to compile in under 30 seconds on a modern machine (4+ cores). The template bloat in math_lib adds a few seconds of real compile time, but this is intentional — it produces measurable signal in the timing data.

---

## 12. Implementation Notes

### 12.1 Template Bloat Implementation

The key to making `math_lib` measurably slow without being _too_ slow is controlling the number of explicit instantiations. Start with 2×2 through 4×4 for float and double (24 instantiations). If the signal is too weak (compile times don't differ enough from simple files), increase to 8×8 (98 instantiations). The goal is a 5-10× compile time difference between `math/transforms.cpp` and `core/types.cpp`.

### 12.2 Generated Code Verbosity

The Python generator should produce approximately 800-1200 lines total across the 4 generated files for 3 messages. Key techniques for inflating preprocessed size:
- Include standard headers individually rather than via a common precompiled header
- Use `std::ostringstream` for serialization (pulls in `<sstream>`, `<iostream>`, `<string>`)
- Include `<algorithm>`, `<functional>`, `<memory>` whether or not they're used
- Generate defensive `#ifndef` guards that don't use `#pragma once`

### 12.3 Header Chain Construction

The depth-5 chain through `protocol/connection.h`:
```
protocol/connection.h
  └── serialization/encoder.h
        └── proto/registry.h
              └── generated/messages.h
                    └── core/types.h
```

Each header in the chain includes the next, plus some of its own standard library headers. This ensures the `-H` output shows increasing depth and the `header_tree` data contains a meaningful multi-level structure.

### 12.4 Middleware File-Level Include Structure

For spectral partitioning to work, the intra-target include graph must have two weakly-connected clusters:

```
request_router.h ←──── request_router.cpp
       ↑
metrics_collector.h ←── metrics_collector.cpp
       (both include protocol/ and serialization/ headers)

service_registry.h ←── service_registry.cpp ──→ request_router.h (weak cross-link)
       ↑
rate_limiter.h ←──── rate_limiter.cpp
       (both include compute/ headers)
```

The single cross-link (`service_registry.cpp` includes `request_router.h` for dispatching) is the edge that the Fiedler vector will cut.
