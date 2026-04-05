#!/bin/zsh
# consolidate_all.sh — Run all consolidation scripts in dependency order with parallelism.
# Usage: ./scripts/consolidate_all.sh [--config path/to/config.yaml]

set -euo pipefail

CONFIG="config.yaml"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)
            CONFIG="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

CONSOLIDATE_DIR="$(cd "$(dirname "$0")" && pwd)/consolidate"
TOTAL_START=$SECONDS

trap 'echo "Consolidation FAILED at step in progress"; exit 1' ERR

# Tier 1: no inter-script dependencies (parallel)
echo "=== Tier 1: schedule, edge list, file metrics, contributor metrics ==="
TIER1_PIDS=()
python "$CONSOLIDATE_DIR/build_schedule.py" --config "$CONFIG" &
TIER1_PIDS+=($!)
python "$CONSOLIDATE_DIR/build_edge_list.py" --config "$CONFIG" &
TIER1_PIDS+=($!)
python "$CONSOLIDATE_DIR/build_file_metrics.py" --config "$CONFIG" &
TIER1_PIDS+=($!)
python "$CONSOLIDATE_DIR/build_contributor_metrics.py" --config "$CONFIG" &
TIER1_PIDS+=($!)
fail=0; for pid in "${TIER1_PIDS[@]}"; do wait "$pid" || fail=1; done; if (( fail )); then echo "=== Tier 1 FAILED ===" >&2; exit 1; fi
echo "=== Tier 1 complete ==="

# Tier 2: requires file_metrics.parquet
echo "=== Tier 2: target metrics ==="
python "$CONSOLIDATE_DIR/build_target_metrics.py" --config "$CONFIG"
echo "=== Tier 2 complete ==="

# Tier 3: requires file_metrics.parquet + target_metrics.parquet
echo "=== Tier 3: header edges ==="
python "$CONSOLIDATE_DIR/build_header_edges.py" --config "$CONFIG"
echo "=== Tier 3 complete ==="

echo ""
echo "=== Consolidation complete in $(( SECONDS - TOTAL_START ))s ==="
