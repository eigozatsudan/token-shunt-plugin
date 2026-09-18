"""The stop half of a retry cap.

A driver that retries until a run completes has no bound on how many times
it may fail to complete one. On 2026-09-17 the CLI was down for about an
hour and the driver kept retrying, leaving 450 run directories with no
summary.json (reviews/django-dose-2026-09-17.md section 7.2). It cost
$0.0000 that day because the failures happened before the model was
reached -- which is luck, not a bound. This is the bound.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROGRESS = Path(__file__).parent / "progress.py"

OVER_CAP = 3
USAGE = 2


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_dir(self, name, summary=True, body=None, root=None):
        """One run directory, with or without the summary that ends a run."""
        d = (root or self.root) / name
        (d / "work").mkdir(parents=True, exist_ok=True)
        if summary:
            d.joinpath("summary.json").write_text(
                json.dumps({"cases": {}}) if body is None else body)
        return d

    def progress(self, *args):
        return subprocess.run([sys.executable, str(PROGRESS), *args],
                              capture_output=True, text=True)

    # --- the stop rule ---

    def test_barren_runs_reaching_the_cap_stop_the_loop(self):
        # The failure this tool exists for: runs that produce no summary.
        for i in range(3):
            self.run_dir("run.barren%d" % i, summary=False)
        result = self.progress("--max-barren", "3", str(self.root))
        self.assertEqual(result.returncode, OVER_CAP, result.stderr)

    def test_barren_runs_under_the_cap_let_the_loop_continue(self):
        for i in range(2):
            self.run_dir("run.barren%d" % i, summary=False)
        result = self.progress("--max-barren", "3", str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_finished_runs_never_count_against_the_cap(self):
        # 450 finished runs must not read as 450 failures.
        for i in range(5):
            self.run_dir("run.done%d" % i)
        result = self.progress("--max-barren", "1", str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_without_a_cap_nothing_stops(self):
        # Reporting the numbers is useful on its own; a stop needs a cap.
        for i in range(9):
            self.run_dir("run.barren%d" % i, summary=False)
        result = self.progress(str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)

    # --- what counts as barren ---

    def test_a_half_written_summary_counts_as_barren(self):
        # A run killed mid-write leaves a file that json cannot load. Reading
        # it as finished would hide exactly the failure being capped.
        self.run_dir("run.truncated", body='{"cases": {')
        result = self.progress("--max-barren", "1", str(self.root))
        self.assertEqual(result.returncode, OVER_CAP, result.stderr)

    def test_a_summary_that_is_not_an_object_counts_as_barren(self):
        # run.sh only copies a summary forward when it parses as an object.
        self.run_dir("run.list", body="[]")
        result = self.progress("--max-barren", "1", str(self.root))
        self.assertEqual(result.returncode, OVER_CAP, result.stderr)

    def test_loose_files_in_the_root_are_not_runs(self):
        self.root.joinpath("last-run.json").write_text("{}")
        self.run_dir("run.done0")
        result = self.progress("--max-barren", "1", str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["1", "0"])

    # --- what it reports ---

    def test_it_prints_finished_then_barren(self):
        self.run_dir("run.done0")
        self.run_dir("run.done1")
        self.run_dir("run.barren0", summary=False)
        result = self.progress(str(self.root))
        self.assertEqual(result.stdout.split(), ["2", "1"])

    def test_several_roots_are_summed(self):
        # A measurement that interleaves two cases keeps two run roots; the
        # cap is on the measurement, not on either root.
        first, second = self.root / "first", self.root / "second"
        first.mkdir()
        second.mkdir()
        self.run_dir("run.done0", root=first)
        self.run_dir("run.barren0", summary=False, root=second)
        result = self.progress(str(first), str(second))
        self.assertEqual(result.stdout.split(), ["1", "1"])

    # --- usage errors are their own exit code ---

    def test_a_missing_directory_is_a_usage_error(self):
        result = self.progress("--max-barren", "3",
                               str(self.root / "absent"))
        self.assertEqual(result.returncode, USAGE, result.stdout)
        self.assertIn("not a directory", result.stderr)

    def test_a_cap_with_no_value_is_a_usage_error(self):
        result = self.progress("--max-barren")
        self.assertEqual(result.returncode, USAGE, result.stdout)
        self.assertIn("usage: progress.py", result.stderr)

    def test_a_cap_that_is_not_a_number_is_a_usage_error(self):
        # A mistyped cap must not be read as "no cap" and run forever.
        result = self.progress("--max-barren", "ten", str(self.root))
        self.assertEqual(result.returncode, USAGE, result.stdout)
        self.assertIn("max-barren", result.stderr)

    def test_a_cap_of_zero_is_a_usage_error(self):
        # Zero would stop before the first run, which is never what was meant.
        result = self.progress("--max-barren", "0", str(self.root))
        self.assertEqual(result.returncode, USAGE, result.stdout)
        self.assertIn("positive", result.stderr)

    def test_no_directory_is_a_usage_error(self):
        result = self.progress("--max-barren", "3")
        self.assertEqual(result.returncode, USAGE, result.stdout)
        self.assertIn("usage: progress.py", result.stderr)

    def test_over_cap_is_not_the_usage_code(self):
        # The two must stay distinguishable: a mistyped cap and a real stop
        # are opposite instructions to the driver.
        self.run_dir("run.barren0", summary=False)
        stop = self.progress("--max-barren", "1", str(self.root))
        bad = self.progress("--max-barren", "-1", str(self.root))
        self.assertIn("positive", bad.stderr)
        self.assertEqual(stop.returncode, OVER_CAP)
        self.assertEqual(bad.returncode, USAGE)
        self.assertNotEqual(stop.returncode, bad.returncode)


if __name__ == "__main__":
    unittest.main()
