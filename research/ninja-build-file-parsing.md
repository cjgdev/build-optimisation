# Parsing Ninja build files and CMake's CUSTOM_COMMAND

**No mature Python library exists for parsing `.ninja` build files**, leaving developers to write custom parsers. The Ninja file format is deceptively simple — six declaration types, one escape character (`$`), whitespace-significant scoping — but CMake's `CUSTOM_COMMAND` build statements embed arbitrarily complex shell commands that resist structured extraction. This report details the full Ninja file format specification, how CMake generates `CUSTOM_COMMAND` entries, real-world examples of their complexity, existing tooling, and concrete strategies for building a robust Python parser.

---

## The Ninja file format has exactly six declaration types

A `.ninja` file is a sequence of newline-terminated declarations. Comments start with `#` and extend to end of line. Indentation is significant — indented lines belong to the preceding block. The six declaration types are:

```ninja
# 1. Variable declaration
builddir = build

# 2. Rule declaration
rule cc
  command = gcc $cflags -c $in -o $out
  description = CC $out
  depfile = $out.d
  deps = gcc

# 3. Build statement
build foo.o: cc foo.c | header.h || gen_dir
  cflags = -Wall -O2

# 4. Default target
default myapp

# 5. Pool (concurrency control)
pool link_pool
  depth = 4

# 6. File inclusion
include rules.ninja
subninja subdir/build.ninja
```

**Variables** use `name = value` syntax with immediate expansion on the right-hand side. References use `$name` or `${name}`. The sole exception to immediate expansion: variables inside `rule` blocks expand lazily — when the rule is *used* in a build statement, not when declared. This enables rules to reference `$in`, `$out`, and build-scoped overrides.

**Escaping** uses only the `$` character: `$$` produces a literal dollar sign, `$ ` (dollar-space) produces a literal space in path lists, `$:` produces a literal colon, and `$` followed by a newline is a line continuation (leading whitespace on the next line is stripped).

**Rules** declare a named command template. The only required variable is `command` (passed to `sh -c` on Unix). Optional variables include `description`, `depfile`, `deps` (gcc or msvc), `restat`, `rspfile`/`rspfile_content`, `generator`, and `pool`. Two implicit variables, **`$in`** and **`$out`**, expand to space-separated explicit inputs and outputs respectively.

### Build statement formal syntax

The build statement is the most complex declaration. Its full formal syntax:

```
build <explicit_outputs> [| <implicit_outputs>] : <rule> [<explicit_inputs>] [| <implicit_deps>] [|| <order_only_deps>] [|@ <validations>]
  [variable = value]
  ...
```

The meaning of `|` changes based on position relative to the colon. Before the colon, `|` separates explicit outputs from implicit outputs. After the colon and rule name, `|` separates explicit inputs from implicit dependencies, `||` marks order-only dependencies, and `|@` (since Ninja 1.11) marks validations. **Explicit inputs** appear in `$in` and trigger rebuilds on change. **Implicit dependencies** trigger rebuilds but don't appear in `$in`. **Order-only dependencies** must be built first but don't trigger rebuilds when they change. **Implicit outputs** behave like explicit outputs but don't appear in `$out`.

A complete example decomposed:

```ninja
build output.dll | output.lib : link main.o utils.o | config.h || gen_dir
  ldflags = -shared
```

Here `output.dll` is the explicit output, `output.lib` is an implicit output, `link` is the rule, `main.o utils.o` are explicit inputs, `config.h` is an implicit dependency, and `gen_dir` is an order-only dependency.

---

## How CMake generates CUSTOM_COMMAND in Ninja files

CMake's Ninja generator defines a single shared rule used by all `add_custom_command()` and `add_custom_target()` calls, typically in `CMakeFiles/rules.ninja`:

```ninja
rule CUSTOM_COMMAND
  command = $COMMAND
  description = $DESC
  restat = 1
```

The critical design choice: **the command is not in the rule itself**. The rule delegates to `$COMMAND`, which each build statement overrides. This means every custom command shares one rule with the actual shell command injected per build edge via variable binding. The `restat = 1` flag tells Ninja to re-stat outputs after execution, skipping downstream rebuilds if timestamps didn't change.

For `add_custom_command(OUTPUT ...)`, CMake generates a build statement where outputs come from `OUTPUT` and `BYPRODUCTS`, and dependencies come from `DEPENDS`. For `add_custom_target()`, since there's no real output file, CMake creates a synthetic `.util` target paired with a `phony` alias:

```ninja
build CMakeFiles/mytarget.util: CUSTOM_COMMAND | dep1 || order_dep1
  COMMAND = cd /build/dir && cmake -E echo done && cmake -E touch stamp
  DESC = Running mytarget...
  restat = 1

build mytarget: phony CMakeFiles/mytarget.util
```

CMake also defines a top-level variable `cmake_ninja_workdir` pointing to the build directory, used for implicit output duplicates that allow both relative and absolute path references to the same file.

### Real-world CUSTOM_COMMAND examples from open-source projects

**Simple utility** (Android NDK build):
```ninja
build CMakeFiles/edit_cache.util: CUSTOM_COMMAND
  COMMAND = cd /Users/panchen/Documents/code/git/project/.externalNativeBuild/cmake/debug/arm64-v8a && /Users/panchen/Library/Android/sdk/cmake/3.6.4111459/bin/cmake -E echo No\ interactive\ CMake\ dialog\ available.
  DESC = No interactive CMake dialog available...
  restat = 1
```

**Qt MOC/UIC autogen** with depfile, multiple outputs, implicit outputs, and order-only dependencies:
```ninja
build Hw1_autogen/timestamp Hw1_autogen/mocs_compilation.cpp | ${cmake_ninja_workdir}Hw1_autogen/timestamp ${cmake_ninja_workdir}Hw1_autogen/mocs_compilation.cpp: CUSTOM_COMMAND C$:/Qt/6.2.4/mingw_64/./bin/moc.exe || Hw1_autogen_timestamp_deps
  COMMAND = cmd.exe /C "cd /D C:\Users\Georg\Documents\Hw1 && C:\Qt\Tools\CMake_64\bin\cmake.exe -E cmake_autogen C:/Users/Georg/Documents/Hw1/CMakeFiles/Hw1_autogen.dir/AutogenInfo.json Debug && C:\Qt\Tools\CMake_64\bin\cmake.exe -E touch C:/Users/Georg/Documents/Hw1/Hw1_autogen/timestamp && C:\Qt\Tools\CMake_64\bin\cmake.exe -E cmake_transform_depfile Ninja gccdepfile ..."
  DESC = Automatic MOC and UIC for target Hw1
  depfile = C:/Users/Georg/Documents/Hw1/CMakeFiles/d/626869164546a1cfbcc36b5a048ef5c30e9413f1ad07dd5c4d6a145adcf609e2.d
  restat = 1
```

**Complex shell with pipes, redirections, and deeply escaped quotes** (NixOS/nix, converting SQL to C++ header):
```ninja
build src/libstore/libnixstore.so.p/schema.sql.gen.hh: CUSTOM_COMMAND ../src/libstore/schema.sql | /nix/store/.../bin/bash
  COMMAND = /nix/store/.../bin/bash -c '{$ echo$ '"'"'R"__NIX_STR('"'"'$ &&$ cat$ ../src/libstore/schema.sql$ &&$ echo$ '"'"')__NIX_STR"'"'"';$ }$ >$ "$$1"' _ignored_argv0 src/libstore/libnixstore.so.p/schema.sql.gen.hh
```

**Code generation with Bison** (multiple explicit outputs, implicit dependency on the tool binary):
```ninja
build src/libexpr/parser-tab.cc src/libexpr/parser-tab.hh: CUSTOM_COMMAND ../src/libexpr/parser.y | /nix/store/.../bin/bison
  COMMAND = /nix/store/.../bin/bison -v -o src/libexpr/parser-tab.cc ../src/libexpr/parser.y -d
  description = Generating$ src/libexpr/parser-tab.cc$ with$ a$ custom$ command
```

---

## Why COMMAND fields are so hard to parse

The `COMMAND` variable in `CUSTOM_COMMAND` is a raw shell string, not a structured representation. CMake's translation rules create several layers of complexity that a parser must handle.

**Working directory via `cd && ...`**: CMake's `WORKING_DIRECTORY` parameter translates to `cd /path && ` prepended to the command. On Windows, this becomes `cmd.exe /C "cd /D C:\path && ..."`. The actual tool invocation is buried after this prefix.

**Multiple commands chained with `&&`**: When a CMake custom command has multiple `COMMAND` keywords, they're joined with `&&` into a single shell string. A single `COMMAND` value might contain three or four chained commands: `cd /dir && cmake -E env VAR=val && /usr/bin/tool --flag input && cmake -E touch stamp`. The "real" command could be any of these.

**Runtime interpreter prefixes**: When the tool is a Python script, Java JAR, or similar, the actual executable in the shell command is the runtime, not the tool: `/usr/bin/python3 /path/to/generator.py` or `/usr/bin/java -jar /path/to/protoc-gen.jar`. Identifying the "real" tool requires understanding that `python3` and `java` are interpreters.

**Ninja-level escaping interleaved with shell escaping**: The COMMAND value contains Ninja escapes (`$$` for literal `$`, `$ ` for literal space in certain contexts) that must be resolved *before* attempting shell parsing. The NixOS example above shows `$$1` (Ninja escapes to shell `$1`), `'"'"'` (shell single-quote escaping), and `$ ` (Ninja escaped spaces in the description field) all in one entry.

**CMake `-E` wrapper commands**: CMake frequently wraps operations in its own cross-platform commands: `cmake -E copy`, `cmake -E env VAR=val`, `cmake -E touch`, `cmake -E make_directory`. These appear as chained commands alongside the actual tool invocations and must be recognized and filtered.

---

## Existing Python tooling leaves a significant gap

The landscape of Python tools for parsing Ninja files is sparse. **`ninja_syntax.py`**, the official Python module bundled with Ninja, is **exclusively a writer** — it generates `.ninja` files but cannot read them. Its `expand()` function handles only `$varname` and `$$`, explicitly noting it "doesn't handle the full Ninja variable syntax." The module is available on PyPI as `ninja_syntax` (last updated 2017, version 1.7.2).

**No mature, standalone Python library exists for parsing `.ninja` files.** The most notable tools in other languages are `language-ninja` (Haskell, the most complete parser with AST support and variable resolution) and `ninja-build-parser` (Node.js, a minimal stream-based decomposer that deliberately skips variable expansion). In Python, `depslint` on GitHub contains a Ninja manifest parser used for dependency verification via strace, but it's not a general-purpose library. Tools like `NinjaParser` and `ninjatracing` parse only `.ninja_log` timing files, not build manifests.

The most practical extraction approach, used by most developers today, is **Ninja's built-in `-t` tool commands** invoked via subprocess:

- `ninja -t commands [targets]` — prints fully-expanded shell commands for targets
- `ninja -t targets all` — lists all targets with their rule names (`target: rulename`)
- `ninja -t query target` — shows inputs and outputs for a specific target
- `ninja -t deps target` — shows recorded depfile dependencies (requires prior build)
- `ninja -t graph` — outputs a GraphViz dependency graph
- `ninja -t compdb [rules]` — generates a JSON compilation database (only for compilation rules, not CUSTOM_COMMAND)

These tools leverage Ninja's own C++ parser (a hand-written re2c-based lexer in `src/lexer.in.cc` and `src/manifest_parser.cc`) and handle all escaping, variable expansion, and include resolution correctly.

---

## Building a robust Python parser: strategy and key patterns

A practical Python parser for `.ninja` files targeting CUSTOM_COMMAND extraction should follow a **line-by-line state machine** approach — the same pattern used by Ninja's own parser and the few community tools that exist. The core algorithm:

**Phase 1: Lexing with line continuation resolution.** First pass joins all `$\n` continuations, producing complete logical lines. Strip comments. Track line numbers for error reporting.

**Phase 2: Statement classification and block parsing.** Classify each logical line by its leading keyword (`rule`, `build`, `pool`, `default`, `include`, `subninja`) or as a variable declaration. Indented lines following a `rule` or `build` statement are variable bindings scoped to that block. A state machine tracks the current block context.

**Phase 3: Build statement parsing.** This is the hardest part. Parse the build line left-to-right, handling Ninja path escaping (`$ `, `$:`, `$$`). Split on the `:` to separate outputs from inputs. On the output side, `|` separates explicit from implicit outputs. On the input side, the first token after `:` is the rule name, followed by explicit inputs, then `|` for implicit deps, `||` for order-only deps, and `|@` for validations.

```python
def parse_build_line(line):
    """Parse: build out1 out2 | iout1 : rule in1 in2 | idep1 || odep1"""
    # Remove 'build ' prefix
    rest = line[6:]
    # Split on ' : ' (with proper escape handling)
    outputs_str, rest = split_on_colon(rest)
    # Parse outputs: split on ' | ' for implicit outputs
    explicit_out, implicit_out = split_on_pipe(outputs_str)
    # First token of rest is rule name
    tokens = split_escaped(rest)
    rule_name = tokens[0]
    # Remaining tokens split by | and || 
    explicit_in, implicit_in, order_only = split_inputs(tokens[1:])
    return BuildEdge(explicit_out, implicit_out, rule_name,
                     explicit_in, implicit_in, order_only)
```

**Phase 4: Variable expansion** (if needed). For CUSTOM_COMMAND extraction, this is often unnecessary — CMake writes fully-resolved literal values into build-level `COMMAND` bindings. However, a complete parser must handle the scoping chain: build-edge variables → rule variables → file-level variables → parent scope.

**Phase 5: COMMAND extraction heuristics.** For CUSTOM_COMMAND build edges, extract the `COMMAND` variable and apply heuristic parsing to identify the "real" tool:

```python
import shlex

def extract_real_command(command_str):
    """Extract the actual tool invocation from a CUSTOM_COMMAND string."""
    # First, resolve Ninja escapes
    command_str = command_str.replace('$$', '$')
    
    # Split on ' && ' to get chained commands
    parts = command_str.split(' && ')
    
    # Filter out known wrapper patterns
    real_parts = []
    for part in parts:
        stripped = part.strip()
        # Skip 'cd /path' directory changes
        if stripped.startswith('cd '):
            continue
        # Skip 'cmake -E touch' stamp commands
        if 'cmake -E touch' in stripped or 'cmake -E make_directory' in stripped:
            continue
        # Skip Windows cmd.exe wrapper
        if stripped.startswith('cmd.exe /C'):
            continue
        real_parts.append(stripped)
    
    if not real_parts:
        return parts[-1].strip()  # fallback to last command
    
    # Parse the primary command
    primary = real_parts[0]
    try:
        tokens = shlex.split(primary)
    except ValueError:
        tokens = primary.split()
    
    # Handle 'cmake -E env KEY=VAL real_command' pattern
    if tokens and tokens[0].endswith('cmake') and len(tokens) > 2 and tokens[1] == '-E' and tokens[2] == 'env':
        # Skip past cmake -E env and KEY=VAL pairs
        i = 3
        while i < len(tokens) and '=' in tokens[i]:
            i += 1
        tokens = tokens[i:]
    
    # Handle runtime prefixes (python3, java -jar, etc.)
    interpreters = {'python', 'python3', 'python2', 'java', 'ruby', 'perl', 'node'}
    if tokens:
        exe_basename = os.path.basename(tokens[0])
        if exe_basename in interpreters:
            if exe_basename == 'java' and '-jar' in tokens:
                jar_idx = tokens.index('-jar') + 1
                return tokens[jar_idx] if jar_idx < len(tokens) else tokens[0]
            elif len(tokens) > 1:
                return tokens[1]  # The script is the "real" tool
    
    return tokens[0] if tokens else command_str
```

### Critical edge cases a parser must handle

The parser must correctly handle **escaped spaces in paths** (`path/with$ space/file.o` is a single path), **colons in Windows paths** (`C$:/Users/...`), **the `${cmake_ninja_workdir}` variable** that CMake uses in implicit outputs, **empty input lists** (build statements with no inputs at all), and **the `phony` built-in rule** which has no command. For COMMAND parsing specifically, watch for **Windows `cmd.exe /C "..."` wrappers** where the entire real command is inside quotes, **nested quoting** like the `'"'"'` pattern for single quotes inside single-quoted strings, and **multi-line COMMAND values** that span many physical lines via `$\n` continuation.

---

## Conclusion

The Ninja file format is intentionally minimal — **six declaration types, one escape character, whitespace-significant scoping** — making it feasible to write a parser from scratch. The `build` statement's overloaded `|` separator (meaning implicit outputs before the colon, implicit dependencies after it) is the primary syntactic complexity. CMake's `CUSTOM_COMMAND` rule delegates all command content to per-build-edge `COMMAND` variables, meaning the rule definition itself is trivial but the variable values contain arbitrarily complex shell strings.

For a Python parser, the most reliable architecture combines a **line-by-line state machine** for structural parsing with **heuristic shell decomposition** for COMMAND extraction. The `cd && ... && ... && touch stamp` pattern that CMake generates is predictable enough for regex-based splitting on ` && `, followed by filtering known wrapper patterns (`cd`, `cmake -E touch`, `cmake -E env`). When maximum accuracy is needed for a specific build tree, **`ninja -t commands`** via subprocess remains the most reliable approach since it uses Ninja's own parser with full variable expansion. The absence of a mature Python parsing library represents a genuine gap in the ecosystem — the closest alternatives are Haskell's `language-ninja` (full AST parser) and using Ninja's `-t` tools as a subprocess bridge.