"""The loop that spends, and the three things that stop it.

Every guard this repository has built exists because a loop ran past one:
a $30 cap reached $36.55 with no checkpoint (reviews/scope-interleaved-
2026-09-17.md section 6), an hour of CLI downtime left 450 barren run
directories (reviews/django-dose-2026-09-17.md section 7.2), and a
measurement is only pre-registered if the wording it ran under is the
wording that was registered (reviews/parent-no-read-rate-2026-09-17.md
section 0). The guards are tools; this is the loop that obeys them.

The runner is injected through TS_RUNNER so the loop can be exercised
without a model call.
"""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

DRIVE = Path(__file__).parent / "drive.sh"

STOPPED = 3
USAGE = 2


class DriveFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / "runs"
        self.runs.mkdir()
        self.log = self.root / "runner.log"

    def runner(self, body):
        """A stand-in for run.sh, recording each call in runner.log."""
        path = self.root / "fake-runner.sh"
        path.write_text("#!/usr/bin/env bash\n"
                        'echo call >> "%s"\n' % self.log + body + "\n")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        return str(path)

    def completing_runner(self, cases=("c1", "c2")):
        """Writes a run directory with a summary naming every case."""
        summary = json.dumps({"cases": {c: {"modes": {"auto": {}}} for c in cases}})
        return self.runner(
            'd=$(mktemp -d "%s/run.XXXXXXXX")\n' % self.runs
            + 'mkdir -p "$d/transcripts"\n'
            + "cat > \"$d/summary.json\" <<'EOF'\n" + summary + "\nEOF")

    def barren_runner(self):
        """Fails the way the CLI outage failed: a directory and nothing in it."""
        return self.runner('mktemp -d "%s/run.XXXXXXXX" >/dev/null\nexit 1'
                           % self.runs)

    def calls(self):
        if not self.log.exists():
            return 0
        return len(self.log.read_text().split())

    def drive(self, *args, runner=None, env=None):
        environ = dict(os.environ)
        if runner:
            environ["TS_RUNNER"] = runner
        environ.update(env or {})
        return subprocess.run(["bash", str(DRIVE), *args],
                              capture_output=True, text=True, env=environ)


class TargetTests(DriveFixture):
    def test_it_runs_until_the_target_is_reached(self):
        got = self.drive("--pairs", "3", "--runs", str(self.runs),
                         runner=self.completing_runner())
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(self.calls(), 3)

    def test_it_counts_completed_runs_not_directories(self):
        # A run directory is not a measurement; the summary naming the cases
        # is. A driver counting directories would call the target reached
        # after two calls and exit 0; this one runs out its bound instead.
        got = self.drive("--pairs", "2", "--runs", str(self.runs),
                         "--max-barren", "99",
                         runner=self.runner(
                             'mktemp -d "%s/run.XXXXXXXX" >/dev/null' % self.runs))
        self.assertEqual(got.returncode, STOPPED, got.stderr)
        self.assertEqual(self.calls(), 4)

    def test_a_summary_missing_a_case_does_not_count(self):
        # Both arms have to be there: one arm is half a measurement. Nothing
        # here is barren, so only the absolute bound ends this.
        got = self.drive("--pairs", "1", "--runs", str(self.runs),
                         "--cases", "c1,c2", "--max-barren", "3",
                         runner=self.completing_runner(cases=("c1",)))
        self.assertEqual(got.returncode, STOPPED, got.stderr)
        self.assertEqual(self.calls(), 2)

    def test_the_loop_always_has_an_absolute_bound(self):
        # Neither guard fires here: every run leaves a summary, and nothing
        # bills. Without a bound on attempts the loop would never return.
        got = self.drive("--pairs", "5", "--runs", str(self.runs),
                         "--cases", "c1,c2", "--max-runs", "2",
                         runner=self.completing_runner(cases=("c1",)))
        self.assertEqual(got.returncode, STOPPED, got.stderr)
        self.assertEqual(self.calls(), 2)
        self.assertIn("2", got.stderr)


class StopTests(DriveFixture):
    def test_a_runner_that_never_completes_stops_at_the_barren_cap(self):
        # The 450-directory failure. Without this the loop never ends.
        got = self.drive("--pairs", "50", "--runs", str(self.runs),
                         "--max-barren", "4",
                         runner=self.barren_runner())
        self.assertEqual(got.returncode, STOPPED, got.stderr)
        self.assertLessEqual(self.calls(), 4)
        self.assertIn("summary.json", got.stderr)

    def test_the_spend_cap_stops_the_loop(self):
        # Each call bills a transcript; the cap has to end it before target.
        runner = self.runner(
            'd=$(mktemp -d "%s/run.XXXXXXXX")\nmkdir -p "$d/transcripts"\n' % self.runs
            + 'echo \'{"total_cost_usd": 0.5}\' > "$d/transcripts/t.jsonl"\n'
            + 'cat > "$d/summary.json" <<\'EOF\'\n'
            + json.dumps({"cases": {"c1": {}, "c2": {}}}) + "\nEOF")
        got = self.drive("--pairs", "20", "--runs", str(self.runs),
                         "--cap", "1.2", "--reserve", "0.5", runner=runner)
        self.assertEqual(got.returncode, STOPPED, got.stderr)
        self.assertLess(self.calls(), 20)
        self.assertIn("cap", got.stderr)

    def test_a_changed_prompt_stops_the_loop_before_the_next_run(self):
        # A measurement is pre-registered only if the wording it ran under is
        # the wording registered. Editing cases.json mid-block ends it.
        cases = self.root / "cases.json"
        cases.write_text(json.dumps(
            {"cases": [{"id": "c1", "prompt_delegate": "one"},
                       {"id": "c2", "prompt_delegate": "two"}]}))
        runner = self.runner(
            'd=$(mktemp -d "%s/run.XXXXXXXX")\n' % self.runs
            + 'cat > "$d/summary.json" <<\'EOF\'\n'
            + json.dumps({"cases": {"c1": {}, "c2": {}}}) + "\nEOF\n"
            + 'n=$(cat "%s" | wc -l)\n' % self.log
            + 'if [ "$n" -ge 2 ]; then\n'
            + '  printf %%s \'{"cases":[{"id":"c1","prompt_delegate":"CHANGED"},'
              '{"id":"c2","prompt_delegate":"two"}]}\' > "%s"\nfi' % cases)
        got = self.drive("--pairs", "9", "--runs", str(self.runs),
                         "--cases", "c1,c2", "--cases-file", str(cases),
                         runner=runner)
        self.assertEqual(got.returncode, STOPPED, got.stderr)
        self.assertLess(self.calls(), 9)
        self.assertIn("prompt", got.stderr)

    def test_an_unchanged_prompt_never_stops_the_loop(self):
        cases = self.root / "cases.json"
        cases.write_text(json.dumps(
            {"cases": [{"id": "c1", "prompt_delegate": "one"},
                       {"id": "c2", "prompt_delegate": "two"}]}))
        got = self.drive("--pairs", "2", "--runs", str(self.runs),
                         "--cases", "c1,c2", "--cases-file", str(cases),
                         runner=self.completing_runner())
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(self.calls(), 2)


class UsageTests(DriveFixture):
    def test_a_missing_target_is_a_usage_error(self):
        got = self.drive("--runs", str(self.runs),
                         runner=self.completing_runner())
        self.assertEqual(got.returncode, USAGE, got.stdout)

    def test_a_target_that_is_not_a_number_is_a_usage_error(self):
        got = self.drive("--pairs", "many", "--runs", str(self.runs),
                         runner=self.completing_runner())
        self.assertEqual(got.returncode, USAGE, got.stdout)
        self.assertIn("pairs", got.stderr)

    def test_a_reserve_without_a_cap_is_a_usage_error(self):
        # spend.py refuses it; the loop must refuse it too rather than run
        # believing a stop rule is on.
        got = self.drive("--pairs", "1", "--runs", str(self.runs),
                         "--reserve", "0.5", runner=self.completing_runner())
        self.assertEqual(got.returncode, USAGE, got.stdout)

    def test_a_cap_the_guard_rejects_is_a_usage_error_not_a_stop(self):
        # spend.py exits 2 for a mistyped cap and 3 for a real stop. Folding
        # them together is exactly the confusion those codes exist to
        # prevent: the block would look finished because a flag was wrong.
        got = self.drive("--pairs", "3", "--runs", str(self.runs),
                         "--cap", "twenty-one",
                         runner=self.completing_runner())
        self.assertEqual(got.returncode, USAGE, got.stderr)
        self.assertEqual(self.calls(), 0)

    def test_a_reserve_the_guard_rejects_is_a_usage_error_not_a_stop(self):
        got = self.drive("--pairs", "3", "--runs", str(self.runs),
                         "--cap", "21", "--reserve", "lots",
                         runner=self.completing_runner())
        self.assertEqual(got.returncode, USAGE, got.stderr)
        self.assertEqual(self.calls(), 0)

    def test_stopping_is_not_the_usage_code(self):
        stop = self.drive("--pairs", "9", "--runs", str(self.runs),
                          "--max-barren", "2", runner=self.barren_runner())
        bad = self.drive("--pairs", "0", "--runs", str(self.runs),
                         runner=self.completing_runner())
        self.assertEqual(stop.returncode, STOPPED)
        self.assertEqual(bad.returncode, USAGE)


if __name__ == "__main__":
    unittest.main()
