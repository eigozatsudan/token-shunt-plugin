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


def transcript(worker_text, final_text, hook_output=None, session_id=None):
    """A minimal delegate-run stream-json transcript."""
    events = [
        {"type": "system", "subtype": "init", "plugins": [{"name": "token-shunt"}],
         "session_id": session_id},
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

    PAYLOAD = json.dumps({'hookSpecificOutput': {
        'hookEventName': 'PostToolUse',
        'additionalContext': 'token-shunt: this worker returns ...'}})

    def session(self, session_id, delivered):
        """A CLI session file the way the projects directory holds it."""
        directory = self.root / 'sessions' / '-some-cwd'
        directory.mkdir(parents=True, exist_ok=True)
        rows = [{'type': 'user', 'sessionId': session_id, 'message': {}}]
        if delivered:
            rows.append({'type': 'attachment', 'sessionId': session_id,
                         'attachment': {'type': 'hook_additional_context',
                                        'content': ['token-shunt: this worker '
                                                    'returns ...']}})
        (directory / (session_id + '.jsonl')).write_text(
            '\n'.join(json.dumps(r) for r in rows))
        return self.root / 'sessions'

    def test_delivery_is_read_from_the_session_not_the_eval_transcript(self):
        # The eval transcript is stream-json from stdout and carries no
        # attachments, so looking for the text there reported 0 for a
        # reminder that had in fact been delivered
        # (reviews/launch-reminder-effect-2026-09-16.md section 1.1).
        events = transcript(self.line, self.line, hook_output=self.PAYLOAD,
                            session_id='s1')
        path = self.write('g.jsonl', events)
        got = rp.score_transcript(path, sessions=self.session('s1', True))
        self.assertTrue(got['reminder_hook'])
        self.assertIs(got['reminder_delivered'], True)
        got = rp.score_transcript(path, sessions=self.session('s1', False))
        self.assertIs(got['reminder_delivered'], False)

    def test_delivery_is_unmeasured_when_the_session_is_not_there(self):
        # Absent evidence is not evidence of absence: a run whose session
        # file was cleaned up must not be counted as "not delivered".
        events = transcript(self.line, self.line, hook_output=self.PAYLOAD,
                            session_id='s2')
        got = rp.score_transcript(self.write('i.jsonl', events),
                                  sessions=self.root / 'no-sessions-here')
        self.assertIsNone(got['reminder_delivered'])

    def test_a_transcript_naming_no_session_leaves_delivery_unmeasured(self):
        events = transcript(self.line, self.line, hook_output=self.PAYLOAD)
        got = rp.score_transcript(self.write('j.jsonl', events),
                                  sessions=self.session('s3', True))
        self.assertIsNone(got['reminder_delivered'])


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

    def test_an_unmeasured_delivery_is_not_counted_as_delivered(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'transcripts').mkdir()
        (root / 'transcripts' / 'c.haiku.jsonl').write_text('\n'.join(
            json.dumps(e) for e in transcript('no items', 'done')))
        got = rp.score_dir(root, sessions=root / 'absent')
        self.assertEqual(got['reminder_delivered'], 0)
        self.assertEqual(got['reminder_unmeasured'], 1)

    def test_a_runner_probe_is_not_one_of_the_runs(self):
        # `_probe_iso` and `_probe_load` are the runner's own start-up
        # checks, not cases. Counting them inflated `runs` and
        # `undetermined` in the launch-reminder effect record
        # (reviews/launch-reminder-effect-2026-09-16.md section 5).
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'transcripts').mkdir()
        for name in ('_probe_iso.jsonl', '_probe_load.jsonl'):
            (root / 'transcripts' / name).write_text('\n'.join(
                json.dumps(e) for e in transcript('no items', 'done')))
        got = rp.score_dir(root)
        self.assertEqual(got['runs'], 0)
        self.assertEqual(got['undetermined'], 0)
        self.assertEqual(got['slots'], {})

    def test_a_name_that_states_no_mode_is_not_a_run(self):
        # A transcript whose stem carries no `case.mode` split cannot be
        # attributed to a slot, so it is not a unit of this measurement.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'transcripts').mkdir()
        (root / 'transcripts' / 'stray.jsonl').write_text('\n'.join(
            json.dumps(e) for e in transcript('no items', 'done')))
        self.assertEqual(rp.score_dir(root)['runs'], 0)

    def test_a_trial_log_beside_a_transcript_is_not_a_run(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'transcripts').mkdir()
        (root / 'transcripts' / 'x.haiku.jsonl.sendback.jsonl').write_text('{}\n')
        self.assertEqual(rp.score_dir(root)['runs'], 0)


if __name__ == '__main__':
    unittest.main()
