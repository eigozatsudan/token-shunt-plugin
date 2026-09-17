"""Per-pair numbers, written down before the run directories are deleted.

Reviews keep aggregates. On 2026-09-17 the worktrees holding 88 pairs of
Redmine transcripts were removed after the analysis, and with them any
chance of re-analysing those pairs on a question the review did not ask
(reviews/redmine-dose-2026-09-17.md, reviews/redmine-effect2-2026-09-17.md).
The rows are small; the transcripts are 94 MB. Keep the rows.

The `--root-base` option exists because of a real mistake: run directories
moved aside for a second block kept the old absolute paths inside their
transcripts, so matching by the new location scored every direct arm as
zero bytes -- a plausible-looking number, since zero is also the finding
about the auto arm (that review, section 9).
"""
import csv
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PAIRS = Path(__file__).parent / "pairs.py"


class PairsFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / "runs"
        self.runs.mkdir()

    def run_dir(self, name, case, *, fixtures_at=None):
        """One run directory holding one case in both modes."""
        d = self.runs / name
        (d / "transcripts").mkdir(parents=True)
        fix = Path(fixtures_at or (d / "work" / "fixtures"))
        fix.mkdir(parents=True, exist_ok=True)
        return d, fix

    def summary(self, d, case, *, direct_ok=True, auto_ok=True,
                auto_reasons=()):
        modes = {}
        for mode, ok in (("direct", direct_ok), ("auto", auto_ok)):
            modes[mode] = {"checks": {"accuracy_any": ok},
                           "reasons": list(auto_reasons) if mode == "auto" else []}
        (d / "summary.json").write_text(json.dumps({"cases": {case: {"modes": modes}}}))

    def transcript(self, d, case, mode, *, reads=(), costs=(), child_reads=()):
        """A parent transcript: Reads it issued, Reads a subagent issued, costs."""
        rows = []
        for i, (path, body) in enumerate(reads):
            uid = "tu%d" % i
            rows.append({"message": {"content": [
                {"type": "tool_use", "id": uid, "name": "Read",
                 "input": {"file_path": str(path)}}]}})
            rows.append({"message": {"content": [
                {"type": "tool_result", "tool_use_id": uid, "content": body}]}})
        for i, (path, body) in enumerate(child_reads):
            uid = "ct%d" % i
            rows.append({"parent_tool_use_id": "agent1",
                         "message": {"content": [
                             {"type": "tool_use", "id": uid, "name": "Read",
                              "input": {"file_path": str(path)}}]}})
            rows.append({"parent_tool_use_id": "agent1",
                         "message": {"content": [
                             {"type": "tool_result", "tool_use_id": uid,
                              "content": body}]}})
        for c in costs:
            rows.append({"type": "result", "total_cost_usd": c})
        (d / "transcripts" / ("%s.%s.jsonl" % (case, mode))).write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n")

    def pairs(self, *args):
        return subprocess.run([sys.executable, str(PAIRS), *args],
                              capture_output=True, text=True)

    def rows(self, out):
        return list(csv.DictReader(io.StringIO(out)))


class OutputTests(PairsFixture):
    def test_one_row_per_pair_with_both_arms(self):
        d, fix = self.run_dir("run.aaa", "c1")
        body = "x" * 100
        (fix / "f.rb").write_text(body)
        self.summary(d, "c1")
        self.transcript(d, "c1", "direct", reads=[(fix / "f.rb", body)],
                        costs=[0.01, 0.25])
        self.transcript(d, "c1", "auto", child_reads=[(fix / "f.rb", body)],
                        costs=[0.30])
        got = self.pairs(str(self.runs))
        self.assertEqual(got.returncode, 0, got.stderr)
        rows = self.rows(got.stdout)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["run"], "run.aaa")
        self.assertEqual(row["case"], "c1")
        self.assertEqual(row["direct_read_bytes"], "100")
        # The body the subagent read is what the product keeps out of the
        # parent, so it is not the parent's own intake.
        self.assertEqual(row["auto_read_bytes"], "0")
        self.assertEqual(row["direct_cost_usd"], "0.2500")
        self.assertEqual(row["auto_cost_usd"], "0.3000")
        self.assertEqual(row["direct_accuracy_any"], "1")
        self.assertEqual(row["auto_accuracy_any"], "1")
        self.assertEqual(row["direct_pass"], "1")
        self.assertEqual(row["auto_pass"], "1")

    def test_the_header_is_fixed_so_a_diff_reads(self):
        d, fix = self.run_dir("run.aaa", "c1")
        self.summary(d, "c1")
        self.transcript(d, "c1", "direct")
        self.transcript(d, "c1", "auto")
        got = self.pairs(str(self.runs))
        self.assertEqual(got.stdout.splitlines()[0],
                         "run,case,direct_read_bytes,auto_read_bytes,"
                         "direct_cost_usd,auto_cost_usd,"
                         "direct_accuracy_any,auto_accuracy_any,"
                         "direct_pass,auto_pass,auto_reasons")

    def test_rows_are_sorted_so_the_file_is_stable(self):
        for name in ("run.ccc", "run.aaa", "run.bbb"):
            d, _ = self.run_dir(name, "c1")
            self.summary(d, "c1")
            self.transcript(d, "c1", "direct")
            self.transcript(d, "c1", "auto")
        rows = self.rows(self.pairs(str(self.runs)).stdout)
        self.assertEqual([r["run"] for r in rows],
                         ["run.aaa", "run.bbb", "run.ccc"])

    def test_a_failed_arm_carries_its_reasons(self):
        d, _ = self.run_dir("run.aaa", "c1")
        self.summary(d, "c1", auto_ok=True,
                     auto_reasons=["child_no_body: code fence in child message"])
        self.transcript(d, "c1", "direct")
        self.transcript(d, "c1", "auto")
        row = self.rows(self.pairs(str(self.runs)).stdout)[0]
        self.assertEqual(row["auto_pass"], "0")
        self.assertIn("child_no_body", row["auto_reasons"])

    def test_a_missing_accuracy_check_is_blank_not_zero(self):
        # An absent check and a failed one are different facts, and a row
        # that calls the first a zero cannot be told from the second later.
        d, _ = self.run_dir("run.aaa", "c1")
        (d / "summary.json").write_text(json.dumps(
            {"cases": {"c1": {"modes": {"direct": {"checks": {}, "reasons": []},
                                        "auto": {"checks": {}, "reasons": []}}}}}))
        self.transcript(d, "c1", "direct")
        self.transcript(d, "c1", "auto")
        row = self.rows(self.pairs(str(self.runs)).stdout)[0]
        self.assertEqual(row["direct_accuracy_any"], "")


class SelectionTests(PairsFixture):
    def test_a_case_with_only_one_arm_is_not_a_pair(self):
        d, _ = self.run_dir("run.aaa", "c1")
        (d / "summary.json").write_text(json.dumps(
            {"cases": {"c1": {"modes": {"direct": {"checks": {}, "reasons": []}}}}}))
        self.transcript(d, "c1", "direct")
        got = self.pairs(str(self.runs))
        self.assertEqual(got.returncode, 0)
        self.assertEqual(self.rows(got.stdout), [])

    def test_a_directory_with_no_summary_is_skipped(self):
        (self.runs / "run.junk").mkdir()
        got = self.pairs(str(self.runs))
        self.assertEqual(got.returncode, 0)
        self.assertEqual(self.rows(got.stdout), [])

    def test_a_missing_transcript_drops_the_pair(self):
        d, _ = self.run_dir("run.aaa", "c1")
        self.summary(d, "c1")
        self.transcript(d, "c1", "direct")
        got = self.pairs(str(self.runs))
        self.assertEqual(self.rows(got.stdout), [])
        self.assertIn("run.aaa", got.stderr)

    def test_several_run_roots_are_read_together(self):
        other = self.root / "more"
        other.mkdir()
        for base, name in ((self.runs, "run.aaa"), (other, "run.bbb")):
            d = base / name
            (d / "transcripts").mkdir(parents=True)
            (d / "work" / "fixtures").mkdir(parents=True)
            self.summary(d, "c1")
            self.transcript(d, "c1", "direct")
            self.transcript(d, "c1", "auto")
        rows = self.rows(self.pairs(str(self.runs), str(other)).stdout)
        self.assertEqual([r["run"] for r in rows], ["run.aaa", "run.bbb"])


class RootTests(PairsFixture):
    """Where the corpus is, which is not always where the run directory is."""

    def test_reads_outside_the_fixture_tree_are_not_counted(self):
        d, fix = self.run_dir("run.aaa", "c1")
        (fix / "f.rb").write_text("y" * 10)
        self.summary(d, "c1")
        self.transcript(d, "c1", "direct",
                        reads=[(fix / "f.rb", "y" * 10),
                               ("/etc/hostname", "z" * 999)])
        self.transcript(d, "c1", "auto")
        row = self.rows(self.pairs(str(self.runs)).stdout)[0]
        self.assertEqual(row["direct_read_bytes"], "10")

    def test_root_base_scores_run_directories_that_were_moved(self):
        # The transcripts still name the original location. Scoring against
        # the new one silently returns zero for every arm.
        original = self.root / "original"
        moved = self.root / "moved"
        moved.mkdir()
        d = moved / "run.aaa"
        (d / "transcripts").mkdir(parents=True)
        fix = original / "run.aaa" / "work" / "fixtures"
        fix.mkdir(parents=True)
        self.summary(d, "c1")
        self.transcript(d, "c1", "direct", reads=[(fix / "f.rb", "q" * 42)])
        self.transcript(d, "c1", "auto")

        wrong = self.rows(self.pairs(str(moved)).stdout)[0]
        self.assertEqual(wrong["direct_read_bytes"], "0")

        right = self.rows(self.pairs("--root-base", str(original),
                                     str(moved)).stdout)[0]
        self.assertEqual(right["direct_read_bytes"], "42")


class UsageTests(PairsFixture):
    def test_no_argument_is_a_usage_error(self):
        got = self.pairs()
        self.assertEqual(got.returncode, 2)
        self.assertIn("usage", got.stderr)

    def test_a_missing_directory_is_a_usage_error(self):
        got = self.pairs(str(self.root / "nope"))
        self.assertEqual(got.returncode, 2)

    def test_root_base_without_a_value_is_a_usage_error(self):
        got = self.pairs("--root-base")
        self.assertEqual(got.returncode, 2)

    def test_the_output_can_be_written_to_a_file(self):
        d, _ = self.run_dir("run.aaa", "c1")
        self.summary(d, "c1")
        self.transcript(d, "c1", "direct")
        self.transcript(d, "c1", "auto")
        out = self.root / "block.csv"
        got = self.pairs("-o", str(out), str(self.runs))
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(len(self.rows(out.read_text())), 1)
        self.assertEqual(got.stdout, "")


if __name__ == "__main__":
    unittest.main()
