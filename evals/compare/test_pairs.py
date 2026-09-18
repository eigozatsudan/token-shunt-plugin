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
        self.assertEqual(row["direct_accuracy"], "1")
        self.assertEqual(row["auto_accuracy"], "1")
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
                         "direct_accuracy,auto_accuracy,"
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

    def test_the_plain_accuracy_check_is_used_when_there_is_no_accuracy_any(self):
        # Cases declare accuracy_any, or accuracy, or neither. Reading only
        # the first drops a fact the run did record; reporting 0/20 that way
        # has already happened once
        # (reviews/fence-prevalence-design-2026-09-17.md, section 11.2).
        d, _ = self.run_dir("run.aaa", "c1")
        (d / "summary.json").write_text(json.dumps(
            {"cases": {"c1": {"modes": {
                "direct": {"checks": {"accuracy": True}, "reasons": []},
                "auto": {"checks": {"accuracy": False}, "reasons": []}}}}}))
        self.transcript(d, "c1", "direct")
        self.transcript(d, "c1", "auto")
        row = self.rows(self.pairs(str(self.runs)).stdout)[0]
        self.assertEqual(row["direct_accuracy"], "1")
        self.assertEqual(row["auto_accuracy"], "0")

    def test_accuracy_any_wins_when_a_case_declares_both(self):
        d, _ = self.run_dir("run.aaa", "c1")
        (d / "summary.json").write_text(json.dumps(
            {"cases": {"c1": {"modes": {
                "direct": {"checks": {"accuracy_any": True, "accuracy": False},
                           "reasons": []},
                "auto": {"checks": {"accuracy_any": True, "accuracy": False},
                         "reasons": []}}}}}))
        self.transcript(d, "c1", "direct")
        self.transcript(d, "c1", "auto")
        self.assertEqual(self.rows(self.pairs(str(self.runs)).stdout)[0]
                         ["direct_accuracy"], "1")

    def test_a_case_declaring_neither_accuracy_check_is_blank_not_zero(self):
        # An absent check and a failed one are different facts, and a row
        # that calls the first a zero cannot be told from the second later.
        d, _ = self.run_dir("run.aaa", "c1")
        (d / "summary.json").write_text(json.dumps(
            {"cases": {"c1": {"modes": {"direct": {"checks": {}, "reasons": []},
                                        "auto": {"checks": {}, "reasons": []}}}}}))
        self.transcript(d, "c1", "direct")
        self.transcript(d, "c1", "auto")
        row = self.rows(self.pairs(str(self.runs)).stdout)[0]
        self.assertEqual(row["direct_accuracy"], "")


class SelectionTests(PairsFixture):
    def test_a_directory_with_no_summary_is_skipped(self):
        (self.runs / "run.junk").mkdir()
        got = self.pairs(str(self.runs))
        self.assertEqual(got.returncode, 0)
        self.assertEqual(self.rows(got.stdout), [])

    def test_a_missing_transcript_blanks_that_arm_and_keeps_the_other(self):
        # The arm that ran is still worth keeping; what must not happen is
        # the missing one being written as a zero.
        d, _ = self.run_dir("run.aaa", "c1")
        self.summary(d, "c1")
        self.transcript(d, "c1", "direct")
        got = self.pairs(str(self.runs))
        row = self.rows(got.stdout)[0]
        self.assertEqual(row["direct_pass"], "1")
        self.assertEqual(row["auto_read_bytes"], "")
        self.assertEqual(row["auto_pass"], "")
        self.assertIn("run.aaa", got.stderr)

    def test_a_case_with_no_usable_arm_yields_no_row(self):
        d, _ = self.run_dir("run.aaa", "c1")
        self.summary(d, "c1")
        got = self.pairs(str(self.runs))
        self.assertEqual(got.returncode, 0)
        self.assertEqual(self.rows(got.stdout), [])

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


class SingleArmTests(PairsFixture):
    """A measurement that ran one arm still has rows worth keeping.

    Three measurements in a row ran `MODES=auto` only -- direct has no
    worker, so it cannot answer a question about what the worker reported
    -- and each one had to be scored by a throwaway script because this
    tool dropped every single-armed case
    (reviews/fence-sendback-design-2026-09-17.md section 9,
    reviews/fence-prevalence-design-2026-09-17.md section 9,
    reviews/fence-bait-2026-09-17.md section 8).
    """

    def auto_only(self, name="run.aaa", case="c1", **kw):
        d, fix = self.run_dir(name, case)
        (d / "summary.json").write_text(json.dumps(
            {"cases": {case: {"modes": {"auto": {"checks": {"accuracy_any": True},
                                                 "reasons": list(kw.get("reasons", ()))}}}}}))
        self.transcript(d, case, "auto", **{k: v for k, v in kw.items()
                                            if k != "reasons"})
        return d, fix

    def test_an_auto_only_case_is_a_row(self):
        self.auto_only(costs=[0.3])
        got = self.pairs(str(self.runs))
        self.assertEqual(got.returncode, 0, got.stderr)
        rows = self.rows(got.stdout)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["auto_cost_usd"], "0.3000")
        self.assertEqual(rows[0]["auto_accuracy"], "1")

    def test_the_arm_that_did_not_run_is_blank_not_zero(self):
        # Zero bytes and zero dollars are findings: zero is exactly what a
        # correct auto arm reads. An arm that never ran must not be able to
        # be mistaken for one that ran and read nothing.
        self.auto_only()
        row = self.rows(self.pairs(str(self.runs)).stdout)[0]
        for column in ("direct_read_bytes", "direct_cost_usd",
                       "direct_accuracy", "direct_pass"):
            self.assertEqual(row[column], "", column)

    def test_a_direct_only_case_is_a_row_with_the_auto_columns_blank(self):
        d, _ = self.run_dir("run.aaa", "c1")
        (d / "summary.json").write_text(json.dumps(
            {"cases": {"c1": {"modes": {"direct": {"checks": {"accuracy_any": False},
                                                   "reasons": []}}}}}))
        self.transcript(d, "c1", "direct", costs=[0.2])
        row = self.rows(self.pairs(str(self.runs)).stdout)[0]
        self.assertEqual(row["direct_accuracy"], "0")
        self.assertEqual(row["auto_cost_usd"], "")
        self.assertEqual(row["auto_reasons"], "")

    def test_an_auto_only_failure_still_carries_its_reasons(self):
        # This is the column the fence measurements actually needed.
        self.auto_only(reasons=["child_no_body: code fence in child message"])
        row = self.rows(self.pairs(str(self.runs)).stdout)[0]
        self.assertEqual(row["auto_pass"], "0")
        self.assertIn("code fence", row["auto_reasons"])

    def test_the_header_does_not_change_for_a_single_armed_block(self):
        # Both shapes share one schema, so blocks can be compared and a
        # diff of two CSVs stays readable.
        self.auto_only()
        self.assertEqual(self.pairs(str(self.runs)).stdout.splitlines()[0],
                         "run,case,direct_read_bytes,auto_read_bytes,"
                         "direct_cost_usd,auto_cost_usd,"
                         "direct_accuracy,auto_accuracy,"
                         "direct_pass,auto_pass,auto_reasons")

    def test_single_and_paired_cases_can_share_one_block(self):
        self.auto_only(name="run.aaa")
        d, _ = self.run_dir("run.bbb", "c1")
        self.summary(d, "c1")
        self.transcript(d, "c1", "direct")
        self.transcript(d, "c1", "auto")
        rows = self.rows(self.pairs(str(self.runs)).stdout)
        self.assertEqual([r["run"] for r in rows], ["run.aaa", "run.bbb"])
        self.assertEqual(rows[0]["direct_pass"], "")
        self.assertEqual(rows[1]["direct_pass"], "1")

    def test_the_auto_arm_still_counts_only_the_parents_own_reads(self):
        d, fix = self.run_dir("run.aaa", "c1")
        body = "x" * 64
        (d / "summary.json").write_text(json.dumps(
            {"cases": {"c1": {"modes": {"auto": {"checks": {}, "reasons": []}}}}}))
        self.transcript(d, "c1", "auto", reads=[(fix / "f.rb", body)],
                        child_reads=[(fix / "g.rb", "y" * 999)])
        row = self.rows(self.pairs(str(self.runs)).stdout)[0]
        self.assertEqual(row["auto_read_bytes"], "64")


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


class MinimumRowsTests(PairsFixture):
    """The stop half of "keep the rows".

    The tool's own docstring says to run it before the run directories go,
    and a driver that writes `pairs.py -o rows.csv runs && rm -rf runs`
    reads exit 0 as "the rows are kept". Zero rows also exits 0: a header
    and nothing else, which is what losing 88 pairs looked like the first
    time (reviews/redmine-dose-2026-09-17.md). `--min-rows` is how a
    caller says how many it was expecting.
    """

    TOO_FEW = 3

    def one_pair(self, name, case="c1"):
        d, fix = self.run_dir(name, case)
        self.summary(d, case)
        self.transcript(d, case, "direct", costs=[0.01])
        self.transcript(d, case, "auto", costs=[0.02])
        return d

    def test_fewer_rows_than_expected_stops_the_caller(self):
        self.one_pair("run.aaa")
        got = self.pairs("--min-rows", "2", str(self.runs))
        self.assertEqual(got.returncode, self.TOO_FEW, got.stderr)

    def test_no_rows_at_all_stops_the_caller(self):
        # The case the option exists for: everything was skipped and the
        # file holds a header alone.
        (self.runs / "run.junk").mkdir()
        got = self.pairs("--min-rows", "1", str(self.runs))
        self.assertEqual(got.returncode, self.TOO_FEW, got.stderr)

    def test_exactly_the_expected_number_is_enough(self):
        self.one_pair("run.aaa")
        got = self.pairs("--min-rows", "1", str(self.runs))
        self.assertEqual(got.returncode, 0, got.stderr)

    def test_more_rows_than_expected_is_not_an_error(self):
        self.one_pair("run.aaa")
        self.one_pair("run.bbb")
        got = self.pairs("--min-rows", "1", str(self.runs))
        self.assertEqual(got.returncode, 0, got.stderr)

    def test_the_rows_it_did_get_are_still_written(self):
        # Stopping must not also destroy the evidence of how far it got.
        self.one_pair("run.aaa")
        out = self.root / "rows.csv"
        got = self.pairs("--min-rows", "9", "-o", str(out), str(self.runs))
        self.assertEqual(got.returncode, self.TOO_FEW, got.stderr)
        self.assertEqual(len(self.rows(out.read_text())), 1)

    def test_it_says_how_many_it_found_and_how_many_were_wanted(self):
        self.one_pair("run.aaa")
        got = self.pairs("--min-rows", "4", str(self.runs))
        self.assertIn("1", got.stderr)
        self.assertIn("4", got.stderr)

    def test_without_the_option_zero_rows_is_still_success(self):
        # The existing contract: two tests already depend on it.
        (self.runs / "run.junk").mkdir()
        got = self.pairs(str(self.runs))
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(self.rows(got.stdout), [])

    def test_a_minimum_with_no_value_is_a_usage_error(self):
        got = self.pairs("--min-rows")
        self.assertEqual(got.returncode, 2, got.stdout)
        self.assertIn("usage:", got.stderr)

    def test_a_minimum_that_is_not_a_number_is_a_usage_error(self):
        # A mistyped minimum must not be read as "no minimum".
        got = self.pairs("--min-rows", "eighty", str(self.runs))
        self.assertEqual(got.returncode, 2, got.stdout)
        self.assertIn("whole number", got.stderr)

    def test_a_minimum_of_zero_is_a_usage_error(self):
        # Zero asserts nothing, so asking for it is asking for the default
        # while believing a guard is on.
        got = self.pairs("--min-rows", "0", str(self.runs))
        self.assertEqual(got.returncode, 2, got.stdout)
        self.assertIn("positive", got.stderr)

    def test_too_few_is_not_the_usage_code(self):
        self.one_pair("run.aaa")
        short = self.pairs("--min-rows", "2", str(self.runs))
        bad = self.pairs("--min-rows", "-2", str(self.runs))
        self.assertEqual(short.returncode, self.TOO_FEW)
        self.assertEqual(bad.returncode, 2)
        self.assertIn("positive", bad.stderr)
