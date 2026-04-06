"""Compiler timing report parsers for GCC and Clang -ftime-report output.

Provides a strategy pattern with auto-detection to parse timing reports from
either compiler into a normalised ``CompilerTimingReport`` structure.

Usage::

    from buildanalysis.compiler_timing import detect_and_parse

    report = detect_and_parse(stderr_text)
    if report is not None:
        print(report.compiler, report.total.wall)
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PhaseTimings:
    """Timing breakdown for a single compiler phase (seconds)."""

    usr: float
    sys: float
    wall: float


@dataclass(frozen=True, slots=True)
class CompilerTimingReport:
    """Normalised timing report produced by any compiler parser."""

    compiler: str  # "gcc" or "clang"
    phases: dict[str, PhaseTimings]  # phase name → timings (excludes total)
    total: PhaseTimings  # overall totals
    wall_total_ms: int  # int(total.wall * 1000), for backward compat

    # -- Serialisation helpers ------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serialisable dict."""
        return {
            "compiler": self.compiler,
            "phases": {name: asdict(t) for name, t in self.phases.items()},
            "total": asdict(self.total),
            "wall_total_ms": self.wall_total_ms,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CompilerTimingReport:
        """Reconstruct from a dict (as stored in ftime_report.json)."""
        phases = {name: PhaseTimings(**t) for name, t in d["phases"].items()}
        total = PhaseTimings(**d["total"])
        return cls(
            compiler=d["compiler"],
            phases=phases,
            total=total,
            wall_total_ms=d["wall_total_ms"],
        )


# ---------------------------------------------------------------------------
# Abstract parser
# ---------------------------------------------------------------------------


class TimingParser(ABC):
    """Strategy interface for compiler-specific timing parsers."""

    @abstractmethod
    def can_parse(self, text: str) -> bool:
        """Return True if *text* contains output this parser can handle."""

    @abstractmethod
    def parse(self, text: str) -> CompilerTimingReport | None:
        """Parse *text* and return a report, or None if parsing fails."""


# ---------------------------------------------------------------------------
# GCC parser
# ---------------------------------------------------------------------------

# GCC -ftime-report phase line:
#   " phase parsing  :  0.12 ( 14%)  0.01 ( 25%)  0.13 ( 14%)  8027 kB ( 10%)"
_GCC_PHASE_RE = re.compile(
    r"^\s*(.+?)\s*:\s+"
    r"(\d+\.\d+)\s+\(\s*\d+%\)\s+"  # usr
    r"(\d+\.\d+)\s+\(\s*\d+%\)\s+"  # sys
    r"(\d+\.\d+)\s+\(\s*\d+%\)\s+"  # wall
    r"(\d+)\s+kB"  # GGC memory
)

# GCC TOTAL line (no percentage columns):
#   " TOTAL  :  0.85  0.04  0.86  76939 kB"
_GCC_TOTAL_RE = re.compile(
    r"^\s*TOTAL\s*:\s+"
    r"(\d+\.\d+)\s+"  # usr
    r"(\d+\.\d+)\s+"  # sys
    r"(\d+\.\d+)\s+"  # wall
)

# Header line that precedes GCC timing data.
_GCC_HEADER_RE = re.compile(r"^\s*Time variable\b")


class GccTimingParser(TimingParser):
    """Parse GCC ``-ftime-report`` output."""

    def can_parse(self, text: str) -> bool:
        return bool(_GCC_HEADER_RE.search(text))

    def parse(self, text: str) -> CompilerTimingReport | None:
        phases: dict[str, PhaseTimings] = {}
        total: PhaseTimings | None = None

        for line in text.splitlines():
            total_match = _GCC_TOTAL_RE.match(line)
            if total_match:
                total = PhaseTimings(
                    usr=float(total_match.group(1)),
                    sys=float(total_match.group(2)),
                    wall=float(total_match.group(3)),
                )
                continue

            match = _GCC_PHASE_RE.match(line)
            if match:
                name = match.group(1).strip()
                phases[name] = PhaseTimings(
                    usr=float(match.group(2)),
                    sys=float(match.group(3)),
                    wall=float(match.group(4)),
                )

        if total is None and not phases:
            return None

        if total is None:
            total = PhaseTimings(usr=0.0, sys=0.0, wall=0.0)

        return CompilerTimingReport(
            compiler="gcc",
            phases=phases,
            total=total,
            wall_total_ms=int(total.wall * 1000),
        )


# ---------------------------------------------------------------------------
# Clang parser
# ---------------------------------------------------------------------------

# Section banner that delimits Clang timing blocks.
_CLANG_SECTION_BANNER_RE = re.compile(r"^===[-=]+===$")

# Section title line (centred text between banners).
_CLANG_SECTION_TITLE_RE = re.compile(r"^\s+(.+?)\s*$")

# Clang timing data row (6 columns):
#   "   0.3994 ( 87.9%)   0.0785 ( 56.3%)   0.4779 ( 80.5%)   0.8108 ( 83.3%)  2488600454  Front end"
_CLANG_ROW_RE = re.compile(
    r"^\s*"
    r"(\d+\.\d+)\s+\(\s*[\d.]+%\)\s+"  # usr
    r"(\d+\.\d+)\s+\(\s*[\d.]+%\)\s+"  # sys
    r"(\d+\.\d+)\s+\(\s*[\d.]+%\)\s+"  # usr+sys (skip)
    r"(\d+\.\d+)\s+\(\s*[\d.]+%\)\s+"  # wall
    r"\d+\s+"  # instr count (skip)
    r"(.+?)\s*$"  # name
)

# Clang top-level summary header.
_CLANG_TIME_REPORT_TITLE = "Clang time report"


class ClangTimingParser(TimingParser):
    """Parse Clang ``-ftime-report`` output (top-level summary section)."""

    def can_parse(self, text: str) -> bool:
        return _CLANG_TIME_REPORT_TITLE in text

    def parse(self, text: str) -> CompilerTimingReport | None:
        section_lines = self._extract_section(text, _CLANG_TIME_REPORT_TITLE)
        if section_lines is None:
            return None

        phases: dict[str, PhaseTimings] = {}
        total: PhaseTimings | None = None

        for line in section_lines:
            match = _CLANG_ROW_RE.match(line)
            if not match:
                continue

            usr = float(match.group(1))
            sys_ = float(match.group(2))
            wall = float(match.group(4))
            name = match.group(5)

            if name == "Total":
                total = PhaseTimings(usr=usr, sys=sys_, wall=wall)
            else:
                normalised = self._normalise_phase_name(name)
                phases[normalised] = PhaseTimings(usr=usr, sys=sys_, wall=wall)

        if total is None and not phases:
            return None

        if total is None:
            total = PhaseTimings(usr=0.0, sys=0.0, wall=0.0)

        return CompilerTimingReport(
            compiler="clang",
            phases=phases,
            total=total,
            wall_total_ms=int(total.wall * 1000),
        )

    @staticmethod
    def _extract_section(text: str, title: str) -> list[str] | None:
        """Return lines belonging to the named ``===---===`` section."""
        lines = text.splitlines()
        in_section = False
        section_lines: list[str] = []

        i = 0
        while i < len(lines):
            if _CLANG_SECTION_BANNER_RE.match(lines[i]):
                # Check if the next non-empty line is our title.
                if i + 1 < len(lines):
                    title_match = _CLANG_SECTION_TITLE_RE.match(lines[i + 1])
                    if title_match and title_match.group(1) == title:
                        # Skip the banner, title, closing banner.
                        i += 3 if (i + 2 < len(lines) and _CLANG_SECTION_BANNER_RE.match(lines[i + 2])) else i + 2
                        in_section = True
                        continue
                    elif in_section:
                        # Hit the start of a different section — stop.
                        break
            if in_section:
                section_lines.append(lines[i])
            i += 1

        return section_lines if section_lines else None

    @staticmethod
    def _normalise_phase_name(name: str) -> str:
        """Map Clang phase names to short canonical keys."""
        mapping = {
            "Front end": "frontend",
            "Machine code generation": "codegen",
            "LLVM IR generation": "ir_generation",
            "Optimizer": "optimizer",
        }
        return mapping.get(name, name.lower().replace(" ", "_"))


# ---------------------------------------------------------------------------
# Auto-detection entry point
# ---------------------------------------------------------------------------

_PARSERS: list[TimingParser] = [GccTimingParser(), ClangTimingParser()]


def detect_and_parse(text: str) -> CompilerTimingReport | None:
    """Auto-detect the compiler and parse its ``-ftime-report`` output.

    Tries each registered parser in order and returns the first successful
    result, or *None* if no parser matches.
    """
    for parser in _PARSERS:
        if parser.can_parse(text):
            result = parser.parse(text)
            if result is not None:
                return result
    return None
