"""Tests for buildanalysis.compiler_timing — GCC and Clang ftime-report parsers."""

import pytest

from buildanalysis.compiler_timing import (
    ClangTimingParser,
    CompilerTimingReport,
    GccTimingParser,
    PhaseTimings,
    detect_and_parse,
)

# ---------------------------------------------------------------------------
# GCC fixture
# ---------------------------------------------------------------------------

SAMPLE_GCC_FTIME_REPORT = """\
Time variable                                   usr           sys          wall               GGC
 phase setup                                :   0.00 (  0%)   0.00 (  0%)   0.00 (  0%)    1363 kB (  1%)
 phase parsing                              :   0.12 ( 14%)   0.01 ( 25%)   0.13 ( 14%)    8027 kB ( 10%)
 phase lang. deferred                       :   0.01 (  1%)   0.00 (  0%)   0.01 (  1%)     116 kB (  0%)
 phase opt and generate                     :   0.72 ( 85%)   0.03 ( 75%)   0.72 ( 84%)   68433 kB ( 89%)
 TOTAL                                      :   0.85          0.04          0.86           76939 kB
"""

# ---------------------------------------------------------------------------
# Clang fixture (trimmed — only the "Clang time report" section)
# ---------------------------------------------------------------------------

SAMPLE_CLANG_FTIME_REPORT = """\
===-------------------------------------------------------------------------===
                        Analysis execution timing report
===-------------------------------------------------------------------------===
  Total Execution Time: 0.0014 seconds (0.0022 wall clock)

   ---User Time---   --System Time--   --User+System--   ---Wall Time---  ---Instr---  --- Name ---
   0.0010 (100.0%)   0.0004 (100.0%)   0.0014 (100.0%)   0.0022 (100.0%)   23741447  Total

===-------------------------------------------------------------------------===
                          Pass execution timing report
===-------------------------------------------------------------------------===
  Total Execution Time: 0.0343 seconds (0.0473 wall clock)

   ---User Time---   --System Time--   --User+System--   ---Wall Time---  ---Instr---  --- Name ---
   0.0271 (100.0%)   0.0072 (100.0%)   0.0343 (100.0%)   0.0473 (100.0%)  473633141  Total

===-------------------------------------------------------------------------===
                               Clang time report
===-------------------------------------------------------------------------===
  Total Execution Time: 0.5937 seconds (0.9737 wall clock)

   ---User Time---   --System Time--   --User+System--   ---Wall Time---  ---Instr---  --- Name ---
   0.3994 ( 87.9%)   0.0785 ( 56.3%)   0.4779 ( 80.5%)   0.8108 ( 83.3%)  2488600454  Front end
   0.0407 (  9.0%)   0.0566 ( 40.6%)   0.0973 ( 16.4%)   0.1399 ( 14.4%)  640977354  Machine code generation
   0.0119 (  2.6%)   0.0013 (  1.0%)   0.0132 (  2.2%)   0.0167 (  1.7%)  112863610  LLVM IR generation
   0.0022 (  0.5%)   0.0030 (  2.2%)   0.0052 (  0.9%)   0.0062 (  0.6%)   45679213  Optimizer
   0.4542 (100.0%)   0.1395 (100.0%)   0.5937 (100.0%)   0.9737 (100.0%)  3288120631  Total

"""


# ---------------------------------------------------------------------------
# GCC parser tests
# ---------------------------------------------------------------------------


class TestGccTimingParser:
    def setup_method(self):
        self.parser = GccTimingParser()

    def test_can_parse_gcc(self):
        assert self.parser.can_parse(SAMPLE_GCC_FTIME_REPORT)

    def test_cannot_parse_clang(self):
        assert not self.parser.can_parse(SAMPLE_CLANG_FTIME_REPORT)

    def test_extracts_phases(self):
        report = self.parser.parse(SAMPLE_GCC_FTIME_REPORT)
        assert report is not None
        assert "phase parsing" in report.phases
        assert "phase opt and generate" in report.phases
        assert "phase setup" in report.phases

    def test_compiler_is_gcc(self):
        report = self.parser.parse(SAMPLE_GCC_FTIME_REPORT)
        assert report is not None
        assert report.compiler == "gcc"

    def test_phase_wall_times(self):
        report = self.parser.parse(SAMPLE_GCC_FTIME_REPORT)
        assert report is not None
        assert report.phases["phase parsing"].wall == 0.13
        assert report.phases["phase opt and generate"].wall == 0.72

    def test_phase_usr_sys_times(self):
        report = self.parser.parse(SAMPLE_GCC_FTIME_REPORT)
        assert report is not None
        assert report.phases["phase parsing"].usr == 0.12
        assert report.phases["phase parsing"].sys == 0.01

    def test_total(self):
        report = self.parser.parse(SAMPLE_GCC_FTIME_REPORT)
        assert report is not None
        assert report.total.usr == 0.85
        assert report.total.sys == 0.04
        assert report.total.wall == 0.86
        assert report.wall_total_ms == 860

    def test_total_not_in_phases(self):
        report = self.parser.parse(SAMPLE_GCC_FTIME_REPORT)
        assert report is not None
        assert "TOTAL" not in report.phases

    def test_empty_input(self):
        assert self.parser.parse("") is None

    def test_noise_input(self):
        assert self.parser.parse("some random stderr output\nwarning: something\n") is None


# ---------------------------------------------------------------------------
# Clang parser tests
# ---------------------------------------------------------------------------


class TestClangTimingParser:
    def setup_method(self):
        self.parser = ClangTimingParser()

    def test_can_parse_clang(self):
        assert self.parser.can_parse(SAMPLE_CLANG_FTIME_REPORT)

    def test_cannot_parse_gcc(self):
        assert not self.parser.can_parse(SAMPLE_GCC_FTIME_REPORT)

    def test_compiler_is_clang(self):
        report = self.parser.parse(SAMPLE_CLANG_FTIME_REPORT)
        assert report is not None
        assert report.compiler == "clang"

    def test_extracts_phases(self):
        report = self.parser.parse(SAMPLE_CLANG_FTIME_REPORT)
        assert report is not None
        assert "frontend" in report.phases
        assert "codegen" in report.phases
        assert "ir_generation" in report.phases
        assert "optimizer" in report.phases

    def test_phase_count(self):
        report = self.parser.parse(SAMPLE_CLANG_FTIME_REPORT)
        assert report is not None
        assert len(report.phases) == 4

    def test_phase_wall_times(self):
        report = self.parser.parse(SAMPLE_CLANG_FTIME_REPORT)
        assert report is not None
        assert report.phases["frontend"].wall == 0.8108
        assert report.phases["codegen"].wall == 0.1399
        assert report.phases["ir_generation"].wall == 0.0167
        assert report.phases["optimizer"].wall == 0.0062

    def test_phase_usr_sys_times(self):
        report = self.parser.parse(SAMPLE_CLANG_FTIME_REPORT)
        assert report is not None
        assert report.phases["frontend"].usr == 0.3994
        assert report.phases["frontend"].sys == 0.0785

    def test_total(self):
        report = self.parser.parse(SAMPLE_CLANG_FTIME_REPORT)
        assert report is not None
        assert report.total.usr == 0.4542
        assert report.total.sys == 0.1395
        assert report.total.wall == 0.9737
        assert report.wall_total_ms == 973

    def test_only_parses_clang_time_report_section(self):
        """Ensure Analysis and Pass sections are not included in phases."""
        report = self.parser.parse(SAMPLE_CLANG_FTIME_REPORT)
        assert report is not None
        # These are from the Analysis section, not the Clang time report
        assert "AAManager" not in report.phases
        assert "TargetIRAnalysis" not in report.phases

    def test_empty_input(self):
        assert self.parser.parse("") is None


# ---------------------------------------------------------------------------
# Auto-detection tests
# ---------------------------------------------------------------------------


class TestDetectAndParse:
    def test_detects_gcc(self):
        report = detect_and_parse(SAMPLE_GCC_FTIME_REPORT)
        assert report is not None
        assert report.compiler == "gcc"

    def test_detects_clang(self):
        report = detect_and_parse(SAMPLE_CLANG_FTIME_REPORT)
        assert report is not None
        assert report.compiler == "clang"

    def test_returns_none_for_empty(self):
        assert detect_and_parse("") is None

    def test_returns_none_for_noise(self):
        assert detect_and_parse("In file included from /usr/include/stdio.h:1:\nwarning: unused variable") is None


# ---------------------------------------------------------------------------
# Serialisation round-trip tests
# ---------------------------------------------------------------------------


class TestCompilerTimingReportSerialisation:
    def test_gcc_round_trip(self):
        report = detect_and_parse(SAMPLE_GCC_FTIME_REPORT)
        assert report is not None
        d = report.to_dict()
        restored = CompilerTimingReport.from_dict(d)
        assert restored.compiler == report.compiler
        assert restored.total == report.total
        assert restored.wall_total_ms == report.wall_total_ms
        assert set(restored.phases.keys()) == set(report.phases.keys())
        for name in report.phases:
            assert restored.phases[name] == report.phases[name]

    def test_clang_round_trip(self):
        report = detect_and_parse(SAMPLE_CLANG_FTIME_REPORT)
        assert report is not None
        d = report.to_dict()
        restored = CompilerTimingReport.from_dict(d)
        assert restored.compiler == report.compiler
        assert restored.total == report.total
        assert restored.wall_total_ms == report.wall_total_ms
        assert set(restored.phases.keys()) == set(report.phases.keys())

    def test_to_dict_structure(self):
        report = detect_and_parse(SAMPLE_GCC_FTIME_REPORT)
        assert report is not None
        d = report.to_dict()
        assert d["compiler"] == "gcc"
        assert isinstance(d["phases"], dict)
        assert isinstance(d["total"], dict)
        assert "usr" in d["total"]
        assert "sys" in d["total"]
        assert "wall" in d["total"]
        assert isinstance(d["wall_total_ms"], int)


# ---------------------------------------------------------------------------
# PhaseTimings tests
# ---------------------------------------------------------------------------


class TestPhaseTimings:
    def test_frozen(self):
        t = PhaseTimings(usr=1.0, sys=0.5, wall=1.5)
        with pytest.raises(AttributeError):
            t.usr = 2.0  # type: ignore[misc]

    def test_equality(self):
        a = PhaseTimings(usr=1.0, sys=0.5, wall=1.5)
        b = PhaseTimings(usr=1.0, sys=0.5, wall=1.5)
        assert a == b
