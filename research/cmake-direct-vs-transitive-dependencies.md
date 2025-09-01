# Direct vs. transitive dependencies in CMake's File API

**Before CMake 4.2, the File API provided no reliable way to distinguish direct from transitive dependencies.** The `dependencies` array in codemodel-v2 explicitly flattens both into a single list. CMake 4.2 (codemodel version 2.9) finally solves this with six new fields — most critically `linkLibraries`, which evaluates `LINK_LIBRARIES` non-transitively. If you can upgrade to CMake 4.2+, the problem is solved natively. If you cannot, the backtrace heuristic is the best available workaround, though it is fragile. This report covers every relevant mechanism in detail, with concrete JSON examples.

## The `dependencies` array is a flattened transitive closure

The `dependencies` array on target objects contains **every target that must build before this one** — both direct and transitive, merged into a single flat list with no distinguishing marker. The CMake documentation states explicitly:

> "The array includes not just direct dependencies, but also transitive dependencies. All listed targets will build before this one."

This was tracked as **GitLab Issue #21995** ("fileapi: Distinguish between direct and transitive link dependencies"), which noted: *"Currently, the includes and dependencies entries in the codemodel version 2 target object do not distinguish between dependencies that were explicitly defined and transitive dependencies."*

Consider a project where `MyApp` links to `LibA`, and `LibA` links to `LibB`, which links to `LibC`. The `dependencies` array for `MyApp` looks like this:

```json
{
  "name": "MyApp",
  "id": "MyApp::@6890427a1f51a3e7e1df",
  "dependencies": [
    { "id": "LibA::@abc123", "backtrace": 5 },
    { "id": "LibB::@def456", "backtrace": 12 },
    { "id": "LibC::@ghi789" }
  ]
}
```

All three appear identically. There is no field distinguishing `LibA` (the only direct dependency from `target_link_libraries(MyApp PRIVATE LibA)`) from `LibB` and `LibC` (which are transitive). Additionally, the array reflects **build graph** dependencies, not link dependencies specifically — it omits imported targets entirely (pre-v2.9), and `CMAKE_OPTIMIZE_DEPENDENCIES=ON` can cause the entire array to vanish (confirmed as a bug by CMake maintainer Craig Scott).

## Codemodel 2.9 fields finally separate direct from transitive

CMake 4.2 introduced **codemodel version 2.9**, which adds six new fields that properly decompose dependency relationships. Craig Scott confirmed on CMake Discourse: *"The problem is that the `dependencies` array isn't what most people expect it to be... CMake 4.2 added new `linkLibraries`, `interfaceLinkLibraries`, `compileDependencies`, `interfaceCompileDependencies`, `objectDependencies`, and `orderDependencies` fields. Those new fields do properly capture the dependency relationships."*

**`linkLibraries`** is the most important new field. It lists items from the target's `LINK_LIBRARIES` property **evaluated non-transitively** — meaning it contains only what the target directly links to. Each entry can be either a target (with `id`) or a raw linker fragment (with `fragment`), plus an optional `backtrace` and an optional `fromDependency` object. The `fromDependency` field is present only when the item was injected by another target's `INTERFACE_LINK_LIBRARIES_DIRECT` property rather than written in the target's own `target_link_libraries()` call. **If `fromDependency` is absent, the entry is a genuine direct dependency.**

Here is a concrete v2.9 target object showing the distinction:

```json
{
  "name": "MyApp",
  "id": "MyApp::@6890427a1f51a3e7e1df",
  "type": "EXECUTABLE",
  "dependencies": [
    { "id": "LibA::@abc123", "backtrace": 5 },
    { "id": "LibB::@def456", "backtrace": 12 },
    { "id": "LibC::@ghi789" }
  ],
  "linkLibraries": [
    { "id": "LibA::@abc123", "backtrace": 5 }
  ],
  "compileDependencies": [
    { "id": "LibA::@abc123", "backtrace": 5 }
  ],
  "objectDependencies": [],
  "orderDependencies": []
}
```

`linkLibraries` contains only `LibA` — the single direct dependency from `target_link_libraries(MyApp PRIVATE LibA)`. The transitive dependencies `LibB` and `LibC` appear only in the old `dependencies` array. You can compute **transitive-only dependencies** as: items in `dependencies` that do not appear in `linkLibraries`, `objectDependencies`, or `orderDependencies`.

**`interfaceLinkLibraries`** serves a different purpose: it lists what this target declares for its *consumers* via `INTERFACE_LINK_LIBRARIES`. If `LibA` has `target_link_libraries(LibA PUBLIC LibB)`, then `LibA`'s `interfaceLinkLibraries` would contain `LibB`. This field describes what the target *exports*, not what it *consumes*.

**`compileDependencies`** mirrors `linkLibraries` but filtered to dependencies that affect compilation (include paths, definitions). Items wrapped in `$<LINK_ONLY:...>` are excluded. **`interfaceCompileDependencies`** is its interface counterpart. **`objectDependencies`** lists targets referenced via `$<TARGET_OBJECTS:...>`. **`orderDependencies`** lists targets from `add_dependencies()` and is explicitly documented as containing only **direct** order dependencies.

## The backtrace heuristic works but is fragile

The `backtrace` field on dependency entries points into a `backtraceGraph` structure that records the exact file, line, and command that created each dependency:

```json
{
  "backtraceGraph": {
    "nodes": [
      { "file": 0, "line": 15, "command": 0, "parent": 1 },
      { "file": 1, "line": 3, "command": 0 }
    ],
    "commands": ["target_link_libraries", "add_dependencies"],
    "files": ["src/CMakeLists.txt", "libs/CMakeLists.txt"]
  }
}
```

For a **direct** dependency, the backtrace typically points to a `target_link_libraries()` call in the same CMakeLists.txt directory as the target being inspected. For a **transitive** dependency, the backtrace points to the `target_link_libraries()` call in the *dependency's* CMakeLists.txt — a different directory. You can exploit this: resolve the backtrace's file index, check whether it matches the target's `sourceDirectory`, and infer direct vs. transitive accordingly.

This approach has three significant limitations. First, the `backtrace` field is documented as optional ("present when available") with no guarantee of completeness. Second, some dependencies created by generator expressions or imported target properties may not produce meaningful backtraces. Third, a target's own `CMakeLists.txt` can use `include()` or macros from other files, which could make directory-matching unreliable. **For pre-4.2 codebases, this heuristic is the best available option, but it should be validated against known dependency structures before relying on it.**

## Link command fragments show the full resolved link line

The `link.commandFragments` array with `role: "libraries"` represents the **complete resolved linker command line**, including all transitive dependencies. It provides no separation between direct and transitive entries:

```json
{
  "link": {
    "language": "CXX",
    "commandFragments": [
      { "fragment": "/build/libLibA.a", "role": "libraries", "backtrace": 5 },
      { "fragment": "/build/libLibB.a", "role": "libraries", "backtrace": 12 },
      { "fragment": "/build/libLibC.a", "role": "libraries" },
      { "fragment": "-lpthread", "role": "libraries" },
      { "fragment": "-Wl,--as-needed", "role": "flags" }
    ]
  }
}
```

The four `role` values — `flags`, `libraries`, `libraryPath`, and `frameworkPath` — classify fragment *type*, not origin. The `backtrace` field on each fragment follows the same heuristic pattern described above (direct dependencies trace to the target's own CMakeLists.txt), but this is again unreliable. The command fragments are most useful for understanding the actual link line, not for dependency graph analysis.

## No existing tool attempts direct vs. transitive classification

A survey of major tools reveals that **none** attempt to distinguish direct from transitive dependencies from pre-v2.9 File API data:

- **VS Code CMake Tools** reads the `dependencies` array for build ordering and project tree display but treats it as a flat list. Its primary use of the File API is extracting `compileGroups` for IntelliSense, which already contains resolved (transitive) include paths and defines.
- **Qt Creator** similarly uses dependencies for build ordering and project structure. Its `FileApiDataExtractor` processes dependencies without classification.
- **cmake-file-api (Rust crate, v0.1.2)** provides a direct `Vec<Dependency>` mapping of the JSON. No filtering or categorization logic exists, and it predates codemodel 2.9.
- **python-cmake-file-api (v0.0.8.6)** mirrors the JSON structure faithfully as a flat list. No transitive-detection logic.
- **Conan** explored using the File API for package dependency extraction but abandoned the approach, noting that "the codemodel currently contains both public and private definitions and we can't determine their scope."

All of these tools would need updates to consume the new v2.9 fields.

## Practical recommendations for your codebase

Given a large C++ project with GCC 12, CMake, and GNU Make, the optimal path depends on which CMake version you can use.

**If you can upgrade to CMake 4.2+**, request codemodel version 2.9 by placing a query file at `.cmake/api/v1/query/codemodel-v2` (CMake will return the highest minor version it supports). Then use `linkLibraries` for direct link dependencies, `orderDependencies` for direct order-only dependencies, and `dependencies` minus those sets for transitive-only items. The `fromDependency` field on `linkLibraries` entries lets you further distinguish items from your own `target_link_libraries()` calls versus those injected by `INTERFACE_LINK_LIBRARIES_DIRECT`.

**If you must stay on CMake < 4.2**, implement the backtrace heuristic: for each entry in `dependencies`, resolve its `backtrace` through `backtraceGraph`, extract the source file path, and compare it against the target's `sourceDirectory`. Entries whose backtrace file matches the target's own directory (and whose command is `target_link_libraries`) are likely direct; others are likely transitive. Validate this against a few known targets in your project before trusting it broadly. As a cross-check, you can diff against `cmake --graphviz` output, which generates a `.dot` dependency graph — though it has its own quirks with interface libraries and imported targets.

For either approach, avoid relying on `CMAKE_OPTIMIZE_DEPENDENCIES=ON`, which can strip the `dependencies` array entirely (a confirmed bug). And note that `link.commandFragments` is useful for understanding the actual linker invocation but not for dependency classification.

## Conclusion

The CMake File API's original `dependencies` array was designed for build ordering, not dependency graph analysis — it deliberately flattens direct and transitive dependencies into a single list. This **15-year design gap** was finally closed in CMake 4.2 with codemodel version 2.9's `linkLibraries` field, which evaluates `LINK_LIBRARIES` non-transitively and marks injected dependencies with `fromDependency`. The backtrace heuristic provides a workable but imperfect pre-4.2 alternative. No major IDE or library currently parses direct vs. transitive from the old API; the ecosystem is still catching up to v2.9. For your GCC 12 + GNU Make project, upgrading to CMake 4.2 is the cleanest path — the new fields provide exactly the dependency classification you need without fragile heuristics.