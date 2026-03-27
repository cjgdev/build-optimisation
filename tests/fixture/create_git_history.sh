#!/usr/bin/env zsh
# create_git_history.sh — Creates synthetic git history for the fixture project.
#
# Usage: Run from the build-optimisation repo root:
#   zsh tests/fixture/create_git_history.sh
#
# Prerequisites:
#   - All fixture source files must already exist
#   - The repo must have a clean working tree (or at least the fixture files staged)
#
# This script creates ~26 commits with synthetic dates and 3 authors,
# simulating 6 months of development history on the fixture files.

set -euo pipefail

FIXTURE_DIR="tests/fixture"

# Verify we're in the right place
if [[ ! -d "$FIXTURE_DIR/src/core" ]]; then
    echo "Error: must be run from the build-optimisation repo root" >&2
    exit 1
fi

# Helper: commit as a specific author with a specific date
commit_as() {
    local author="$1"
    local date="$2"
    local msg="$3"
    shift 3

    # Stage the specified files
    for f in "$@"; do
        git add "$f"
    done

    GIT_AUTHOR_NAME="$author" \
    GIT_AUTHOR_EMAIL="${author}@example.com" \
    GIT_COMMITTER_NAME="$author" \
    GIT_COMMITTER_EMAIL="${author}@example.com" \
    GIT_AUTHOR_DATE="$date" \
    GIT_COMMITTER_DATE="$date" \
    git commit -m "$msg" --allow-empty
}

echo "Creating synthetic git history for fixture..."

# --- Phase 1: Initial import (alice) ---
commit_as "alice" "2025-09-01T09:00:00+00:00" "Initial project structure" \
    "$FIXTURE_DIR/CMakeLists.txt" \
    "$FIXTURE_DIR/config_iface/CMakeLists.txt" \
    "$FIXTURE_DIR/src/core/CMakeLists.txt" \
    "$FIXTURE_DIR/src/core/types.h" \
    "$FIXTURE_DIR/src/core/types.cpp" \
    "$FIXTURE_DIR/src/core/assert.h" \
    "$FIXTURE_DIR/src/core/assert.cpp" \
    "$FIXTURE_DIR/src/core/string_utils.h" \
    "$FIXTURE_DIR/src/core/string_utils.cpp" \
    "$FIXTURE_DIR/src/logging/CMakeLists.txt" \
    "$FIXTURE_DIR/src/logging/logger.h" \
    "$FIXTURE_DIR/src/logging/logger.cpp" \
    "$FIXTURE_DIR/src/logging/sink.h" \
    "$FIXTURE_DIR/src/logging/sink.cpp" \
    "$FIXTURE_DIR/src/platform/CMakeLists.txt" \
    "$FIXTURE_DIR/src/platform/filesystem.h" \
    "$FIXTURE_DIR/src/platform/filesystem.cpp" \
    "$FIXTURE_DIR/src/platform/thread_pool.h" \
    "$FIXTURE_DIR/src/platform/thread_pool.cpp" \
    "$FIXTURE_DIR/src/math/CMakeLists.txt" \
    "$FIXTURE_DIR/src/math/matrix.h" \
    "$FIXTURE_DIR/src/math/matrix.cpp" \
    "$FIXTURE_DIR/src/math/vector.h" \
    "$FIXTURE_DIR/src/math/vector.cpp" \
    "$FIXTURE_DIR/src/math/transforms.h" \
    "$FIXTURE_DIR/src/math/transforms.cpp" \
    "$FIXTURE_DIR/src/math/helpers/constants.h" \
    "$FIXTURE_DIR/src/math/helpers/constants.cpp" \
    "$FIXTURE_DIR/src/math/helpers/interpolation.h" \
    "$FIXTURE_DIR/src/math/helpers/interpolation.cpp" \
    "$FIXTURE_DIR/src/codegen/CMakeLists.txt" \
    "$FIXTURE_DIR/src/codegen/generate_messages.py" \
    "$FIXTURE_DIR/src/codegen/messages.def" \
    "$FIXTURE_DIR/src/codegen/proto/registry.h" \
    "$FIXTURE_DIR/src/codegen/proto/registry.cpp" \
    "$FIXTURE_DIR/src/codegen/proto/validation.h" \
    "$FIXTURE_DIR/src/codegen/proto/validation.cpp" \
    "$FIXTURE_DIR/src/serialization/CMakeLists.txt" \
    "$FIXTURE_DIR/src/serialization/encoder.h" \
    "$FIXTURE_DIR/src/serialization/encoder.cpp" \
    "$FIXTURE_DIR/src/serialization/decoder.h" \
    "$FIXTURE_DIR/src/serialization/decoder.cpp" \
    "$FIXTURE_DIR/src/protocol/CMakeLists.txt" \
    "$FIXTURE_DIR/src/protocol/handler.h" \
    "$FIXTURE_DIR/src/protocol/handler.cpp" \
    "$FIXTURE_DIR/src/protocol/connection.h" \
    "$FIXTURE_DIR/src/protocol/connection.cpp" \
    "$FIXTURE_DIR/src/compute/CMakeLists.txt" \
    "$FIXTURE_DIR/src/compute/pipeline.h" \
    "$FIXTURE_DIR/src/compute/pipeline.cpp" \
    "$FIXTURE_DIR/src/compute/scheduler.h" \
    "$FIXTURE_DIR/src/compute/scheduler.cpp" \
    "$FIXTURE_DIR/src/middleware/CMakeLists.txt" \
    "$FIXTURE_DIR/src/middleware/request_router.h" \
    "$FIXTURE_DIR/src/middleware/request_router.cpp" \
    "$FIXTURE_DIR/src/middleware/metrics_collector.h" \
    "$FIXTURE_DIR/src/middleware/metrics_collector.cpp" \
    "$FIXTURE_DIR/src/middleware/service_registry.h" \
    "$FIXTURE_DIR/src/middleware/service_registry.cpp" \
    "$FIXTURE_DIR/src/middleware/rate_limiter.h" \
    "$FIXTURE_DIR/src/middleware/rate_limiter.cpp" \
    "$FIXTURE_DIR/src/engine/CMakeLists.txt" \
    "$FIXTURE_DIR/src/engine/engine.h" \
    "$FIXTURE_DIR/src/engine/engine.cpp" \
    "$FIXTURE_DIR/src/plugin_api/CMakeLists.txt" \
    "$FIXTURE_DIR/src/plugin_api/plugin_api.h" \
    "$FIXTURE_DIR/src/plugin_api/plugin_api.cpp" \
    "$FIXTURE_DIR/src/plugin_api/plugin_registry.h" \
    "$FIXTURE_DIR/src/plugin_api/plugin_registry.cpp" \
    "$FIXTURE_DIR/src/app/CMakeLists.txt" \
    "$FIXTURE_DIR/src/app/main.cpp" \
    "$FIXTURE_DIR/src/test/CMakeLists.txt" \
    "$FIXTURE_DIR/src/test/test_main.cpp" \
    "$FIXTURE_DIR/src/test/test_protocol.cpp" \
    "$FIXTURE_DIR/src/test/test_compute.cpp" \
    "$FIXTURE_DIR/src/benchmark/CMakeLists.txt" \
    "$FIXTURE_DIR/src/benchmark/bench_main.cpp"

# --- Phase 2: Core stabilisation (alice, Sep week 2-3) ---
commit_as "alice" "2025-09-08T10:00:00+00:00" "core: strengthen assertion handler" \
    "$FIXTURE_DIR/src/core/assert.cpp"

commit_as "alice" "2025-09-10T14:30:00+00:00" "core: add Result type aliases" \
    "$FIXTURE_DIR/src/core/types.h" \
    "$FIXTURE_DIR/src/core/types.cpp"

commit_as "alice" "2025-09-15T11:00:00+00:00" "core: extend string split with max_parts" \
    "$FIXTURE_DIR/src/core/string_utils.cpp"

# --- Phase 3: Protocol feature work (bob, Sep-Oct) ---
commit_as "bob" "2025-09-20T09:00:00+00:00" "codegen: refine message definitions" \
    "$FIXTURE_DIR/src/codegen/messages.def" \
    "$FIXTURE_DIR/src/codegen/generate_messages.py"

commit_as "bob" "2025-09-25T10:30:00+00:00" "proto: implement registry wrapper" \
    "$FIXTURE_DIR/src/codegen/proto/registry.h" \
    "$FIXTURE_DIR/src/codegen/proto/registry.cpp"

commit_as "bob" "2025-10-01T09:00:00+00:00" "proto: add validation layer" \
    "$FIXTURE_DIR/src/codegen/proto/validation.h" \
    "$FIXTURE_DIR/src/codegen/proto/validation.cpp"

commit_as "bob" "2025-10-05T14:00:00+00:00" "serialization: implement binary encoder" \
    "$FIXTURE_DIR/src/serialization/encoder.h" \
    "$FIXTURE_DIR/src/serialization/encoder.cpp"

commit_as "bob" "2025-10-08T11:00:00+00:00" "serialization: implement decoder" \
    "$FIXTURE_DIR/src/serialization/decoder.h" \
    "$FIXTURE_DIR/src/serialization/decoder.cpp"

commit_as "bob" "2025-10-12T09:30:00+00:00" "protocol: add connection handling" \
    "$FIXTURE_DIR/src/protocol/connection.h" \
    "$FIXTURE_DIR/src/protocol/connection.cpp"

commit_as "bob" "2025-10-15T15:00:00+00:00" "protocol: add request handler" \
    "$FIXTURE_DIR/src/protocol/handler.h" \
    "$FIXTURE_DIR/src/protocol/handler.cpp"

commit_as "bob" "2025-10-20T10:00:00+00:00" "codegen: add MetricReport message type" \
    "$FIXTURE_DIR/src/codegen/messages.def" \
    "$FIXTURE_DIR/src/codegen/proto/registry.cpp"

# --- Phase 4: Middleware refactoring (charlie, Nov) ---
commit_as "charlie" "2025-11-01T09:00:00+00:00" "middleware: initial request routing" \
    "$FIXTURE_DIR/src/middleware/request_router.h" \
    "$FIXTURE_DIR/src/middleware/request_router.cpp"

commit_as "charlie" "2025-11-08T10:00:00+00:00" "middleware: refactor request routing dispatch" \
    "$FIXTURE_DIR/src/middleware/request_router.h" \
    "$FIXTURE_DIR/src/middleware/request_router.cpp"

commit_as "charlie" "2025-11-12T14:00:00+00:00" "middleware: add metrics collection" \
    "$FIXTURE_DIR/src/middleware/metrics_collector.h" \
    "$FIXTURE_DIR/src/middleware/metrics_collector.cpp"

commit_as "charlie" "2025-11-18T11:30:00+00:00" "middleware: integrate service registry with routing" \
    "$FIXTURE_DIR/src/middleware/service_registry.cpp"

# --- Phase 5: Compute optimisation (alice, Nov-Dec) ---
commit_as "alice" "2025-11-25T09:00:00+00:00" "compute: optimise matrix transform pipeline" \
    "$FIXTURE_DIR/src/math/transforms.cpp" \
    "$FIXTURE_DIR/src/compute/pipeline.cpp"

commit_as "alice" "2025-12-01T14:00:00+00:00" "compute: tune scheduler thread allocation" \
    "$FIXTURE_DIR/src/compute/scheduler.cpp"

# --- Phase 6: Bug fixes (scattered, Dec) ---
commit_as "bob" "2025-12-05T10:00:00+00:00" "fix: protocol connection timeout handling" \
    "$FIXTURE_DIR/src/protocol/connection.cpp"

commit_as "charlie" "2025-12-08T11:00:00+00:00" "fix: thread pool deadlock on shutdown" \
    "$FIXTURE_DIR/src/platform/thread_pool.cpp"

commit_as "alice" "2025-12-10T09:30:00+00:00" "fix: logger null sink crash" \
    "$FIXTURE_DIR/src/logging/logger.cpp"

commit_as "charlie" "2025-12-12T14:00:00+00:00" "fix: engine shutdown race condition" \
    "$FIXTURE_DIR/src/engine/engine.cpp"

commit_as "bob" "2025-12-15T10:30:00+00:00" "fix: registry type lookup failure" \
    "$FIXTURE_DIR/src/codegen/proto/registry.cpp"

# --- Phase 7: Logging improvements (alice, Dec) ---
commit_as "alice" "2025-12-18T09:00:00+00:00" "logging: add structured log levels" \
    "$FIXTURE_DIR/src/logging/logger.h" \
    "$FIXTURE_DIR/src/logging/logger.cpp" \
    "$FIXTURE_DIR/src/logging/sink.h" \
    "$FIXTURE_DIR/src/logging/sink.cpp"

commit_as "alice" "2025-12-20T11:00:00+00:00" "logging: improve sink buffering" \
    "$FIXTURE_DIR/src/logging/sink.cpp"

echo "Done. Created 26 synthetic commits."
