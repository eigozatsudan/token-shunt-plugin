"""Would Lock B have fired on the conversations already measured?

Design: docs/superpowers/specs/2026-09-19-cumulative-intake-design.md 3.1,
which picked 16,384 bytes because 1 of 14 archived auto conversations went
over it and 13 never came close. That table was computed from
`parent_bytes.py` sums; this replays the archived transcripts through the
shipped `intake_ledger` itself, read by read, at $0.

It composes two modules and parses nothing of its own: `read_rows` for what
the parent read, `intake_ledger.deny_reason` for the verdict.

What it cannot answer: what the conversation would have done next. A denied
read changes the turns after it, and the archive holds the conversation
that was not denied. So the replay charges the bytes the transcript really
took, and a deny is a flag on that read, never a rewrite of the history.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'plugin' / 'hooks'))
import intake_replay  # noqa: E402


def rows(*items):
    return "\n".join(json.dumps(i) for i in items) + "\n"


def use(uid, path, **inp):
    body = {"file_path": path}
    body.update({k: v for k, v in inp.items() if v is not None})
    return {"type": "assistant", "parent_tool_use_id": None,
            "message": {"content": [
                {"type": "tool_use", "id": uid, "name": "Read", "input": body}]}}


def result(uid, text):
    return {"type": "user", "parent_tool_use_id": None,
            "message": {"content": [
                {"type": "tool_result", "tool_use_id": uid, "content": text}]}}


class ReplayTests(unittest.TestCase):
    ROOT = "/run/work/fixtures"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def turn(self, number, *items):
        name = ("c.auto.jsonl" if number == 1
                else "c.auto.jsonl.turn%d.jsonl" % number)
        (self.dir / name).write_text(rows(*items))

    def read(self, uid, size, **inp):
        return (use(uid, self.ROOT + "/%s.py" % uid, **inp),
                result(uid, "x" * size))

    def replay(self, budget=16384):
        return intake_replay.replay(self.dir, "c", "auto", self.ROOT, budget)

    def test_a_conversation_that_stays_small_never_fires(self):
        self.turn(1)
        self.turn(2, *self.read("a", 8000))
        got = self.replay()
        self.assertEqual([], got["denied"])
        self.assertIsNone(got["first_deny_turn"])
        self.assertEqual(8000, got["total_bytes"])

    def test_the_read_after_the_crossing_one_is_denied(self):
        # The crossing read itself passes: PreToolUse cannot measure what is
        # about to come back without estimating it (spec 2).
        self.turn(1)
        self.turn(2, *self.read("a", 10000))
        self.turn(3, *self.read("b", 12000))
        self.turn(4, *self.read("c", 8000))
        got = self.replay()
        self.assertEqual(4, got["first_deny_turn"])
        self.assertEqual([self.ROOT + "/c.py"], got["denied"])

    def test_the_archive_is_not_rewritten_after_a_deny(self):
        # The conversation really did take those bytes; the replay says what
        # the lock would have refused, not what would have happened next.
        self.turn(1)
        self.turn(2, *self.read("a", 20000))
        self.turn(3, *self.read("b", 5000))
        got = self.replay()
        self.assertEqual(25000, got["total_bytes"])
        self.assertEqual(5000, got["bytes_after_first_deny"])

    def test_a_targeted_read_is_charged_and_never_denied(self):
        self.turn(1)
        self.turn(2, *self.read("a", 20000))
        self.turn(3, *self.read("b", 5000, offset=10, limit=50))
        got = self.replay()
        self.assertEqual([], got["denied"])
        self.assertEqual(25000, got["total_bytes"])

    def test_every_turn_is_reported_even_when_nothing_was_read(self):
        self.turn(1)
        self.turn(2, *self.read("a", 100))
        got = self.replay()
        self.assertEqual([1, 2], [t["turn"] for t in got["turns"]])
        self.assertEqual([0, 100], [t["bytes"] for t in got["turns"]])

    def test_a_budget_of_zero_fires_nothing(self):
        self.turn(1, *self.read("a", 99999))
        got = self.replay(budget=0)
        self.assertEqual([], got["denied"])
        self.assertEqual(99999, got["total_bytes"])

    def test_the_replay_leaves_no_state_behind(self):
        # It runs against the shipped hook, so it must not write into the
        # ledger a live session would use.
        before = sorted(Path(tempfile.gettempdir()).glob('token-shunt-intake-*'))
        self.turn(1, *self.read("a", 20000))
        self.turn(2, *self.read("b", 5000))
        self.replay()
        self.assertEqual(
            before, sorted(Path(tempfile.gettempdir()).glob('token-shunt-intake-*')))

    def test_the_sum_matches_the_instrument_it_reuses(self):
        self.turn(1, *self.read("a", 4000))
        self.turn(2, *self.read("b", 6000))
        got = self.replay()
        import parent_turn_reads
        counted = parent_turn_reads.conversation(self.dir, "c", "auto", self.ROOT)
        self.assertEqual(counted["total_bytes"], got["total_bytes"])
        self.assertEqual(counted["total_reads"], got["total_reads"])


if __name__ == '__main__':
    unittest.main()
