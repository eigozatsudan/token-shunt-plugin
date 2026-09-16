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
