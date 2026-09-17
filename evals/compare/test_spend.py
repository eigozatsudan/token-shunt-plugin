"""The stop half of a cost cap.

A cap written in a pre-registration is not a stop rule until the loop that
spends measures spend and exits. On 2026-09-17 a $30 cap ran to $36.55
because seventy runs went out as one loop with no checkpoint
(reviews/scope-interleaved-2026-09-17.md section 6).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SPEND = Path(__file__).parent / "spend.py"


class SpendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def transcript(self, run, name, *costs, junk=False):
        d = self.root / run / "transcripts"
        d.mkdir(parents=True, exist_ok=True)
        rows = []
        if junk:
            rows.append("not json at all")
        for c in costs:
            rows.append(json.dumps({"type": "result", "total_cost_usd": c}))
        (d / name).write_text("\n".join(rows) + "\n")

    def spend(self, *args):
        return subprocess.run([sys.executable, str(SPEND), *args],
                              capture_output=True, text=True)

    def test_each_transcript_counts_only_its_last_total(self):
        # A stream-json transcript reports a running total; summing every row
        # would count the same spend several times over.
        self.transcript("run.a", "case.jsonl", 0.1, 0.25, 0.5)
        result = self.spend(str(self.root))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertAlmostEqual(0.5, float(result.stdout.strip()))

    def test_transcripts_and_runs_add_up(self):
        self.transcript("run.a", "case.jsonl", 0.5)
        self.transcript("run.a", "probe.jsonl", 0.25)
        self.transcript("run.b", "case.jsonl", 1.0)
        result = self.spend(str(self.root))
        self.assertAlmostEqual(1.75, float(result.stdout.strip()))

    def test_a_transcript_without_a_cost_contributes_nothing(self):
        self.transcript("run.a", "case.jsonl", 0.5)
        (self.root / "run.a" / "transcripts" / "empty.jsonl").write_text(
            json.dumps({"type": "system"}) + "\n")
        result = self.spend(str(self.root))
        self.assertAlmostEqual(0.5, float(result.stdout.strip()))

    def test_a_broken_line_does_not_stop_the_count(self):
        # A truncated transcript is exactly when the caller needs the number.
        self.transcript("run.a", "case.jsonl", 0.5, junk=True)
        result = self.spend(str(self.root))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertAlmostEqual(0.5, float(result.stdout.strip()))

    def test_nothing_spent_is_zero_not_an_error(self):
        result = self.spend(str(self.root))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertAlmostEqual(0.0, float(result.stdout.strip()))

    def test_under_the_cap_exits_zero(self):
        self.transcript("run.a", "case.jsonl", 0.5)
        self.assertEqual(0, self.spend("--cap", "1.0", str(self.root)).returncode)

    def test_reaching_the_cap_exits_nonzero(self):
        # At the cap, not past it: the next run would cross it.
        self.transcript("run.a", "case.jsonl", 1.0)
        result = self.spend("--cap", "1.0", str(self.root))
        self.assertEqual(3, result.returncode)
        self.assertIn("cap", result.stderr.lower())
        self.assertAlmostEqual(1.0, float(result.stdout.strip()))

    def test_over_the_cap_exits_nonzero(self):
        self.transcript("run.a", "case.jsonl", 1.5)
        self.assertEqual(3, self.spend("--cap", "1.0", str(self.root)).returncode)

    def test_a_reserve_stops_one_run_before_the_cap(self):
        # The check runs BEFORE a run, so a bare cap overshoots by up to one
        # run: $1.0868 went out against a $1.0 cap on 2026-09-17
        # (reviews/pairs-tool-trial-2026-09-17.md section 3). The reserve is
        # what the next run is expected to cost.
        self.transcript("r1", "a.jsonl", 0.80)
        self.assertEqual(0, self.spend("--cap", "1.0", str(self.root)).returncode)
        result = self.spend("--cap", "1.0", "--reserve", "0.25", str(self.root))
        self.assertEqual(3, result.returncode)
        self.assertIn("0.25", result.stderr)

    def test_a_reserve_that_still_fits_exits_zero(self):
        self.transcript("r1", "a.jsonl", 0.50)
        self.assertEqual(0, self.spend("--cap", "1.0", "--reserve", "0.25",
                                       str(self.root)).returncode)

    def test_the_boundary_stops(self):
        # total + reserve == cap: the run would land exactly on the cap, and
        # the bare cap already treats landing on it as a stop.
        self.transcript("r1", "a.jsonl", 0.75)
        self.assertEqual(3, self.spend("--cap", "1.0", "--reserve", "0.25",
                                       str(self.root)).returncode)

    def test_a_reserve_over_the_whole_cap_stops_before_anything_is_spent(self):
        # Nothing spent yet and one run cannot fit: starting is the mistake.
        result = self.spend("--cap", "0.20", "--reserve", "0.25", str(self.root))
        self.assertEqual(3, result.returncode)

    def test_the_printed_total_is_the_spend_not_the_reserve(self):
        # The number on stdout is what has been spent; the reserve only
        # decides the exit code.
        self.transcript("r1", "a.jsonl", 0.80)
        result = self.spend("--cap", "1.0", "--reserve", "0.25", str(self.root))
        self.assertEqual("0.8000", result.stdout.splitlines()[0])

    def test_the_options_may_come_in_either_order(self):
        self.transcript("r1", "a.jsonl", 0.80)
        self.assertEqual(3, self.spend("--reserve", "0.25", "--cap", "1.0",
                                       str(self.root)).returncode)

    def test_a_reserve_without_a_cap_is_a_usage_error(self):
        # A reserve decides nothing on its own, and silently ignoring it
        # would leave the caller believing it had a stop rule.
        result = self.spend("--reserve", "0.25", str(self.root))
        self.assertEqual(2, result.returncode)
        self.assertIn("cap", result.stderr.lower())

    def test_a_reserve_that_is_not_a_positive_number_is_a_usage_error(self):
        for bad in ("abc", "0", "-1"):
            with self.subTest(bad=bad):
                result = self.spend("--cap", "1.0", "--reserve", bad,
                                    str(self.root))
                self.assertEqual(2, result.returncode)

    def test_a_reserve_with_no_value_is_a_usage_error(self):
        self.assertEqual(2, self.spend("--cap", "1.0", "--reserve").returncode)

    def test_a_cap_that_is_not_a_positive_number_is_a_usage_error(self):
        # Distinct from the over-cap code, so a typo cannot read as "stop".
        for bad in ("nonsense", "-1", "0"):
            with self.subTest(bad=bad):
                result = self.spend("--cap", bad, str(self.root))
                self.assertEqual(2, result.returncode)

    def test_a_missing_directory_is_a_usage_error(self):
        result = self.spend(str(self.root / "gone"))
        self.assertEqual(2, result.returncode)

    def test_several_roots_are_summed(self):
        # Two arms live in two checkouts; the cap is over both.
        self.transcript("t/run.a", "case.jsonl", 1.0)
        self.transcript("c/run.a", "case.jsonl", 2.0)
        result = self.spend(str(self.root / "t"), str(self.root / "c"))
        self.assertAlmostEqual(3.0, float(result.stdout.strip()))


if __name__ == "__main__":
    unittest.main()
