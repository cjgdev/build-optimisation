# How Ninja hashes commands in .ninja_log

**Ninja uses MurmurHash64A with the seed `0xDECAFBADDECAFBAD` to hash the fully-expanded command string — including response file content — and stores it as a lowercase 16-character hex value in the v5 `.ninja_log` format.** The correct join key to correlate `.ninja_log` entries back to `build.ninja` rules is the **output path**, with the command hash serving as a secondary consistency check. This report covers every implementation detail needed to build a production Python parser and build-metrics pipeline.

## The hash is MurmurHash64A with a hardcoded seed

The hashing function lives in `src/build_log.cc` inside an anonymous namespace. It is **MurmurHash2's 64-bit variant** (MurmurHash64A) by Austin Appleby, returning a `uint64_t`. The algorithm parameters are fixed:

- **Seed**: `0xDECAFBADDECAFBAD` (hardcoded, never configurable)
- **Multiplicative constant `m`**: `0xc6a4a7935bd1e995`
- **Bit-shift constant `r`**: `47`

The public entry point is a static method on `BuildLog::LogEntry`:

```cpp
// static
uint64_t BuildLog::LogEntry::HashCommand(StringPiece command) {
    METRIC_RECORD("hash command");
    return MurmurHash64A(command.data(), command.size());
}
```

This is distinct from the hash function Ninja uses for internal hash-map lookups (`rapidhash` for `std::hash<StringPiece>` in `hash_map.h`). Only **MurmurHash64A is used for the `.ninja_log` command hash**. The algorithm processes 8 bytes at a time using `memcpy` into a `uint64_t`, which means it reads in **native byte order** — little-endian on x86/x64, the overwhelmingly common case for build machines. A Python reimplementation must match this byte ordering.

## What exactly gets hashed: the fully-expanded command plus rspfile content

The `RecordCommand` function in `build_log.cc` calls `edge->EvaluateCommand(true)` — the `true` argument is critical. Here is the evaluation pipeline:

```cpp
std::string Edge::EvaluateCommand(const bool incl_rsp_file) const {
  string command = GetBinding("command");
  if (incl_rsp_file) {
    string rspfile_content = GetBinding("rspfile_content");
    if (!rspfile_content.empty())
      command += ";rspfile=" + rspfile_content;
  }
  return command;
}
```

The `GetBinding("command")` call triggers full variable expansion through Ninja's scope chain with **shell escaping** applied (`EdgeEnv::kShellEscape`). Special variables `$in`, `$out`, `$in_newline` are resolved to the shell-escaped, space-separated (or newline-separated) list of explicit input/output paths. All user-defined variables (`$cflags`, `$ldflags`, etc.) are recursively expanded.

The hashed string is therefore: **the fully-expanded shell command, with `;rspfile=<expanded rspfile_content>` appended if a response file is defined**. This is a crucial detail for any Python reimplementation. There is **no normalization whatsoever** — no whitespace trimming, no flag reordering, no path canonicalization within the command string itself. Any byte-level change to the expanded command changes the hash and triggers a rebuild.

The dirty-checking code in `graph.cc` uses the identical call — `edge->EvaluateCommand(/*incl_rsp_file=*/true)` — ensuring the recorded hash and the rebuild-decision hash are always consistent.

## The v5 log format: five tab-separated fields

Every `.ninja_log` file begins with the header `# ninja log v5` followed by a newline. The current version is **v5** (`kCurrentVersion = 5`, `kOldestSupportedVersion = 5`). If Ninja encounters a log older than v5, it discards it and starts fresh. The v5 format was introduced in 2012 when Ninja switched from storing full command text (v4) to hashes, shrinking Chrome's build log from **197 MB to 1.6 MB**.

Each subsequent line contains five tab-separated fields, written by this format string:

```cpp
fprintf(f, "%d\t%d\t%" PRId64 "\t%s\t%" PRIx64 "\n",
        entry.start_time, entry.end_time, (int64_t)entry.restat_mtime,
        entry.output.c_str(), entry.command_hash);
```

| Column | Field | Type | Description |
|--------|-------|------|-------------|
| 1 | `start_time` | decimal int | Milliseconds since Ninja process start when the command began |
| 2 | `end_time` | decimal int | Milliseconds since Ninja process start when the command finished |
| 3 | `restat_mtime` | decimal int64 | Output file mtime; platform-dependent (POSIX epoch-based). Can be **0** for restat rules where output was unchanged |
| 4 | `output` | string | Canonicalized output file path (relative to build dir) |
| 5 | `command_hash` | lowercase hex uint64 | MurmurHash64A of the expanded command string |

A minimal Python parser:

```python
def parse_ninja_log(path):
    entries = {}
    with open(path) as f:
        header = f.readline()
        assert 'ninja log v' in header
        for line in f:
            if line.startswith('#'):
                continue
            parts = line.rstrip('\n').split('\t')
            if len(parts) != 5:
                continue
            start, end, mtime, output, cmdhash = parts
            entries[output] = {
                'start_ms': int(start),
                'end_ms': int(end),
                'restat_mtime': int(mtime),
                'output': output,
                'command_hash': cmdhash,  # hex string
                'duration_ms': int(end) - int(start),
            }
    return entries
```

Because the log is **append-only**, the same output path can appear multiple times (once per build invocation). The last entry for each output path is the current one. Running `ninja -t recompact` deduplicates the log, keeping only the latest entry per output.

## Joining .ninja_log to build.ninja: output path is the primary key

The **output path** is the correct and primary join key. Each line in `.ninja_log` stores one output path, which corresponds directly to an output in a `build` statement in `build.ninja`. For multi-output build edges (e.g., a rule that produces both `foo.o` and `foo.d`), Ninja writes **one log line per output**, all sharing the same `start_time`, `end_time`, and `command_hash`.

The recommended production strategy:

- **Parse `.ninja_log`** into a dict keyed by output path, keeping only the last entry per path (as Ninja itself does).
- **Parse `build.ninja`** (or use `ninja -t compdb` for compilation commands) to map output paths to their full commands and rule metadata.
- **Join on canonicalized output path.** Ninja canonicalizes paths (resolving `.` and `..`, collapsing consecutive slashes) before writing them to both `build.ninja` and `.ninja_log`.
- **Verify with command hash** (optional). Recompute `MurmurHash64A(command_bytes)` from the expanded command and compare to the stored hex hash. A mismatch means the `build.ninja` has changed since the logged build.

For grouping multi-output edges into a single logical build step, match entries that share the **same command hash and overlapping start/end times**. The `ninjatracing` tool uses exactly this heuristic.

Three Ninja built-in tools are invaluable for this pipeline:

- `ninja -t commands <target>` — prints the fully-expanded command for a target
- `ninja -t compdb` — generates a JSON compilation database mapping outputs to commands
- `ninja -t compdb -x` — same, but with response file content expanded inline (matching what gets hashed)

## Five edge cases that will break a naive implementation

**Response file content changes the hash.** When a build rule has `rspfile` and `rspfile_content` defined, the hashed command is not just the `command` binding — it has `;rspfile=<expanded_rspfile_content>` appended. If you are computing hashes externally, you must replicate this concatenation exactly. Using `ninja -t compdb -x` gives you the expanded form, but the concatenation format (`;rspfile=` prefix) is Ninja-specific and not what `-t compdb -x` outputs. For hash verification you must reconstruct the exact `;rspfile=` format.

**Phony rules are never logged.** Build edges using the `phony` rule produce no `.ninja_log` entries. If your pipeline expects every `build.ninja` target to have a log entry, filter out phony edges.

**The `restat_mtime` field of 0 is a known gotcha.** When a `restat = 1` rule doesn't modify its output, Ninja can record `mtime = 0`. This is a documented issue (GitHub #2405) and can cause perpetual rebuilds if the sole dependency is a phony target. Your pipeline should treat `restat_mtime = 0` as "output unchanged by this build step," not as a real timestamp.

**Timing is relative, not absolute.** The `start_time` and `end_time` fields are milliseconds since the **Ninja process started**, not epoch timestamps. To convert to wall-clock time, you need the Ninja process start time, which is not recorded in `.ninja_log`. For build-time optimization purposes, the relative durations (`end - start`) and the parallelism profile (overlapping intervals) are what matter.

**The 256 KB line buffer limit is silent.** Ninja's log parser uses a 256 KB read buffer. Lines exceeding this length are silently dropped. In practice this only affects pathological cases, but with very large link commands (especially on Windows with massive rspfile content), it's worth knowing.

## A production-quality Python MurmurHash64A implementation

For hash verification in your pipeline, here is a faithful Python port of Ninja's exact algorithm:

```python
import struct

def murmurhash64a(data: bytes) -> int:
    """Exact reimplementation of Ninja's MurmurHash64A."""
    SEED  = 0xDECAFBADDECAFBAD
    M     = 0xc6a4a7935bd1e995
    R     = 47
    MASK  = 0xFFFFFFFFFFFFFFFF

    h = (SEED ^ ((len(data) * M) & MASK)) & MASK
    # Process 8-byte chunks (little-endian)
    off = 0
    while off + 8 <= len(data):
        k = struct.unpack_from('<Q', data, off)[0]
        k = (k * M) & MASK
        k ^= (k >> R)
        k = (k * M) & MASK
        h = (h ^ k) & MASK
        h = (h * M) & MASK
        off += 8
    # Handle remaining bytes
    remaining = len(data) - off
    for i in range(remaining - 1, -1, -1):
        if i > 0 or remaining == 1:
            pass  # will handle below
    # Tail bytes (match the C switch fallthrough)
    tail = data[off:]
    if len(tail) >= 7: h = (h ^ (tail[6] << 48)) & MASK
    if len(tail) >= 6: h = (h ^ (tail[5] << 40)) & MASK
    if len(tail) >= 5: h = (h ^ (tail[4] << 32)) & MASK
    if len(tail) >= 4: h = (h ^ (tail[3] << 24)) & MASK
    if len(tail) >= 3: h = (h ^ (tail[2] << 16)) & MASK
    if len(tail) >= 2: h = (h ^ (tail[1] << 8))  & MASK
    if len(tail) >= 1:
        h = (h ^ tail[0]) & MASK
        h = (h * M) & MASK
    h ^= (h >> R)
    h = (h * M) & MASK
    h ^= (h >> R)
    return h

# Usage: compare against .ninja_log hash
cmd = b"g++ -MMD -MF foo.o.d -O2 -c foo.cc -o foo.o"
hex_hash = format(murmurhash64a(cmd), 'x')
```

The command string must be encoded as raw bytes (UTF-8 on Linux, matching your system's locale — in practice, ASCII for compiler commands). Pass the **exact** byte sequence that `edge->EvaluateCommand(true)` would produce, including the `;rspfile=...` suffix for response-file rules.

## Conclusion

The `.ninja_log` system is simpler than it first appears but has several non-obvious details that trip up external tooling. The output path is your primary join key — not the command hash. The hash exists for Ninja's internal dirty-checking, but it serves as a powerful consistency signal for your pipeline: if you can reproduce it, you've proven your command expansion matches Ninja's exactly. The two most common mistakes in production parsers are ignoring the response file content in the hash and assuming timestamps are absolute rather than relative to process start. For build-time optimization work with GCC 12 and CMake, the duration (`end_ms - start_ms`) per output is the critical metric, and grouping entries by shared command hash reveals which multi-output rules are bottlenecks in your critical path.