"""Scoring the follow-up turns judge() never reaches.

Design: docs/superpowers/specs/2026-09-19-multiturn-accuracy-design.md.
judge.py reads one transcript per case (design 5.1), so `parent_no_read`
and `accuracy` judge turn 1 only -- and Lock B's denies land on turns 2-5.
These cover the accuracy half only: the route contracts of turn 1 do not
apply to a second delegation, and nothing here may reach a verdict.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import judge


def transcript(final, worker_replies=()):
    """A minimal parent transcript ending in `final`.

    Each worker reply is a real parent-level Agent launch and its result,
    because that is the only shape `child_return_of` accepts as delivered.
    """
    events = [{"type": "system", "subtype": "init", "cwd": "/w", "plugins": []}]
    for number, reply in enumerate(worker_replies):
        use_id = "agent%d" % number
        events.append({
            "type": "assistant", "parent_tool_use_id": None,
            "message": {"id": "m%d" % number, "content": [{
                "type": "tool_use", "id": use_id, "name": "Agent",
                "input": {"subagent_type": "token-shunt:bulk-reader",
                          "prompt": "read"}}]}})
        events.append({
            "type": "user", "parent_tool_use_id": None,
            "message": {"content": [{
                "type": "tool_result", "tool_use_id": use_id,
                "content": [{"type": "text", "text": reply}]}]}})
    events.append({"type": "result", "result": final})
    return events


def written(events, directory, name):
    path = Path(directory) / name
    path.write_text("".join(json.dumps(e) + "\n" for e in events),
                    encoding="utf-8")
    return str(path)


class GoldTests(unittest.TestCase):
    def test_a_turn_whose_answer_carries_every_gold_misses_none(self):
        with tempfile.TemporaryDirectory() as d:
            path = written(transcript("It raises IrreversibleError here."),
                           d, "t2.jsonl")
            row = judge.judge_turn(path, {"gold_turns": {"2": ["IrreversibleError"]}}, 2)
        self.assertEqual(row["missing"], [])
        self.assertEqual(row["turn"], 2)

    def test_a_missing_gold_is_named(self):
        with tempfile.TemporaryDirectory() as d:
            path = written(transcript("It raises something."), d, "t2.jsonl")
            row = judge.judge_turn(
                path, {"gold_turns": {"2": ["IrreversibleError", "as_string"]}}, 2)
        self.assertEqual(row["missing"], ["IrreversibleError", "as_string"])

    def test_a_turn_with_no_declared_gold_is_recorded_as_unscored(self):
        with tempfile.TemporaryDirectory() as d:
            path = written(transcript("anything"), d, "t5.jsonl")
            row = judge.judge_turn(path, {"gold_turns": {"2": ["x"]}}, 5)
        self.assertIs(row["scored"], False)
        self.assertNotIn("missing", row)

    def test_a_missing_transcript_is_an_error_not_a_missed_gold(self):
        row = judge.judge_turn("/nonexistent/t3.jsonl",
                               {"gold_turns": {"3": ["as_string"]}}, 3)
        self.assertIn("error", row)
        self.assertNotIn("missing", row)


class UnscoredTests(unittest.TestCase):
    """What a turn asked but the substring rule cannot score, said out loud."""

    def test_a_declared_unscored_half_is_carried_into_the_row(self):
        spec = {"prompt_turns": ["a"],
                "gold_turns": {"2": ["IrreversibleError"]},
                "gold_unscored": {"2": ["operation.reversible"]}}
        with tempfile.TemporaryDirectory() as d:
            path = written(transcript("IrreversibleError"), d, "t2.jsonl")
            row = judge.judge_turn(path, spec, 2)
        self.assertEqual(row["unscored"], ["operation.reversible"])
        self.assertEqual(row["missing"], [])

    def test_a_turn_with_nothing_unscored_says_so_with_an_empty_list(self):
        with tempfile.TemporaryDirectory() as d:
            path = written(transcript("as_string"), d, "t3.jsonl")
            row = judge.judge_turn(path, {"gold_turns": {"3": ["as_string"]}}, 3)
        self.assertEqual(row["unscored"], [])

    def test_an_unscored_entry_that_is_also_scored_is_refused(self):
        error = judge.spec_evidence_error({
            "prompt_turns": ["a"],
            "gold_turns": {"2": ["IrreversibleError"]},
            "gold_unscored": {"2": ["IrreversibleError"]}})
        self.assertIsNotNone(error)


class UnscoredWorkerReplyTests(unittest.TestCase):
    """A reply length is not a gold verdict, so an unscored turn keeps it.

    The archived block launched five workers, all of them on turn 5 -- the
    turn with no gold. Dropping the lengths there would hide every contract
    violation that happens in a turn we chose not to score.
    """

    def test_an_unscored_turn_still_records_worker_reply_lengths(self):
        with tempfile.TemporaryDirectory() as d:
            path = written(transcript("anything", ["y" * 4200]), d, "t5.jsonl")
            row = judge.judge_turn(path, {"gold_turns": {"2": ["x"]}}, 5)
        self.assertIs(row["scored"], False)
        self.assertEqual(row["worker_reply_chars"], [4200])
        self.assertNotIn("missing", row)

    def test_an_unscored_turn_with_no_transcript_is_still_an_error(self):
        row = judge.judge_turn("/nonexistent/t5.jsonl",
                               {"gold_turns": {"2": ["x"]}}, 5)
        self.assertIn("error", row)
        self.assertNotIn("worker_reply_chars", row)


class WorkerReplyTests(unittest.TestCase):
    def test_worker_reply_lengths_ride_alongside_the_gold(self):
        with tempfile.TemporaryDirectory() as d:
            path = written(transcript("as_string does it", ["x" * 5770]),
                           d, "t3.jsonl")
            row = judge.judge_turn(path, {"gold_turns": {"3": ["as_string"]}}, 3)
        self.assertEqual(row["missing"], [])
        self.assertEqual(row["worker_reply_chars"], [5770])

    def test_a_turn_without_a_worker_reports_no_lengths(self):
        with tempfile.TemporaryDirectory() as d:
            path = written(transcript("as_string does it"), d, "t3.jsonl")
            row = judge.judge_turn(path, {"gold_turns": {"3": ["as_string"]}}, 3)
        self.assertEqual(row["worker_reply_chars"], [])


class ScanContractTests(unittest.TestCase):
    """The enumeration comes from the declaration, not from the disk."""

    SPEC = {"prompt_turns": ["a", "b"],
            "gold_turns": {"2": ["IrreversibleError"], "3": ["as_string"]}}

    def write(self, directory, turn, final):
        name = ("case.auto.jsonl" if turn == 1
                else "case.auto.jsonl.turn%d.jsonl" % turn)
        written(transcript(final), directory, name)

    def test_every_declared_turn_gets_a_row_even_when_its_file_is_gone(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, 1, "turn one")
            self.write(d, 2, "IrreversibleError")
            rows = judge.judge_turns(d, "case", "auto", self.SPEC)
        self.assertEqual([r["turn"] for r in rows], [2, 3])
        self.assertEqual(rows[0]["missing"], [])
        self.assertEqual(rows[1]["error"], "transcript missing")

    def test_turn_one_is_not_scanned_here(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, 1, "turn one")
            self.write(d, 2, "IrreversibleError")
            self.write(d, 3, "as_string")
            rows = judge.judge_turns(d, "case", "auto", self.SPEC)
        self.assertNotIn(1, [r["turn"] for r in rows])

    def test_a_turn_file_past_the_declaration_is_reported_not_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, 1, "turn one")
            self.write(d, 2, "IrreversibleError")
            self.write(d, 3, "as_string")
            self.write(d, 4, "extra")
            rows = judge.judge_turns(d, "case", "auto", self.SPEC)
        extra = [r for r in rows if r["turn"] == 4]
        self.assertEqual(extra[0]["error"], "undeclared turn file")

    def test_a_declared_turn_without_gold_is_unscored_not_missing(self):
        spec = {"prompt_turns": ["a", "b"], "gold_turns": {"2": ["IrreversibleError"]}}
        with tempfile.TemporaryDirectory() as d:
            self.write(d, 1, "turn one")
            self.write(d, 2, "IrreversibleError")
            self.write(d, 3, "whatever")
            rows = judge.judge_turns(d, "case", "auto", spec)
        self.assertIs(rows[1]["scored"], False)

    def test_a_case_with_no_follow_up_turns_yields_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, 1, "turn one")
            self.assertEqual(judge.judge_turns(d, "case", "auto", {"id": "x"}), [])


class CommandLineTests(unittest.TestCase):
    """run.sh needs one call that prints every declared turn's row."""

    def test_the_turns_mode_prints_a_row_per_declared_turn(self):
        spec = {"prompt_turns": ["a", "b"],
                "gold_turns": {"2": ["IrreversibleError"], "3": ["as_string"]}}
        with tempfile.TemporaryDirectory() as d:
            written(transcript("turn one"), d, "case.auto.jsonl")
            written(transcript("IrreversibleError"), d,
                    "case.auto.jsonl.turn2.jsonl")
            written(transcript("as_string"), d, "case.auto.jsonl.turn3.jsonl")
            spec_path = Path(d) / "spec.json"
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            done = subprocess.run(
                [sys.executable, str(Path(__file__).parent / "judge.py"),
                 "--turns", d, "case", "auto", str(spec_path)],
                capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        rows = json.loads(done.stdout)
        self.assertEqual([r["turn"] for r in rows], [2, 3])
        self.assertEqual([r["missing"] for r in rows], [[], []])

    def test_the_turns_mode_exits_zero_even_when_a_gold_is_missed(self):
        """Recording only: a missed gold must not become a nonzero exit."""
        spec = {"prompt_turns": ["a"], "gold_turns": {"2": ["as_string"]}}
        with tempfile.TemporaryDirectory() as d:
            written(transcript("turn one"), d, "case.auto.jsonl")
            written(transcript("nothing here"), d, "case.auto.jsonl.turn2.jsonl")
            spec_path = Path(d) / "spec.json"
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            done = subprocess.run(
                [sys.executable, str(Path(__file__).parent / "judge.py"),
                 "--turns", d, "case", "auto", str(spec_path)],
                capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)[0]["missing"], ["as_string"])


class SpecValidationTests(unittest.TestCase):
    def test_a_gold_contained_in_another_gold_of_the_same_turn_is_refused(self):
        error = judge.spec_evidence_error({
            "prompt_turns": ["a", "b", "c", "d"],
            "gold_turns": {"2": ["IrreversibleError", "reversible"]}})
        self.assertIsNotNone(error)
        self.assertIn("reversible", error)

    def test_the_same_gold_in_different_turns_is_allowed(self):
        self.assertIsNone(judge.spec_evidence_error({
            "prompt_turns": ["a", "b", "c", "d"],
            "gold_turns": {"2": ["reversible"], "3": ["IrreversibleError"]}}))

    def test_turn_one_belongs_to_judge_and_is_refused_here(self):
        error = judge.spec_evidence_error({
            "prompt_turns": ["a", "b", "c", "d"],
            "gold_turns": {"1": ["show_list"]}})
        self.assertIsNotNone(error)

    def test_a_turn_past_the_declared_prompts_is_refused(self):
        error = judge.spec_evidence_error({
            "prompt_turns": ["a", "b", "c", "d"],
            "gold_turns": {"6": ["show_list"]}})
        self.assertIsNotNone(error)

    def test_an_unnormalised_key_is_refused(self):
        error = judge.spec_evidence_error({
            "prompt_turns": ["a", "b", "c", "d"],
            "gold_turns": {"02": ["show_list"]}})
        self.assertIsNotNone(error)

    def test_gold_turns_without_prompt_turns_is_refused(self):
        self.assertIsNotNone(judge.spec_evidence_error(
            {"gold_turns": {"2": ["show_list"]}}))

    def test_a_declaration_that_is_not_a_list_of_strings_is_refused(self):
        self.assertIsNotNone(judge.spec_evidence_error({
            "prompt_turns": ["a"], "gold_turns": {"2": "show_list"}}))

    def test_the_existing_specs_still_validate(self):
        self.assertIsNone(judge.spec_evidence_error({"id": "x"}))


if __name__ == "__main__":
    unittest.main()
