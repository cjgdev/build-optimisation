#!/bin/bash
# Wraps a compiler invocation, capturing stderr to a per-file log.
# Usage: CMAKE_CXX_COMPILER_LAUNCHER=<path/to/capture_stderr.sh>
# The wrapper receives the compiler and all arguments.

OUTPUT_DIR="${BUILD_OPTIMISER_STDERR_DIR:-.}"
COMPILER="$1"
shift

# Derive a log filename from the source file argument
SOURCE_FILE=""
for arg in "$@"; do
    if [[ "$arg" == *.cpp || "$arg" == *.cc || "$arg" == *.cxx ]]; then
        SOURCE_FILE="$arg"
        break
    fi
done

if [ -z "$SOURCE_FILE" ]; then
    # No source file found, just run the compiler normally
    "$COMPILER" "$@"
    exit $?
fi

LOG_FILE="${OUTPUT_DIR}/$(echo "$SOURCE_FILE" | tr '/' '_').stderr"
"$COMPILER" "$@" 2> "$LOG_FILE"
EXIT_CODE=$?
exit $EXIT_CODE
