"""The retention probe measures one thing: did the parent keep the paths?

Pre-registered instrument for the check-worker-launch effect run
(reviews/launch-reminder-effect-design-2026-09-16.md). `gold_confirmed`
only notices a lost path when a gold item rides on it; this asks the
narrower question directly, over every worker line the run produced.
"""
import json
from pathlib import Path
import tempfile
import unittest

import retention_probe as rp


def transcript(worker_text, final_text, hook_output=None):
    """A minimal delegate-run stream-json transcript."""
    events = [
        {"type": "system", "subtype": "init", "plugins": [{"name": "token-shunt"}]},
        {"type": "assistant", "uuid": "u1", "parent_tool_use_id": None,
         "message": {"id": "m1", "content": [
             {"type": "tool_use", "id": "t1", "name": "Agent",
              "input": {"subagent_type": "token-shunt:bulk-reader",
                        "model": "haiku", "prompt": "q"}}]}},
        {"type": "user", "uuid": "u2", "parent_tool_use_id": None,
         "message": {"content": [
             {"type": "tool_result", "tool_use_id": "t1",
              "content": worker_text}]}},
        {"type": "assistant", "uuid": "u3", "parent_tool_use_id": None,
         "message": {"id": "m2", "content": [
             {"type": "text", "text": final_text}]}},
        {"type": "result", "uuid": "u4", "parent_tool_use_id": None,
         "subtype": "success", "result": final_text},
    ]
    if hook_output is not None:
        events.insert(2, {"type": "system", "subtype": "hook_response",
                          "hook_name": "PostToolUse:Agent",
                          "output": hook_output})
    return events


class ScoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.file = self.root / 'kept.rb'
        self.file.write_text('x = 1\n')
        self.line = 'confirmed: %s — User includes Notifiable' % self.file

    def write(self, name, events):
        path = self.root / name
        path.write_text('\n'.join(json.dumps(e) for e in events))
        return path

    def test_a_kept_line_is_not_an_abbreviation(self):
        path = self.write('a.jsonl', transcript(
            self.line, 'Here it is.\n' + self.line))
        got = rp.score_transcript(path)
        self.assertEqual(got['status'], 'ok')
        self.assertEqual(got['lost'], [])
        self.assertFalse(got['abbreviated'])

    def test_a_basename_in_place_of_the_path_is_the_failure_measured(self):
        path = self.write('b.jsonl', transcript(
            self.line, 'confirmed: kept.rb — User includes Notifiable'))
        got = rp.score_transcript(path)
        self.assertEqual(got['status'], 'violation')
        self.assertEqual(got['lost'], [str(self.file)])
        self.assertTrue(got['abbreviated'])

    def test_a_run_with_no_worker_line_is_undetermined_not_clean(self):
        # A run that never delegated says nothing about retention, and
        # counting it as a pass would inflate the treated arm.
        path = self.write('c.jsonl', transcript(
            'no items here', 'Some prose answer.'))
        got = rp.score_transcript(path)
        self.assertEqual(got['status'], 'undetermined')
        self.assertFalse(got['abbreviated'])

    def test_a_missing_file_is_undetermined_not_a_violation(self):
        gone = self.root / 'gone.rb'
        path = self.write('d.jsonl', transcript(
            'confirmed: %s — fact' % gone, 'summary only'))
        self.assertEqual(rp.score_transcript(path)['status'], 'undetermined')

    def test_the_reminder_is_seen_when_the_hook_answered(self):
        payload = json.dumps({'hookSpecificOutput': {
            'hookEventName': 'PostToolUse',
            'additionalContext': 'token-shunt: this worker returns ...'}})
        path = self.write('e.jsonl', transcript(
            self.line, self.line, hook_output=payload))
        self.assertTrue(rp.score_transcript(path)['reminder_hook'])
        path = self.write('f.jsonl', transcript(self.line, self.line))
        self.assertFalse(rp.score_transcript(path)['reminder_hook'])

    def test_delivery_is_reported_apart_from_the_hook_answering(self):
        # The hook returning a payload and the CLI putting it in the
        # parent's context are two claims. The arm is only treated if the
        # second one holds, so they are counted separately.
        payload = json.dumps({'hookSpecificOutput': {
            'hookEventName': 'PostToolUse',
            'additionalContext': 'token-shunt: this worker returns ...'}})
        events = transcript(self.line, self.line, hook_output=payload)
        got = rp.score_transcript(self.write('g.jsonl', events))
        self.assertFalse(got['reminder_delivered'])
        events.insert(3, {"type": "user", "parent_tool_use_id": None,
                          "message": {"content": [
                              {"type": "text",
                               "text": "token-shunt: this worker returns ..."}]}})
        got = rp.score_transcript(self.write('h.jsonl', events))
        self.assertTrue(got['reminder_delivered'])


class ScoreDirTests(unittest.TestCase):
    def test_a_run_directory_is_summed_by_slot(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'transcripts').mkdir()
        (root / 'verdicts').mkdir()
        target = root / 'user.rb'
        target.write_text('x\n')
        line = 'confirmed: %s — fact' % target
        (root / 'transcripts' / 'compare-explicit-multifile.haiku.jsonl').write_text(
            '\n'.join(json.dumps(e) for e in transcript(line, 'confirmed: user.rb — fact')))
        (root / 'verdicts' / 'compare-explicit-multifile.haiku.json').write_text(
            json.dumps({'verdict': 'fail', 'metrics': {'total_cost_usd': 0.2}}))
        got = rp.score_dir(root)
        self.assertEqual(got['runs'], 1)
        self.assertEqual(got['abbreviated'], 1)
        self.assertEqual(got['measured'], 1)
        self.assertEqual(got['cost'], 0.2)
        self.assertEqual(got['slots']['compare-explicit-multifile/haiku'][0]['status'],
                         'violation')

    def test_a_trial_log_beside_a_transcript_is_not_a_run(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'transcripts').mkdir()
        (root / 'transcripts' / 'x.haiku.jsonl.sendback.jsonl').write_text('{}\n')
        self.assertEqual(rp.score_dir(root)['runs'], 0)


if __name__ == '__main__':
    unittest.main()
