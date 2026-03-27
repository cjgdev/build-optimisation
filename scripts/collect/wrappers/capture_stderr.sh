#!/bin/bash
# scripts/collect/wrappers/capture_stderr.sh
# Wraps a compiler invocation, capturing stderr to a per-file log.
# Injected via CMAKE_CXX_COMPILER_LAUNCHER to capture -ftime-report and -H output.

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
    FILE_HASH=$(printf '%s' "$SOURCE_FILE" | (md5sum 2>/dev/null || md5) | awk '{print substr($1,1,16)}')
    LOG_FILE="${OUTPUT_DIR}/${FILE_HASH}.stderr"
    "$COMPILER" "$@" 2> "$LOG_FILE"
    EXIT_CODE=$?
else
    # Not a compilation (e.g., linking) — don't capture
    "$COMPILER" "$@"
    EXIT_CODE=$?
fi

exit $EXIT_CODE
