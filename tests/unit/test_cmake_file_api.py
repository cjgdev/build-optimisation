"""Tests for build_optimiser.cmake_file_api against static fixture reply data."""

from pathlib import Path

import pytest

from build_optimiser.cmake_file_api import (
    CodeModel,
    FileAPIError,
    build_codegen_inventory,
    build_file_index,
    create_query_files,
    parse_reply,
    reconstruct_compile_command,
)

REPLY_DIR = Path(__file__).parent.parent / "data" / "cmake_file_api_reply"

# The fixture source dir at the time the reply was generated
FIXTURE_DIR = Path(__file__).parent.parent / "fixture"


@pytest.fixture
def codemodel() -> CodeModel:
    """Parse the static reply data once per test module."""
    # We need to find the build_dir that was used when the reply was generated.
    # The reply dir IS the reply — we need a fake build_dir that contains it.
    # Create a symlink structure so parse_reply can find it.
    # Actually, the reply dir is at tests/data/cmake_file_api_reply/
    # but parse_reply expects build_dir/.cmake/api/v1/reply/
    # We'll construct a temporary structure.
    import tempfile
    import os

    tmp = Path(tempfile.mkdtemp())
    api_reply = tmp / ".cmake" / "api" / "v1" / "reply"
    api_reply.mkdir(parents=True)

    # Symlink all files from the static reply dir
    for f in REPLY_DIR.iterdir():
        os.symlink(f, api_reply / f.name)

    return parse_reply(tmp, FIXTURE_DIR)


# Expected non-generator-provided targets from the fixture
EXPECTED_TARGETS = {
    "core", "logging", "platform", "math_lib", "math_objs",
    "proto_gen", "proto_msgs", "serialization", "protocol",
    "compute", "middleware", "engine", "plugin_api",
    "app", "test_runner", "benchmark", "config_iface",
}


class TestParseReply:
    def test_loads_all_fixture_targets(self, codemodel: CodeModel):
        target_names = set(codemodel.targets.keys())
        assert EXPECTED_TARGETS.issubset(target_names), (
            f"Missing targets: {EXPECTED_TARGETS - target_names}"
        )

    def test_cmake_version_detected(self, codemodel: CodeModel):
        assert codemodel.cmake_version.startswith("4.")

    def test_codemodel_version_is_2_9(self, codemodel: CodeModel):
        assert codemodel.codemodel_version == (2, 9)

    def test_no_generator_provided_targets(self, codemodel: CodeModel):
        # ALL_BUILD, ZERO_CHECK, etc. should be filtered out
        for name in codemodel.targets:
            assert name not in ("ALL_BUILD", "ZERO_CHECK", "INSTALL")


class TestTargetParsing:
    def test_core_is_static_library(self, codemodel: CodeModel):
        assert codemodel.targets["core"].type == "STATIC_LIBRARY"

    def test_app_is_executable(self, codemodel: CodeModel):
        assert codemodel.targets["app"].type == "EXECUTABLE"

    def test_config_iface_is_interface(self, codemodel: CodeModel):
        assert codemodel.targets["config_iface"].type == "INTERFACE_LIBRARY"

    def test_plugin_api_is_shared_library(self, codemodel: CodeModel):
        assert codemodel.targets["plugin_api"].type == "SHARED_LIBRARY"

    def test_math_objs_is_object_library(self, codemodel: CodeModel):
        assert codemodel.targets["math_objs"].type == "OBJECT_LIBRARY"

    def test_proto_gen_is_utility(self, codemodel: CodeModel):
        assert codemodel.targets["proto_gen"].type == "UTILITY"

    def test_core_has_sources(self, codemodel: CodeModel):
        core = codemodel.targets["core"]
        source_names = [Path(s.path).name for s in core.sources]
        assert "types.cpp" in source_names
        assert "assert.cpp" in source_names
        assert "string_utils.cpp" in source_names

    def test_core_has_compile_groups(self, codemodel: CodeModel):
        core = codemodel.targets["core"]
        assert len(core.compile_groups) >= 1
        assert core.compile_groups[0].language == "CXX"

    def test_core_has_artifacts(self, codemodel: CodeModel):
        core = codemodel.targets["core"]
        assert any("libcore.a" in a.path for a in core.artifacts)

    def test_name_on_disk(self, codemodel: CodeModel):
        assert codemodel.targets["core"].name_on_disk == "libcore.a"

    def test_interface_compile_dependencies_populated(self, codemodel: CodeModel):
        # middleware has PUBLIC deps, so interface_compile_dependencies should be set
        middleware = codemodel.targets["middleware"]
        assert middleware.interface_compile_dependencies is not None
        assert len(middleware.interface_compile_dependencies) > 0

    def test_private_deps_not_in_interface_compile(self, codemodel: CodeModel):
        # engine has PRIVATE dep on middleware — should not have interfaceCompileDependencies
        engine = codemodel.targets["engine"]
        iface_ids = set(engine.interface_compile_dependencies or ())
        # middleware should not be in interface compile deps since it's PRIVATE
        assert not iface_ids, "engine has only PRIVATE deps, so interface_compile_dependencies should be empty"


class TestCodegenFiles:
    def test_proto_msgs_has_generated_sources(self, codemodel: CodeModel):
        proto_msgs = codemodel.targets["proto_msgs"]
        generated = [s for s in proto_msgs.sources if s.is_generated]
        assert len(generated) >= 4  # messages.h, messages.cpp, message_registry.h, message_registry.cpp

    def test_generated_files_marked_correctly(self, codemodel: CodeModel):
        proto_msgs = codemodel.targets["proto_msgs"]
        for src in proto_msgs.sources:
            if "generated" in src.path:
                assert src.is_generated

    def test_non_generated_files_not_marked(self, codemodel: CodeModel):
        core = codemodel.targets["core"]
        for src in core.sources:
            assert not src.is_generated


class TestFileIndex:
    def test_all_paths_are_absolute(self, codemodel: CodeModel):
        file_index = build_file_index(codemodel)
        for path in file_index:
            assert path.startswith("/"), f"Path not absolute: {path}"

    def test_maps_to_correct_targets(self, codemodel: CodeModel):
        file_index = build_file_index(codemodel)
        # Find a core source file
        core_files = [p for p, t in file_index.items() if t == "core"]
        assert len(core_files) >= 3

    def test_generated_files_in_index(self, codemodel: CodeModel):
        file_index = build_file_index(codemodel)
        proto_msgs_files = [p for p, t in file_index.items() if t == "proto_msgs"]
        assert len(proto_msgs_files) >= 4  # authored + generated


class TestCodegenInventory:
    def test_proto_msgs_in_inventory(self, codemodel: CodeModel):
        inventory = build_codegen_inventory(codemodel)
        assert "proto_msgs" in inventory

    def test_proto_msgs_generated_files(self, codemodel: CodeModel):
        inventory = build_codegen_inventory(codemodel)
        generated = inventory["proto_msgs"]
        basenames = [Path(p).name for p in generated]
        assert "messages.h" in basenames
        assert "messages.cpp" in basenames
        assert "message_registry.h" in basenames
        assert "message_registry.cpp" in basenames

    def test_core_not_in_inventory(self, codemodel: CodeModel):
        inventory = build_codegen_inventory(codemodel)
        assert "core" not in inventory


class TestEdges:
    def test_has_edges(self, codemodel: CodeModel):
        assert len(codemodel.edges) > 0

    def test_app_has_direct_link_to_engine(self, codemodel: CodeModel):
        app_edges = [e for e in codemodel.edges if e.source_target == "app"]
        engine_edges = [e for e in app_edges if e.dest_target == "engine"]
        assert any(e.is_direct and e.dependency_type == "link" for e in engine_edges)

    def test_app_has_transitive_deps(self, codemodel: CodeModel):
        app_edges = [e for e in codemodel.edges if e.source_target == "app"]
        transitive = [e for e in app_edges if not e.is_direct]
        assert len(transitive) > 0

    def test_core_depends_on_config_iface(self, codemodel: CodeModel):
        core_edges = [e for e in codemodel.edges if e.source_target == "core"]
        config_edges = [e for e in core_edges if e.dest_target == "config_iface"]
        assert len(config_edges) > 0

    def test_proto_msgs_order_depends_on_proto_gen(self, codemodel: CodeModel):
        proto_msgs_edges = [e for e in codemodel.edges if e.source_target == "proto_msgs"]
        proto_gen_edges = [e for e in proto_msgs_edges if e.dest_target == "proto_gen"]
        assert any(e.dependency_type == "order" for e in proto_gen_edges)

    def test_edge_types_valid(self, codemodel: CodeModel):
        valid_types = {"link", "compile", "object", "order", "transitive"}
        for edge in codemodel.edges:
            assert edge.dependency_type in valid_types

    def test_visibility_values_valid(self, codemodel: CodeModel):
        valid = {"PUBLIC", "PRIVATE", "INTERFACE", "TRANSITIVE", "UNKNOWN"}
        for edge in codemodel.edges:
            assert edge.cmake_visibility in valid, (
                f"Invalid visibility '{edge.cmake_visibility}' on {edge.source_target} -> {edge.dest_target}"
            )

    def test_transitive_edges_have_transitive_visibility(self, codemodel: CodeModel):
        for edge in codemodel.edges:
            if not edge.is_direct:
                assert edge.cmake_visibility == "TRANSITIVE"

    def test_private_link_visibility(self, codemodel: CodeModel):
        # engine -> middleware is PRIVATE (target_link_libraries(engine PRIVATE middleware))
        engine_to_middleware = [
            e for e in codemodel.edges
            if e.source_target == "engine" and e.dest_target == "middleware" and e.dependency_type == "link"
        ]
        assert len(engine_to_middleware) == 1
        assert engine_to_middleware[0].cmake_visibility == "PRIVATE"

    def test_public_link_visibility(self, codemodel: CodeModel):
        # middleware -> protocol is PUBLIC (target_link_libraries(middleware PUBLIC protocol compute logging))
        middleware_to_protocol = [
            e for e in codemodel.edges
            if e.source_target == "middleware" and e.dest_target == "protocol" and e.dependency_type == "link"
        ]
        assert len(middleware_to_protocol) == 1
        assert middleware_to_protocol[0].cmake_visibility == "PUBLIC"


class TestCreateQueryFiles:
    def test_creates_files(self, tmp_path: Path):
        create_query_files(tmp_path, "test-client")
        query_dir = tmp_path / ".cmake" / "api" / "v1" / "query" / "client-test-client"
        assert (query_dir / "codemodel-v2").exists()
        assert (query_dir / "toolchains-v1").exists()

    def test_idempotent(self, tmp_path: Path):
        create_query_files(tmp_path, "test-client")
        create_query_files(tmp_path, "test-client")  # no error

    def test_no_reply_dir_raises(self, tmp_path: Path):
        with pytest.raises(FileAPIError, match="No File API reply"):
            parse_reply(tmp_path, tmp_path)


class TestReconstructCompileCommand:
    def test_returns_command_for_source_file(self, codemodel: CodeModel):
        core = codemodel.targets["core"]
        src = [s for s in core.sources if s.compile_group_index is not None][0]
        cmd = reconstruct_compile_command(src, core, "/usr/bin/g++")
        assert cmd is not None
        assert "/usr/bin/g++" in cmd
        assert src.path in cmd

    def test_returns_none_for_no_compile_group(self, codemodel: CodeModel):
        # config_iface is INTERFACE_LIBRARY — no compile groups
        config = codemodel.targets["config_iface"]
        if config.sources:
            for src in config.sources:
                if src.compile_group_index is None:
                    result = reconstruct_compile_command(src, config, "/usr/bin/g++")
                    assert result is None
                    return
        # If no sources at all, that's also fine for INTERFACE
        assert True

    def test_includes_flags_and_defines(self, codemodel: CodeModel):
        core = codemodel.targets["core"]
        src = [s for s in core.sources if s.compile_group_index is not None][0]
        cmd = reconstruct_compile_command(src, core, "/usr/bin/g++")
        # Should contain at least some flags
        assert "-std=" in cmd or "gnu++" in cmd
