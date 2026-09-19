"""Parent corpus Reads across every turn of a conversation, not just turn 1.

`judge.py` reads one transcript per case (design 5.1), so `parent_no_read`
only ever judges turn 1. In the multi-turn block that is the one turn where
the parent never reads the corpus: 0 parent corpus Reads at turn 1 against
21 across turns 2-5, in 10 of 14 conversations
(reviews/multiturn-context-2026-09-18.md section 4-2, corrected 2026-09-19).

This instrument walks the follow-up transcripts run.sh already writes and
says, per conversation, where the parent took the corpus on. It is not part
of the release gate.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
import parent_turn_reads  # noqa: E402


def rows(*items):
    return "\n".join(json.dumps(i) for i in items) + "\n"


def use(uid, path, parent=None, name="Read"):
    return {"type": "assistant", "parent_tool_use_id": parent,
            "message": {"content": [
                {"type": "tool_use", "id": uid, "name": name,
                 "input": {"file_path": path}}]}}


def result(uid, text, parent=None):
    return {"type": "user", "parent_tool_use_id": parent,
            "message": {"content": [
                {"type": "tool_result", "tool_use_id": uid, "content": text}]}}


class TurnFileDiscoveryTests(unittest.TestCase):
    """run.sh writes `<first>.jsonl` then `<first>.jsonl.turnN.jsonl`."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def touch(self, name):
        p = self.dir / name
        p.write_text(rows())
        return p

    def test_the_first_turn_comes_before_the_numbered_ones(self):
        self.touch("c.auto.jsonl.turn3.jsonl")
        self.touch("c.auto.jsonl")
        self.touch("c.auto.jsonl.turn2.jsonl")
        found = parent_turn_reads.turn_files(self.dir, "c", "auto")
        self.assertEqual([1, 2, 3], [n for n, _ in found])

    def test_turns_sort_by_number_not_by_string(self):
        self.touch("c.auto.jsonl")
        for n in (2, 10, 3):
            self.touch("c.auto.jsonl.turn%d.jsonl" % n)
        found = parent_turn_reads.turn_files(self.dir, "c", "auto")
        self.assertEqual([1, 2, 3, 10], [n for n, _ in found])

    def test_a_missing_middle_turn_leaves_a_gap_rather_than_renumbering(self):
        self.touch("c.auto.jsonl")
        self.touch("c.auto.jsonl.turn4.jsonl")
        found = parent_turn_reads.turn_files(self.dir, "c", "auto")
        self.assertEqual([1, 4], [n for n, _ in found])

    def test_another_case_or_mode_is_not_collected(self):
        self.touch("c.auto.jsonl")
        self.touch("c.direct.jsonl")
        self.touch("other.auto.jsonl")
        found = parent_turn_reads.turn_files(self.dir, "c", "auto")
        self.assertEqual(["c.auto.jsonl"], [p.name for _, p in found])

    def test_a_conversation_with_no_first_turn_yields_nothing(self):
        self.touch("c.auto.jsonl.turn2.jsonl")
        self.assertEqual([], parent_turn_reads.turn_files(self.dir, "c", "auto"))


class CorpusReadCountTests(unittest.TestCase):
    ROOT = "/run/work/fixtures"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def write(self, name, text):
        (self.dir / name).write_text(text)

    def scan(self):
        return parent_turn_reads.conversation(self.dir, "c", "auto", self.ROOT)

    def test_a_parent_read_of_a_corpus_file_is_counted_on_its_turn(self):
        self.write("c.auto.jsonl", rows())
        self.write("c.auto.jsonl.turn2.jsonl",
                   rows(use("a", self.ROOT + "/m.py"), result("a", "x" * 40)))
        got = self.scan()
        self.assertEqual({1: 0, 2: 1}, {t["turn"]: t["reads"] for t in got["turns"]})
        self.assertEqual({1: 0, 2: 40}, {t["turn"]: t["bytes"] for t in got["turns"]})

    def test_a_read_issued_inside_the_worker_is_not_the_parents(self):
        self.write("c.auto.jsonl",
                   rows(use("a", self.ROOT + "/m.py", parent="agent-1"),
                        result("a", "x" * 40, parent="agent-1")))
        self.assertEqual(0, self.scan()["total_reads"])

    def test_a_read_outside_the_corpus_root_is_not_counted(self):
        self.write("c.auto.jsonl",
                   rows(use("a", "/run/plugin/hooks/check"), result("a", "x" * 40)))
        self.assertEqual(0, self.scan()["total_reads"])

    def test_the_verdict_fails_when_any_turn_read_the_corpus(self):
        self.write("c.auto.jsonl", rows())
        self.write("c.auto.jsonl.turn2.jsonl",
                   rows(use("a", self.ROOT + "/m.py"), result("a", "x")))
        got = self.scan()
        self.assertFalse(got["clean"])
        self.assertEqual([2], got["dirty_turns"])

    def test_a_conversation_that_never_reads_the_corpus_is_clean(self):
        self.write("c.auto.jsonl", rows())
        self.write("c.auto.jsonl.turn2.jsonl", rows())
        got = self.scan()
        self.assertTrue(got["clean"])
        self.assertEqual([], got["dirty_turns"])

    def test_turn_one_alone_can_hide_a_later_read(self):
        """The failure the instrument exists to catch."""
        self.write("c.auto.jsonl", rows())
        for n in (2, 3, 4):
            self.write("c.auto.jsonl.turn%d.jsonl" % n,
                       rows(use("u%d" % n, self.ROOT + "/f%d.py" % n),
                            result("u%d" % n, "x" * 100)))
        got = self.scan()
        self.assertEqual(0, got["turns"][0]["reads"])
        self.assertEqual(3, got["total_reads"])
        self.assertEqual([2, 3, 4], got["dirty_turns"])

    def test_the_paths_the_parent_read_are_reported(self):
        self.write("c.auto.jsonl",
                   rows(use("a", self.ROOT + "/db/m.py"), result("a", "x")))
        self.assertEqual([self.ROOT + "/db/m.py"], self.scan()["paths"])

    def test_a_denied_read_is_not_a_breach(self):
        """A denied Read is the hook working, so nothing entered the parent."""
        deny = {"type": "user", "parent_tool_use_id": None,
                "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "a",
                     "is_error": True, "content": "denied"}]}}
        self.write("c.auto.jsonl", rows(use("a", self.ROOT + "/m.py"), deny))
        got = self.scan()
        self.assertEqual(0, got["total_reads"])
        self.assertTrue(got["clean"])

    def test_a_truncated_line_does_not_stop_the_count(self):
        good = rows(use("a", self.ROOT + "/m.py"), result("a", "x" * 10))
        self.write("c.auto.jsonl", "{not json\n" + good)
        self.assertEqual(1, self.scan()["total_reads"])


class CommandLineTests(unittest.TestCase):
    """Pointing it at five blocks staged under five different roots."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def test_without_root_it_derives_one_and_ignores_the_plugins_own_files(self):
        corpus = "/run/work/fixtures/django/db/m.py"
        (self.dir / "c.auto.jsonl").write_text(
            rows(use("a", "/run/plugin/hooks/reader-call-contract"),
                 result("a", "x" * 999)))
        (self.dir / "c.auto.jsonl.turn2.jsonl").write_text(
            rows(use("b", corpus), result("b", "x" * 40)))
        got = parent_turn_reads.conversation(
            self.dir, "c", "auto",
            parent_turn_reads.derive_root_of(self.dir, "c", "auto"))
        self.assertEqual(1, got["total_reads"])
        self.assertEqual(40, got["total_bytes"])

    def test_a_conversation_touching_no_corpus_derives_no_root(self):
        (self.dir / "c.auto.jsonl").write_text(
            rows(use("a", "/run/plugin/hooks/x"), result("a", "x")))
        self.assertIsNone(
            parent_turn_reads.derive_root_of(self.dir, "c", "auto"))


class RootDerivationTests(unittest.TestCase):
    """Five archived blocks staged fixtures under different absolute roots."""

    def test_the_root_is_derived_from_a_work_fixtures_path(self):
        self.assertEqual(
            "/tmp/ts-multiturn/evals/compare/tmp/runs/run.X/work/fixtures",
            parent_turn_reads.derive_root(
                ["/tmp/ts-multiturn/evals/compare/tmp/runs/run.X/work/"
                 "fixtures/django/db/m.py"]))

    def test_paths_with_no_fixtures_segment_derive_nothing(self):
        self.assertIsNone(parent_turn_reads.derive_root(["/etc/passwd"]))


if __name__ == "__main__":
    unittest.main()
