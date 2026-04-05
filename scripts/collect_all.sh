#!/bin/zsh
# collect_all.sh — Run all collection scripts in order with parallelism.
# Usage: ./scripts/collect_all.sh [--config path/to/config.yaml] [--skip 02] [--skip 05] ...

set -euo pipefail

CONFIG="config.yaml"
typeset -A SKIP

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)
            CONFIG="$2"
            shift 2
            ;;
        --skip)
            SKIP[$2]=1
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)/collect"
TOTAL_START=$SECONDS

run_step() {
    local step=$1
    local script=$2
    local step_start=$SECONDS

    if [[ -n "${SKIP[$step]+x}" ]]; then
        echo "=== Step $step: SKIPPED ==="
        return 0
    fi

    echo "=== Step $step: $script ==="
    python "$SCRIPT_DIR/$script" --config "$CONFIG"
    echo "=== Step $step complete in $(( SECONDS - step_start ))s ==="
}

trap 'echo "Collection FAILED at step in progress"; exit 1' ERR

# Step 1: CMake File API (configure + extract) — must complete first
run_step "01" "01_cmake_file_api.py"

# Steps 2 and 3 can run in parallel (git history doesn't need the build)
if [[ -z "${SKIP[02]+x}" ]]; then
    python "$SCRIPT_DIR/02_git_history.py" --config "$CONFIG" &
    GIT_PID=$!
else
    echo "=== Step 02: SKIPPED ==="
    GIT_PID=""
fi

# Step 3: Instrumented build
run_step "03" "03_instrumented_build.py"

# Wait for git history if it was started
if [[ -n "$GIT_PID" ]]; then
    if wait "$GIT_PID"; then
        echo "=== Step 02 complete ==="
    else
        echo "=== Step 02 FAILED ===" >&2
        exit 1
    fi
fi

# Steps 4, 5, 6 can run in parallel (all read from completed build)
PIDS=()

if [[ -z "${SKIP[04]+x}" ]]; then
    python "$SCRIPT_DIR/04_post_build_metrics.py" --config "$CONFIG" &
    PIDS+=($!)
else
    echo "=== Step 04: SKIPPED ==="
fi

if [[ -z "${SKIP[05]+x}" ]]; then
    python "$SCRIPT_DIR/05_preprocessed_size.py" --config "$CONFIG" &
    PIDS+=($!)
else
    echo "=== Step 05: SKIPPED ==="
fi

if [[ -z "${SKIP[06]+x}" ]]; then
    python "$SCRIPT_DIR/06_ninja_log.py" --config "$CONFIG" &
    PIDS+=($!)
else
    echo "=== Step 06: SKIPPED ==="
fi

# Wait for all parallel steps
fail=0
for pid in "${PIDS[@]}"; do
    wait "$pid" || fail=1
done
if (( fail )); then
    echo "=== One or more of steps 04/05/06 FAILED ===" >&2
    exit 1
fi

echo ""
echo "=== Collection complete in $(( SECONDS - TOTAL_START ))s ==="
