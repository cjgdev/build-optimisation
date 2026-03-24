#!/bin/bash
# Orchestration script for all data collection steps.
# Usage:
#   ./scripts/collect_all.sh                        # Run all steps
#   ./scripts/collect_all.sh --skip 02 --skip 08    # Skip specific steps

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COLLECT_DIR="${SCRIPT_DIR}/collect"

# Parse --skip arguments
SKIP=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip)
            SKIP+=("$2")
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "Usage: $0 [--skip STEP_NUMBER]..." >&2
            exit 1
            ;;
    esac
done

should_skip() {
    local step="$1"
    for s in "${SKIP[@]}"; do
        if [[ "$s" == "$step" ]]; then
            return 0
        fi
    done
    return 1
}

run_step() {
    local step_num="$1"
    local script="$2"
    local desc="$3"

    if should_skip "$step_num"; then
        echo "=== SKIPPING Step ${step_num}: ${desc} ==="
        return 0
    fi

    echo ""
    echo "================================================================"
    echo "=== Step ${step_num}: ${desc}"
    echo "================================================================"
    local start_time=$(date +%s)

    python3 "${COLLECT_DIR}/${script}"

    local end_time=$(date +%s)
    local elapsed=$((end_time - start_time))
    echo "=== Step ${step_num} completed in ${elapsed}s ==="
}

echo "Build Optimiser — Data Collection"
echo "================================="
echo "Start time: $(date)"
echo ""

TOTAL_START=$(date +%s)

run_step "01" "01_dependency_graph.py" "Dependency Graph (CMake Graphviz)"
run_step "02" "02_compile_times.py"    "Compile Times (-ftime-report)"
run_step "03" "03_object_files.py"     "Object File Sizes"
run_step "04" "04_sloc.py"             "Source Lines of Code"
run_step "05" "05_git_history.py"      "Git Change History"
run_step "06" "06_header_depth.py"     "Header Inclusion Depth"
run_step "07" "07_preprocessed_size.py" "Preprocessed Output Size"
run_step "08" "08_link_times.py"       "Link Times"

TOTAL_END=$(date +%s)
TOTAL_ELAPSED=$((TOTAL_END - TOTAL_START))

echo ""
echo "================================================================"
echo "=== All collection steps completed in ${TOTAL_ELAPSED}s ==="
echo "================================================================"

echo ""
echo "Running consolidation..."
echo ""

python3 "${SCRIPT_DIR}/consolidate/build_file_metrics.py"
python3 "${SCRIPT_DIR}/consolidate/build_target_metrics.py"
python3 "${SCRIPT_DIR}/consolidate/build_edge_list.py"

echo ""
echo "Data collection and consolidation complete."
echo "Processed data written to data/processed/"
