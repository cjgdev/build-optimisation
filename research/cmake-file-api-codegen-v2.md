# CMake File API and codemodel-v2: a complete technical reference

The CMake File API, introduced in **CMake 3.14**, provides a file-based mechanism for external tools to extract rich, structured semantic information about CMake-generated build systems — including targets, dependencies, source files, compile flags, include paths, and preprocessor definitions. It supersedes the deprecated cmake-server mode (removed in CMake 3.20) and offers strictly more structured data than `compile_commands.json`. This reference covers the full query/reply lifecycle, the complete codemodel-v2 JSON schema, and practical techniques for walking the data to build project models programmatically.

The File API works through a simple contract: a client writes query files into a well-known directory before running `cmake`, and CMake writes structured JSON reply files after generation completes. The codemodel-v2 object kind is the most important reply — it encodes the entire project structure with configurations, directories, projects, targets, source files, compile settings, and inter-target dependencies. Every major C++ IDE (VS Code CMake Tools, CLion, Qt Creator, Kate) relies on this mechanism for IntelliSense, project navigation, and build management.

---

## How the query/reply mechanism works

The File API lives under `<build>/.cmake/api/v1/` with two subdirectories: `query/` (written by clients) and `reply/` (written by CMake). The query files must exist **before** running `cmake`; CMake reads them during generation and produces the corresponding replies. Three query styles are supported, in ascending order of sophistication.

**Shared stateless queries** are the simplest. Create an empty file named after the desired object kind and version directly in the query directory:

```
<build>/.cmake/api/v1/query/codemodel-v2
```

This requests codemodel version 2. The file must be empty. Because it lives in a shared namespace, no single tool owns it — coordination is required if multiple tools use this style.

**Client stateless queries** add ownership by nesting under a client-named subdirectory. A tool called `myide` would create:

```
<build>/.cmake/api/v1/query/client-myide/codemodel-v2
```

Each client owns its subdirectory and can freely add or remove query files. This is the style most IDEs use.

**Client stateful queries** use a `query.json` file for richer version negotiation:

```json
{
  "requests": [
    { "kind": "codemodel", "version": { "major": 2, "minor": 0 } },
    { "kind": "cache", "version": 2 },
    { "kind": "toolchains", "version": 1 }
  ],
  "client": { "tool": "my-analyzer", "version": "1.0" }
}
```

CMake selects the first version it recognizes for each kind and responds with the highest known minor version for that major version. The optional `client` object is opaque to CMake and passed through verbatim to the reply — useful for tools that need to correlate requests with responses.

After `cmake` generates the build system, it writes reply files into `<build>/.cmake/api/v1/reply/`. The entry point is always an **index file** named `index-<unspecified>.json`. If multiple index files exist (from interrupted runs), the one with the **lexicographically largest filename** is current. The index file structure:

```json
{
  "cmake": {
    "version": {
      "major": 3, "minor": 28, "patch": 0,
      "string": "3.28.0", "isDirty": false
    },
    "paths": {
      "cmake": "/usr/bin/cmake",
      "ctest": "/usr/bin/ctest",
      "cpack": "/usr/bin/cpack",
      "root": "/usr/share/cmake-3.28"
    },
    "generator": {
      "name": "Unix Makefiles",
      "multiConfig": false
    }
  },
  "objects": [
    {
      "kind": "codemodel",
      "version": { "major": 2, "minor": 6 },
      "jsonFile": "codemodel-v2-abc123def456.json"
    },
    {
      "kind": "toolchains",
      "version": { "major": 1, "minor": 0 },
      "jsonFile": "toolchains-v1-789ghi.json"
    }
  ],
  "reply": {
    "client-myide": {
      "codemodel-v2": {
        "kind": "codemodel",
        "version": { "major": 2, "minor": 6 },
        "jsonFile": "codemodel-v2-abc123def456.json"
      }
    }
  }
}
```

Every `jsonFile` path is **relative to the reply directory** (i.e., relative to the index file's location). The `objects` array lists all generated reply objects; the `reply` object maps query files to their specific responses, organized by client name.

---

## The codemodel-v2 top-level structure

The codemodel-v2 JSON file provides a hierarchical view of the entire project. Its top-level structure:

```json
{
  "kind": "codemodel",
  "version": { "major": 2, "minor": 6 },
  "paths": {
    "source": "/home/user/project",
    "build": "/home/user/project/build"
  },
  "configurations": [ ... ]
}
```

The `paths` object gives absolute paths (always forward slashes) to the top-level source and build directories. All relative paths elsewhere in the reply are relative to these roots. The **`configurations` array** contains one entry per build configuration — a single entry for single-config generators like Unix Makefiles (the entry's `name` is the value of `CMAKE_BUILD_TYPE`), or multiple entries for multi-config generators like Visual Studio or Ninja Multi-Config.

Each configuration entry contains three parallel arrays — `directories`, `projects`, and `targets` — cross-referenced by index:

```json
{
  "name": "Release",
  "directories": [
    {
      "source": ".",
      "build": ".",
      "childIndexes": [1, 2],
      "projectIndex": 0,
      "targetIndexes": [0, 1],
      "hasInstallRule": true,
      "minimumCMakeVersion": { "string": "3.16" },
      "jsonFile": "directory-.-Release-abc123.json"
    },
    {
      "source": "lib",
      "build": "lib",
      "parentIndex": 0,
      "projectIndex": 0,
      "targetIndexes": [2],
      "minimumCMakeVersion": { "string": "3.16" }
    }
  ],
  "projects": [
    {
      "name": "MyProject",
      "directoryIndexes": [0, 1, 2],
      "targetIndexes": [0, 1, 2]
    }
  ],
  "targets": [
    {
      "name": "MyApp",
      "id": "MyApp::@6890427a1f51a3e7e1df",
      "directoryIndex": 0,
      "projectIndex": 0,
      "jsonFile": "target-MyApp-Release-abc123.json"
    },
    {
      "name": "MyLib",
      "id": "MyLib::@6890427a1f51a3e7e1df",
      "directoryIndex": 1,
      "projectIndex": 0,
      "jsonFile": "target-MyLib-Release-def456.json"
    }
  ]
}
```

**Directories** form a tree via `parentIndex` and `childIndexes`, mirroring the `add_subdirectory()` hierarchy. Each directory knows which project it belongs to (`projectIndex`) and which targets it directly contains (`targetIndexes`). **Projects** (from `project()` commands) reference their constituent directories and targets. **Targets** are the key entries — each has a `name`, a unique `id` string, and a `jsonFile` pointing to a separate target object file with full details.

The `id` field follows the format `<target-name>::@<hex-hash>` where the hash incorporates the directory path to ensure uniqueness when identically-named targets exist in different directories. While the documentation states the format is "unspecified and should not be interpreted," this pattern is stable across all observed versions.

Starting with **codemodel 2.9** (CMake 4.2), an additional `abstractTargets` array appears alongside `targets`. This array contains imported targets and non-build-participating interface libraries that were previously excluded entirely from the reply. Each abstract target has the same fields as regular targets plus an `abstract: true` flag in its target object file.

---

## Enumerating targets and understanding their types

To enumerate all targets, iterate `configurations[n].targets`. Each entry provides the target `name`, `id`, `directoryIndex`, `projectIndex`, and `jsonFile`. Load each `jsonFile` to access the full target object. The **`type`** field in the target object identifies what kind of build artifact the target produces:

- **`EXECUTABLE`** — from `add_executable()`; produces a runnable binary
- **`STATIC_LIBRARY`** — from `add_library(... STATIC)`; produces a `.a`/`.lib` archive
- **`SHARED_LIBRARY`** — from `add_library(... SHARED)`; produces a `.so`/`.dylib`/`.dll`
- **`MODULE_LIBRARY`** — from `add_library(... MODULE)`; produces a loadable plugin
- **`OBJECT_LIBRARY`** — from `add_library(... OBJECT)`; produces individual `.o` files, no linked artifact
- **`INTERFACE_LIBRARY`** — from `add_library(... INTERFACE)`; header-only, no build artifacts
- **`UTILITY`** — from `add_custom_target()`; no compilation, just runs commands

Generator-provided targets like `ALL_BUILD`, `INSTALL`, and `ZERO_CHECK` have `"isGeneratorProvided": true` and should typically be filtered out of user-facing UIs. The `nameOnDisk` field gives the actual output filename (e.g., `"libMyLib.so.1.2.3"`), and the `artifacts` array lists all consumable output file paths.

---

## Inter-target dependencies and the dependency graph

Each target object contains an optional **`dependencies` array** listing every target that must build before it. This includes both direct dependencies (from `target_link_libraries()`, `add_dependencies()`) and transitive dependencies propagated through the build graph:

```json
"dependencies": [
  {
    "id": "MyLib::@6890427a1f51a3e7e1df",
    "backtrace": 3
  },
  {
    "id": "GeneratedHeaders::@a1b2c3d4e5f60000"
  }
]
```

Each entry's `id` matches the `id` field of another target in the codemodel's `targets` array. The optional `backtrace` is an index into the target's `backtraceGraph` that traces back to the CMake command creating the dependency (e.g., `target_link_libraries()` or `add_dependencies()`). To resolve a dependency, scan the codemodel's `targets` array for a matching `id`, then load that target's `jsonFile`.

**Building a complete dependency graph** requires loading all target objects and constructing an adjacency list keyed by `id`. Here is the algorithmic approach in pseudocode:

```python
# 1. Load codemodel, pick configuration
# 2. Build id→target lookup
targets = {}
for entry in config["targets"]:
    target_obj = load_json(reply_dir / entry["jsonFile"])
    targets[target_obj["id"]] = target_obj

# 3. Build adjacency list
for tid, target in targets.items():
    for dep in target.get("dependencies", []):
        dep_target = targets[dep["id"]]
        # tid depends on dep["id"]
```

Starting with **codemodel 2.9**, richer dependency semantics are available through dedicated arrays: `linkLibraries` (direct link dependencies from `LINK_LIBRARIES`), `compileDependencies` (from `COMPILE_ONLY` link items), `objectDependencies` (from `$<TARGET_OBJECTS:...>`), and `orderDependencies` (from `add_dependencies()`). Each entry has either an `id` (referencing a CMake target) or a `fragment` (a raw library flag like `-lpthread`).

---

## Source files per target and compile groups

The **`sources` array** in each target object lists every source file associated with the target. Each entry contains:

```json
"sources": [
  {
    "path": "src/main.cpp",
    "compileGroupIndex": 0,
    "sourceGroupIndex": 1,
    "backtrace": 1
  },
  {
    "path": "include/config.h",
    "sourceGroupIndex": 0,
    "backtrace": 2
  },
  {
    "path": "/home/user/project/build/generated/proto.pb.cc",
    "compileGroupIndex": 0,
    "sourceGroupIndex": 1,
    "isGenerated": true,
    "backtrace": 3
  }
]
```

The critical distinction: **compiled sources have a `compileGroupIndex`**; non-compiled files (headers, resources) do not. The `compileGroupIndex` is a 0-based index into the target's `compileGroups` array, linking each source to its exact compile settings. The `sourceGroupIndex` points into `sourceGroups`, which organizes files by logical grouping (typically `"Source Files"` and `"Header Files"`).

The `path` field is relative to the top-level source directory if the file resides within it, otherwise absolute. Generated files in the build directory typically appear with absolute paths. The `backtrace` traces back to the command that added the source (e.g., `add_executable()`, `target_sources()`).

The **`sourceGroups` array** provides a logical grouping for IDE display:

```json
"sourceGroups": [
  { "name": "Header Files", "sourceIndexes": [1] },
  { "name": "Source Files", "sourceIndexes": [0, 2] }
]
```

---

## Generated files and the limits of custom command visibility

The `isGenerated` boolean on source entries indicates files with CMake's `GENERATED` source file property set. This property is applied automatically to files listed as `OUTPUT` of `add_custom_command()`, as `BYPRODUCTS` of custom commands or targets, and by `file(GENERATE ...)`. Notably, `configure_file()` outputs do NOT automatically get this property (they are created at configure time and exist before the build).

**A critical limitation**: the File API does **not** expose `add_custom_command()` details — there is no direct link from a generated source to the command, working directory, or dependencies that produce it. The `backtrace` on a generated source traces to where the file was *added to the target* (e.g., `target_sources()`), not to the `add_custom_command()` that creates it. To discover what generates a specific file, you must either parse the native build system files (e.g., `build.ninja`, Makefiles) or maintain that mapping in your own CMake infrastructure.

This means tools that need to understand generation pipelines — such as build system analyzers that want to show "file X is produced by command Y" — cannot get this information from the File API alone. The workaround is to combine File API data with `compile_commands.json` or native build file parsing.

---

## Extracting complete compiler flags, includes, and defines

The **`compileGroups` array** is the richest source of compilation information. Each compile group aggregates sources that share identical compile settings:

```json
"compileGroups": [
  {
    "sourceIndexes": [0, 2, 3],
    "language": "CXX",
    "languageStandard": {
      "standard": "17",
      "backtraces": [5]
    },
    "compileCommandFragments": [
      { "fragment": "-O2 " },
      { "fragment": "-Wall " },
      { "fragment": "-fPIC " },
      { "fragment": "-std=gnu++17" }
    ],
    "includes": [
      { "path": "/home/user/project/include", "backtrace": 3 },
      { "path": "/usr/include/protobuf", "isSystem": true, "backtrace": 4 }
    ],
    "defines": [
      { "define": "NDEBUG", "backtrace": 6 },
      { "define": "PROJECT_VERSION=\"1.2.3\"", "backtrace": 7 }
    ],
    "precompileHeaders": [
      { "header": "/home/user/project/build/CMakeFiles/MyApp.dir/cmake_pch.hxx", "backtrace": 8 }
    ],
    "sysroot": { "path": "/opt/cross/sysroot" }
  }
]
```

Each `compileCommandFragments` entry contains a `fragment` string — a single flag or small group of flags in the build system's native shell encoding. **Concatenating all fragments in order reconstructs the full compiler flags.** Note that some fragments may include trailing whitespace. An optional `backtrace` on each fragment (available from codemodel 2.6+) traces back to the CMake command that added the flag.

The `includes` array provides each include directory with its `path`, an optional `isSystem` boolean (corresponding to `-isystem` vs. `-I`), and an optional `backtrace` to the `target_include_directories()` or `include_directories()` call. The `defines` array lists preprocessor definitions in `NAME` or `NAME=VALUE` format, also with optional backtraces.

**The compiler executable path itself is not in compileGroups.** To get it, request the `toolchains` object kind (available since CMake 3.20), which reports `compiler.path`, `compiler.id` (e.g., `"GNU"`, `"Clang"`), `compiler.version`, and implicit include/link directories. To assemble a complete compile command for a source file:

1. Get the compiler path from `toolchains` for the matching `language`
2. Concatenate all `compileCommandFragments` fragments
3. Add `-I<path>` or `-isystem <path>` for each entry in `includes`
4. Add `-D<define>` for each entry in `defines`
5. Append the source file path

This reconstruction is an approximation — `compile_commands.json` gives the exact command. However, the File API provides **structured** data (separate includes, defines, flags with backtraces) that `compile_commands.json` does not. The File API also works with **all generators** (including Visual Studio and Xcode), while `compile_commands.json` is limited to Makefile and Ninja generators.

| Aspect | compile_commands.json | File API codemodel-v2 |
|--------|----------------------|----------------------|
| Generator support | Makefile/Ninja only | All generators |
| Data structure | Flat list, monolithic command string | Hierarchical with separate fields |
| Target awareness | None | Full target model with dependencies |
| Include paths | Embedded in command, must be parsed | Separate `includes` array with `isSystem` |
| Preprocessor defines | Embedded in command | Separate `defines` array |
| Backtraces | None | Per-flag trace to CMakeLists.txt |
| Multi-config | Problematic (mixed configs) | Separate `configurations` entries |

---

## Walking the JSON: a complete concrete example

Consider a project with an executable `MyApp` that depends on a static library `MyLib`. Here is the complete walkthrough.

**Step 1: Create query files and run cmake.**

```bash
mkdir -p build/.cmake/api/v1/query/client-analyzer
touch build/.cmake/api/v1/query/client-analyzer/codemodel-v2
touch build/.cmake/api/v1/query/client-analyzer/toolchains-v1
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
```

**Step 2: Find and parse the index file.**

Read `build/.cmake/api/v1/reply/index-2024-01-15T10-30-00-0000.json`. Locate the codemodel-v2 entry in the `objects` array:

```json
{ "kind": "codemodel", "version": {"major":2,"minor":6}, "jsonFile": "codemodel-v2-d4e5f6a7b8c9.json" }
```

**Step 3: Parse the codemodel file.** Load `reply/codemodel-v2-d4e5f6a7b8c9.json`:

```json
{
  "kind": "codemodel",
  "version": { "major": 2, "minor": 6 },
  "paths": { "source": "/home/user/project", "build": "/home/user/project/build" },
  "configurations": [{
    "name": "Release",
    "directories": [
      { "source": ".", "build": ".", "childIndexes": [1], "projectIndex": 0, "targetIndexes": [0] },
      { "source": "lib", "build": "lib", "parentIndex": 0, "projectIndex": 0, "targetIndexes": [1] }
    ],
    "projects": [
      { "name": "MyProject", "directoryIndexes": [0, 1], "targetIndexes": [0, 1] }
    ],
    "targets": [
      { "name": "MyApp", "id": "MyApp::@6890427a1f51a3e7e1df", "directoryIndex": 0, "projectIndex": 0, "jsonFile": "target-MyApp-Release-abc123.json" },
      { "name": "MyLib", "id": "MyLib::@77a8b9c0d1e2f3045678", "directoryIndex": 1, "projectIndex": 0, "jsonFile": "target-MyLib-Release-def456.json" }
    ]
  }]
}
```

**Step 4: Load target object files.** Load `reply/target-MyApp-Release-abc123.json`:

```json
{
  "name": "MyApp",
  "id": "MyApp::@6890427a1f51a3e7e1df",
  "type": "EXECUTABLE",
  "backtrace": 1,
  "paths": { "source": ".", "build": "." },
  "nameOnDisk": "MyApp",
  "artifacts": [{ "path": "MyApp" }],
  "sources": [
    { "path": "src/main.cpp", "compileGroupIndex": 0, "sourceGroupIndex": 0, "backtrace": 1 },
    { "path": "src/app.cpp", "compileGroupIndex": 0, "sourceGroupIndex": 0, "backtrace": 1 },
    { "path": "src/app.h", "sourceGroupIndex": 1, "backtrace": 1 }
  ],
  "sourceGroups": [
    { "name": "Source Files", "sourceIndexes": [0, 1] },
    { "name": "Header Files", "sourceIndexes": [2] }
  ],
  "compileGroups": [{
    "sourceIndexes": [0, 1],
    "language": "CXX",
    "languageStandard": { "standard": "17", "backtraces": [3] },
    "compileCommandFragments": [
      { "fragment": "-O2 " },
      { "fragment": "-DNDEBUG " },
      { "fragment": "-std=gnu++17" }
    ],
    "includes": [
      { "path": "/home/user/project/include", "backtrace": 2 },
      { "path": "/home/user/project/lib/include", "backtrace": 4 }
    ],
    "defines": [
      { "define": "NDEBUG" },
      { "define": "APP_VERSION=\"1.0\"", "backtrace": 5 }
    ]
  }],
  "dependencies": [
    { "id": "MyLib::@77a8b9c0d1e2f3045678", "backtrace": 6 }
  ],
  "link": {
    "language": "CXX",
    "commandFragments": [
      { "fragment": "-O2 -DNDEBUG", "role": "flags" },
      { "fragment": "lib/libMyLib.a", "role": "libraries", "backtrace": 6 }
    ]
  },
  "backtraceGraph": {
    "commands": ["add_executable", "target_include_directories", "target_compile_definitions", "target_link_libraries"],
    "files": ["CMakeLists.txt"],
    "nodes": [
      { "file": 0 },
      { "command": 0, "file": 0, "line": 10, "parent": 0 },
      { "command": 1, "file": 0, "line": 12, "parent": 0 },
      { "command": 1, "file": 0, "line": 13, "parent": 0 },
      { "command": 2, "file": 0, "line": 14, "parent": 0 },
      { "command": 2, "file": 0, "line": 15, "parent": 0 },
      { "command": 3, "file": 0, "line": 16, "parent": 0 }
    ]
  }
}
```

**Step 5: Interpret the result.** From this data we can conclude: target `MyApp` is an executable that compiles `src/main.cpp` and `src/app.cpp` with C++17, flags `-O2 -DNDEBUG`, two include directories, and two preprocessor definitions. It depends on `MyLib` (resolved via the matching `id`), and links against `lib/libMyLib.a`. Backtrace node 6 traces the dependency to `target_link_libraries()` at `CMakeLists.txt` line 16.

---

## The backtraceGraph: tracing definitions back to CMakeLists.txt

The `backtraceGraph` object appears in every target and directory object. It is a compact directed acyclic graph encoding all CMake call stacks relevant to that object:

```json
"backtraceGraph": {
  "commands": ["add_library", "target_sources", "target_include_directories"],
  "files": ["lib/CMakeLists.txt", "cmake/helpers.cmake"],
  "nodes": [
    { "file": 0 },
    { "command": 0, "file": 0, "line": 5, "parent": 0 },
    { "command": 1, "file": 0, "line": 12, "parent": 0 },
    { "command": 2, "file": 1, "line": 3, "parent": 2 }
  ]
}
```

The `commands` and `files` arrays are deduplicated string pools. Each `nodes` entry has a required `file` index, and optional `line` (1-based), `command` index, and `parent` node index. **Root nodes** (typically index 0) represent a CMakeLists.txt file with no command — they are the bottom of the call stack. Nodes without a `parent` field are stack roots.

To reconstruct a full backtrace from any `backtrace` integer found on sources, includes, defines, or dependencies: look up `nodes[backtrace]`, read its command/file/line, then follow `parent` recursively until reaching a root. In the example above, node 3 represents `target_include_directories` at `cmake/helpers.cmake` line 3, called from node 2 (`target_sources` at `lib/CMakeLists.txt` line 12). IDEs use this for "go to definition" — clicking an include directory shows exactly which `target_include_directories()` call added it and from which file.

---

## How downstream tools consume the File API

**VS Code CMake Tools** (`ms-vscode.cmake-tools`) was the first major IDE extension to adopt the File API. Its `CMakeFileApiDriver` creates client stateless query files requesting `codemodel-v2`, runs cmake, then parses the reply to populate IntelliSense (feeding `compileGroups` data to the C/C++ extension) and the project outline. It selects the File API automatically when CMake ≥ 3.14 is detected. A notable early bug: the extension performed strict version checking (`== 2.0`) rather than checking `major == 2`, causing warnings when CMake 3.18 bumped the minor version to 2.1.

**CLion** uses the File API internally to support all generator types (Ninja, Makefiles, Xcode, Visual Studio). Its integration is closed-source but consumes the same JSON structures. **Qt Creator** has an open-source File API parser (`fileapiparser.cpp`, ~940 lines of C++/Qt) in the `cmakeprojectmanager2` plugin that demonstrates robust error handling for malformed backtraces and missing fields. **Kate** (KDE) also implements File API parsing for code navigation.

Several libraries simplify programmatic access. The **Python `cmake-file-api` package** (PyPI) provides a high-level interface:

```python
from cmake_file_api import CMakeProject, ObjectKind

project = CMakeProject(build_path, source_path, api_version=1)
project.cmake_file_api.instrument_all()
project.configure(quiet=True)
results = project.cmake_file_api.inspect_all()
codemodel = results[ObjectKind.CODEMODEL][2]

for target in codemodel.configurations[0].targets:
    deps = [d.target.name for d in target.target.dependencies]
    print(f"{target.name} depends on: {deps}")
```

The **Rust `cmake-file-api` crate** provides typed deserialization. Both libraries follow the same core algorithm: write query → run cmake → glob for `index-*.json` → parse objects → follow `jsonFile` references.

The standard parsing algorithm for any custom tool is:

1. Glob `reply/index-*.json`, select the lexicographically last filename
2. Parse the index, find the codemodel-v2 entry in `objects`
3. Load the codemodel JSON via its `jsonFile` path (relative to `reply/`)
4. Select the desired configuration from `configurations`
5. For each target in `targets`, load its `jsonFile` to get the full target object
6. Cross-reference `dependencies[].id` against target `id` fields to build the dependency graph
7. Iterate `sources` and `compileGroups` to extract per-file compilation information

---

## Version history and compatibility across CMake releases

The File API was introduced in **CMake 3.14** (March 2019) with codemodel version **2.0**. Version 1 was intentionally skipped to avoid confusion with the cmake-server protocol. The cmake-server mode was deprecated in CMake 3.15 and removed entirely in CMake 3.20. The codemodel schema has evolved through backward-compatible minor version bumps:

| Codemodel version | CMake release | Key additions |
|---|---|---|
| **2.0** | 3.14 | Initial release: targets, directories, projects, compileGroups, backtraceGraph, dependencies |
| **2.1** | 3.18 | `precompileHeaders` array in compileGroups |
| **2.2** | 3.19 | `languageStandard` object in compileGroups (`standard`, `backtraces`) |
| **2.3** | 3.21 | Directory object kind (installers); `jsonFile` on directory entries |
| **2.4** | 3.23 | `fileSet` installer type with fileSetName/fileSetType |
| **2.5** | 3.26 | `fileSets` on targets, `fileSetIndex` on sources, `cxxModuleBmi` installer |
| **2.6** | 3.27 | `frameworks` in compileGroups (Apple); `cmake_file_api()` CMake command |
| **2.7** | 3.29 | `launchers` on targets (CROSSCOMPILING_EMULATOR, TEST_LAUNCHER) |
| **2.8** | 4.0 | `debugger` on targets (workingDirectory) |
| **2.9** | 4.2 | Major expansion: `abstractTargets`, `imported`/`abstract`/`symbolic` flags, `UNKNOWN_LIBRARY` type, `linkLibraries`, `interfaceLinkLibraries`, `compileDependencies`, `objectDependencies`, `orderDependencies`, `codemodelVersion` field |
| **2.10** | 4.3 | `interfaceSources` array, `interfaceSourceIndexes` in sourceGroups |

**Compatibility best practice**: clients should check `version.major == 2` and tolerate unknown fields from higher minor versions. Never perform strict equality checks on minor versions — this is the exact bug that caused VS Code CMake Tools to emit warnings when CMake bumped from 2.0 to 2.1. CMake guarantees that minor version increments are additive only.

Starting with **CMake 3.27**, projects can submit queries from within CMakeLists.txt using `cmake_file_api(QUERY API_VERSION 1 CODEMODEL 2.3 ...)`, enabling build-time self-introspection workflows. **CMake 4.1** added formal JSON schema files describing every reply object, and introduced `error-*.json` reply files for failed generations.

## Conclusion

The CMake File API is the definitive mechanism for programmatic access to CMake project structure. Its codemodel-v2 reply encodes the complete build model — from directory hierarchies and project groupings down to per-source compile flags with backtraces to the originating CMake commands. The key architectural insight is its **indirection-based design**: the index file references the codemodel, which references target files, which reference compile groups and backtrace nodes. This avoids monolithic responses and enables incremental loading.

Two notable gaps remain. First, **custom command details are invisible** — you can see that a source is generated but not what generates it. Second, **the compiler executable path** lives in the separate `toolchains` object kind rather than in compileGroups, requiring a second query to reconstruct complete compile commands. For large GNU Make/GCC codebases, the structured `compileGroups` data (with per-flag backtraces) provides strictly more information than `compile_commands.json` and works across all generators. The dependency graph from `dependencies` — and the richer `linkLibraries`/`orderDependencies` arrays in codemodel 2.9+ — enables complete build-order analysis without parsing native build files.