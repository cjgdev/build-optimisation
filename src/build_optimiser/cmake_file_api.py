"""CMake File API codemodel-v2 parser.

Encapsulates query file creation, reply parsing, and index building.
Supports codemodel 2.9 (CMake 4.2+) for direct vs transitive dependency classification.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


class FileAPIError(Exception):
    """Raised when the File API reply is missing or malformed."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IncludeEntry:
    path: str
    is_system: bool = False


@dataclass(frozen=True, slots=True)
class CompileGroup:
    language: str
    language_standard: str | None
    flags: str
    includes: tuple[IncludeEntry, ...]
    defines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Artifact:
    path: str


@dataclass(frozen=True, slots=True)
class FileEntry:
    path: str  # canonical absolute path
    cmake_target: str
    compile_group_index: int | None
    is_generated: bool
    language: str | None


@dataclass(frozen=True, slots=True)
class Target:
    name: str
    id: str
    type: str  # EXECUTABLE, STATIC_LIBRARY, SHARED_LIBRARY, MODULE_LIBRARY, OBJECT_LIBRARY, INTERFACE_LIBRARY, UTILITY
    name_on_disk: str | None
    artifacts: tuple[Artifact, ...]
    source_dir: str
    build_dir: str
    sources: tuple[FileEntry, ...]
    compile_groups: tuple[CompileGroup, ...]
    link_libraries: tuple[str, ...] | None  # target IDs — codemodel 2.9+
    order_dependencies: tuple[str, ...] | None
    compile_dependencies: tuple[str, ...] | None
    object_dependencies: tuple[str, ...] | None
    interface_link_libraries: tuple[str, ...] | None  # codemodel 2.9+
    interface_compile_dependencies: tuple[str, ...] | None  # codemodel 2.9+
    all_dependencies: tuple[str, ...]
    link_fragments: tuple[str, ...]
    backtrace_graph: dict = field(default_factory=dict)
    is_generator_provided: bool = False


@dataclass(frozen=True, slots=True)
class Edge:
    source_target: str
    dest_target: str
    is_direct: bool
    dependency_type: str  # link / compile / object / order / transitive
    from_dependency: str | None = None
    cmake_visibility: str = "UNKNOWN"  # PUBLIC / PRIVATE / INTERFACE / TRANSITIVE / UNKNOWN


@dataclass
class CodeModel:
    targets: dict[str, Target]
    id_to_name: dict[str, str]
    edges: list[Edge]
    cmake_version: str
    codemodel_version: tuple[int, int]


# ---------------------------------------------------------------------------
# Query file creation
# ---------------------------------------------------------------------------


def create_query_files(build_dir: Path, client_name: str) -> None:
    """Create the File API query directory and empty query files."""
    query_dir = build_dir / ".cmake" / "api" / "v1" / "query" / f"client-{client_name}"
    query_dir.mkdir(parents=True, exist_ok=True)
    (query_dir / "codemodel-v2").touch()
    (query_dir / "toolchains-v1").touch()


# ---------------------------------------------------------------------------
# Reply parsing
# ---------------------------------------------------------------------------


def parse_reply(build_dir: Path, source_dir: Path) -> CodeModel:
    """Parse the File API reply and return a structured CodeModel."""
    reply_dir = build_dir / ".cmake" / "api" / "v1" / "reply"
    if not reply_dir.is_dir():
        raise FileAPIError(
            f"No File API reply directory at {reply_dir}. "
            "Ensure cmake was run after query files were created."
        )

    # Find the index file (lexicographically last)
    index_files = sorted(reply_dir.glob("index-*.json"))
    if not index_files:
        raise FileAPIError(f"No index-*.json found in {reply_dir}")
    index_path = index_files[-1]

    with open(index_path) as f:
        index_data = json.load(f)

    cmake_version = index_data["cmake"]["version"]["string"]

    # Find the codemodel object
    codemodel_entry = None
    for obj in index_data.get("objects", []):
        if obj["kind"] == "codemodel":
            codemodel_entry = obj
            break

    if codemodel_entry is None:
        raise FileAPIError("No codemodel object in File API index")

    codemodel_major = codemodel_entry["version"]["major"]
    codemodel_minor = codemodel_entry["version"]["minor"]

    if codemodel_minor < 9:
        logger.warning(
            "CMake %s produces codemodel %d.%d. Direct/transitive dependency "
            "separation requires codemodel 2.9 (CMake 4.2+). All edges will be "
            "classified as 'transitive'.",
            cmake_version, codemodel_major, codemodel_minor,
        )

    # Load codemodel JSON
    codemodel_path = reply_dir / codemodel_entry["jsonFile"]
    with open(codemodel_path) as f:
        codemodel_data = json.load(f)

    config = codemodel_data["configurations"][0]
    source_dir_resolved = str(Path(source_dir).resolve())

    # Build id_to_name from both targets and abstractTargets
    id_to_name: dict[str, str] = {}
    all_target_entries = list(config.get("targets", []))
    all_target_entries.extend(config.get("abstractTargets", []))
    for entry in all_target_entries:
        id_to_name[entry["id"]] = entry["name"]

    # Parse each target
    targets: dict[str, Target] = {}
    for entry in all_target_entries:
        target_path = reply_dir / entry["jsonFile"]
        with open(target_path) as f:
            target_data = json.load(f)

        # Skip generator-provided targets
        if target_data.get("isGeneratorProvided", False):
            continue

        target = _parse_target(target_data, source_dir_resolved, str(build_dir.resolve()))
        targets[target.name] = target

    # Extract edges
    edges = _extract_edges(targets, id_to_name, codemodel_minor)

    return CodeModel(
        targets=targets,
        id_to_name=id_to_name,
        edges=edges,
        cmake_version=cmake_version,
        codemodel_version=(codemodel_major, codemodel_minor),
    )


def _canonicalise(path: str, base_dir: str) -> str:
    """Canonicalise a path relative to a base directory."""
    if os.path.isabs(path):
        return os.path.realpath(path)
    return os.path.realpath(os.path.join(base_dir, path))


def _parse_target(data: dict, source_dir: str, build_dir: str) -> Target:
    """Parse a single target JSON object into a Target dataclass."""
    name = data["name"]
    target_source_dir = _canonicalise(data["paths"]["source"], source_dir)
    target_build_dir = _canonicalise(data["paths"]["build"], build_dir)

    # Parse compile groups
    compile_groups: list[CompileGroup] = []
    for cg in data.get("compileGroups", []):
        lang = cg.get("language", "")
        lang_std_obj = cg.get("languageStandard")
        lang_std = lang_std_obj.get("standard") if lang_std_obj else None

        fragments = cg.get("compileCommandFragments", [])
        flags = " ".join(f.get("fragment", "") for f in fragments)

        includes = tuple(
            IncludeEntry(
                path=os.path.realpath(inc["path"]),
                is_system=inc.get("isSystem", False),
            )
            for inc in cg.get("includes", [])
        )

        defines = tuple(d["define"] for d in cg.get("defines", []))

        compile_groups.append(CompileGroup(
            language=lang,
            language_standard=lang_std,
            flags=flags,
            includes=includes,
            defines=defines,
        ))

    # Parse sources into FileEntry objects
    sources: list[FileEntry] = []
    for src in data.get("sources", []):
        src_path = src["path"]
        is_generated = src.get("isGenerated", False)

        # Canonicalise: generated files may have absolute paths from the build dir;
        # non-generated files are relative to the source dir
        if os.path.isabs(src_path):
            canonical = os.path.realpath(src_path)
        elif is_generated:
            canonical = _canonicalise(src_path, build_dir)
        else:
            canonical = _canonicalise(src_path, source_dir)

        cg_index = src.get("compileGroupIndex")
        language = None
        if cg_index is not None and cg_index < len(compile_groups):
            language = compile_groups[cg_index].language

        sources.append(FileEntry(
            path=canonical,
            cmake_target=name,
            compile_group_index=cg_index,
            is_generated=is_generated,
            language=language,
        ))

    # Parse artifacts
    artifacts = tuple(
        Artifact(path=_canonicalise(a["path"], build_dir))
        for a in data.get("artifacts", [])
    )

    # Parse dependencies
    all_deps = tuple(d["id"] for d in data.get("dependencies", []))

    # codemodel 2.9+ fields
    link_libs = _extract_dep_ids(data, "linkLibraries")
    order_deps = _extract_dep_ids(data, "orderDependencies")
    compile_deps = _extract_dep_ids(data, "compileDependencies")
    object_deps = _extract_dep_ids(data, "objectDependencies")
    iface_link_libs = _extract_dep_ids(data, "interfaceLinkLibraries")
    iface_compile_deps = _extract_dep_ids(data, "interfaceCompileDependencies")

    # Link fragments
    link_data = data.get("link", {})
    link_frags = tuple(
        f.get("fragment", "")
        for f in link_data.get("commandFragments", [])
    )

    return Target(
        name=name,
        id=data["id"],
        type=data.get("type", "UTILITY"),
        name_on_disk=data.get("nameOnDisk"),
        artifacts=artifacts,
        source_dir=target_source_dir,
        build_dir=target_build_dir,
        sources=tuple(sources),
        compile_groups=tuple(compile_groups),
        link_libraries=link_libs,
        order_dependencies=order_deps,
        compile_dependencies=compile_deps,
        object_dependencies=object_deps,
        interface_link_libraries=iface_link_libs,
        interface_compile_dependencies=iface_compile_deps,
        all_dependencies=all_deps,
        link_fragments=link_frags,
        backtrace_graph=data.get("backtraceGraph", {}),
    )


def _extract_dep_ids(data: dict, key: str) -> tuple[str, ...] | None:
    """Extract dependency IDs from a codemodel 2.9+ field, or None if absent."""
    entries = data.get(key)
    if entries is None:
        return None
    return tuple(e["id"] for e in entries)


def _extract_edges(
    targets: dict[str, Target],
    id_to_name: dict[str, str],
    codemodel_minor: int,
) -> list[Edge]:
    """Build the edge list from parsed targets."""
    edges: list[Edge] = []

    for target in targets.values():
        if codemodel_minor >= 9:
            # Use the specific dependency fields for classification
            direct_link_ids = set(target.link_libraries or ())
            direct_order_ids = set(target.order_dependencies or ())
            direct_compile_ids = set(target.compile_dependencies or ())
            direct_object_ids = set(target.object_dependencies or ())
            all_direct_ids = direct_link_ids | direct_order_ids | direct_compile_ids | direct_object_ids

            # interfaceCompileDependencies distinguishes PUBLIC from PRIVATE:
            # PUBLIC deps appear in both linkLibraries and interfaceCompileDependencies,
            # PRIVATE deps appear only in linkLibraries.
            iface_compile_ids = set(target.interface_compile_dependencies or ())

            def _link_visibility(dep_id: str) -> str:
                """Determine cmake visibility for a direct link dependency."""
                if dep_id in iface_compile_ids:
                    return "PUBLIC"
                return "PRIVATE"

            # Process direct dependencies with their type
            for dep_id in direct_link_ids:
                dep_name = id_to_name.get(dep_id)
                if dep_name and dep_name in targets:
                    edges.append(Edge(
                        source_target=target.name,
                        dest_target=dep_name,
                        is_direct=True,
                        dependency_type="link",
                        cmake_visibility=_link_visibility(dep_id),
                    ))

            for dep_id in direct_order_ids:
                dep_name = id_to_name.get(dep_id)
                if dep_name and dep_name in targets:
                    # Avoid duplicate if already added as link
                    if dep_id not in direct_link_ids:
                        edges.append(Edge(
                            source_target=target.name,
                            dest_target=dep_name,
                            is_direct=True,
                            dependency_type="order",
                        ))

            for dep_id in direct_compile_ids:
                dep_name = id_to_name.get(dep_id)
                if dep_name and dep_name in targets:
                    if dep_id not in direct_link_ids and dep_id not in direct_order_ids:
                        edges.append(Edge(
                            source_target=target.name,
                            dest_target=dep_name,
                            is_direct=True,
                            dependency_type="compile",
                        ))

            for dep_id in direct_object_ids:
                dep_name = id_to_name.get(dep_id)
                if dep_name and dep_name in targets:
                    if dep_id not in all_direct_ids - direct_object_ids:
                        edges.append(Edge(
                            source_target=target.name,
                            dest_target=dep_name,
                            is_direct=True,
                            dependency_type="object",
                        ))

            # Transitive: in all_dependencies but not in any direct set
            for dep_id in target.all_dependencies:
                if dep_id not in all_direct_ids:
                    dep_name = id_to_name.get(dep_id)
                    if dep_name and dep_name in targets:
                        edges.append(Edge(
                            source_target=target.name,
                            dest_target=dep_name,
                            is_direct=False,
                            dependency_type="transitive",
                            cmake_visibility="TRANSITIVE",
                        ))
        else:
            # Pre-2.9: all edges classified as transitive
            for dep_id in target.all_dependencies:
                dep_name = id_to_name.get(dep_id)
                if dep_name and dep_name in targets:
                    edges.append(Edge(
                        source_target=target.name,
                        dest_target=dep_name,
                        is_direct=False,
                        dependency_type="transitive",
                        cmake_visibility="UNKNOWN",
                    ))

    return edges


# ---------------------------------------------------------------------------
# Index builders
# ---------------------------------------------------------------------------


def build_file_index(codemodel: CodeModel) -> dict[str, str]:
    """Map canonical file path -> target name for all source files."""
    index: dict[str, str] = {}
    for target in codemodel.targets.values():
        for file_entry in target.sources:
            index[file_entry.path] = file_entry.cmake_target
    return index


def build_target_index(codemodel: CodeModel) -> dict[str, Target]:
    """Map target name -> Target object."""
    return dict(codemodel.targets)


def build_codegen_inventory(codemodel: CodeModel) -> dict[str, list[str]]:
    """Map target name -> list of generated file paths."""
    inventory: dict[str, list[str]] = {}
    for target in codemodel.targets.values():
        generated = [f.path for f in target.sources if f.is_generated]
        if generated:
            inventory[target.name] = generated
    return inventory


def reconstruct_compile_command(
    file_entry: FileEntry,
    target: Target,
    compiler_path: str,
) -> str | None:
    """Build a complete compile command from structured File API data.

    Returns None for files with no compile group (e.g., headers in INTERFACE libraries).
    """
    if file_entry.compile_group_index is None:
        return None
    if file_entry.compile_group_index >= len(target.compile_groups):
        return None

    cg = target.compile_groups[file_entry.compile_group_index]
    parts = [compiler_path]

    if cg.flags:
        parts.append(cg.flags)

    for inc in cg.includes:
        prefix = "-isystem " if inc.is_system else "-I"
        parts.append(f"{prefix}{inc.path}")

    for define in cg.defines:
        parts.append(f"-D{define}")

    parts.append(file_entry.path)

    return " ".join(parts)
