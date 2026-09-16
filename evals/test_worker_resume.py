"""The parent relaunches a stopped worker; it does not resume one.

Design row 906: a worker that cannot meet the answer contract reports
partial and the parent does not resume it. Rows 447, 908 and 932 say the
same for follow-ups, the shared cap and the A contract. Until now nothing
enforced it, and compare-bulk-facts/auto resumed a turn-limited worker at
9346d19 (reviews/a-suite-failures-9346d19-2026-09-16.md section 3).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HOOKS = Path(__file__).resolve().parent.parent / 'plugin' / 'hooks'
sys.path.insert(0, str(HOOKS))
import worker_resume as wr  # noqa: E402

WORKER = 'token-shunt:bulk-reader'


def session_file(directory, agent_id, agent_type=WORKER, status='completed'):
    path = Path(directory) / 'session.jsonl'
    note = ('<task-notification><task-id>%s</task-id>'
            '<tool-use-id>t1</tool-use-id><status>%s</status>'
            '<result>confirmed: /x — y</result></task-notification>'
            % (agent_id, status))
    rows = [
        {'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'id': 't1', 'name': 'Agent',
             'input': {'subagent_type': agent_type}}]}},
        {'type': 'user', 'message': {'content': note}},
    ]
    path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
    return str(path)


class DecideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def event(self, to, **over):
        event = {'tool_name': 'SendMessage', 'tool_input': {'to': to,
                 'message': 'continue'},
                 'transcript_path': session_file(self.tmp.name, 'a1')}
        event.update(over)
        return event

    def test_a_message_to_a_worker_of_this_session_is_denied(self):
        reason = wr.decide(self.event('a1'))
        self.assertIsNotNone(reason)
        self.assertIn('a1', reason)
        # The deny has to name the move that is allowed, or it strands the
        # parent exactly where resume looked like the way out.
        self.assertIn('new Agent call', reason)
        self.assertIn('partial', reason)

    def test_a_message_to_anything_else_passes(self):
        for target in ('some-teammate', 'a2', '', None, 7):
            with self.subTest(target=target):
                self.assertIsNone(wr.decide(self.event(target)))

    def test_only_token_shunt_workers_are_protected(self):
        event = self.event('a1')
        event['transcript_path'] = session_file(
            self.tmp.name, 'a1', agent_type='some-other:agent')
        self.assertIsNone(wr.decide(event))

    def test_a_worker_that_stopped_at_its_turn_limit_is_still_protected(self):
        # This is the case that actually happened: the worker stops without
        # a report, which is when resume is most tempting.
        event = self.event('a1')
        event['transcript_path'] = session_file(
            self.tmp.name, 'a1', status='failed')
        self.assertIsNotNone(wr.decide(event))

    def test_another_tool_is_not_judged(self):
        self.assertIsNone(wr.decide(self.event('a1', tool_name='Agent')))

    def test_an_unreadable_session_does_not_deny(self):
        # Nothing known means nothing proven. A deny here would block
        # messages this hook cannot show are resumes.
        event = self.event('a1')
        event['transcript_path'] = '/nonexistent/session.jsonl'
        self.assertIsNone(wr.decide(event))
        self.assertIsNone(wr.decide({'tool_name': 'SendMessage',
                                     'tool_input': {'to': 'a1'}}))

    def test_a_broken_session_never_fails_the_turn(self):
        bad = Path(self.tmp.name) / 'bad.jsonl'
        bad.write_text('{not json\n')
        event = self.event('a1')
        event['transcript_path'] = str(bad)
        self.assertIsNone(wr.decide(event))


class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_hook(self, event):
        proc = subprocess.run([str(HOOKS / 'check-worker-resume')],
                              input=json.dumps(event), text=True,
                              capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_the_hook_denies_and_stays_quiet_otherwise(self):
        path = session_file(self.tmp.name, 'a1')
        out = self.run_hook({'tool_name': 'SendMessage',
                             'tool_input': {'to': 'a1', 'message': 'go'},
                             'transcript_path': path})
        payload = json.loads(out)['hookSpecificOutput']
        self.assertEqual(payload['permissionDecision'], 'deny')
        self.assertTrue(payload['permissionDecisionReason']
                        .startswith('token-shunt: '))
        self.assertEqual('', self.run_hook(
            {'tool_name': 'SendMessage', 'tool_input': {'to': 'someone'},
             'transcript_path': path}))

    def test_unparsable_input_is_not_a_turn_failure(self):
        proc = subprocess.run([str(HOOKS / 'check-worker-resume')],
                              input='{not json', text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, '')


class RegistrationTests(unittest.TestCase):
    """A hook nothing invokes enforces nothing."""

    def test_send_message_is_matched_by_the_registered_hook(self):
        hooks = json.loads((HOOKS / 'hooks.json').read_text(
            encoding='utf-8'))['hooks']['PreToolUse']
        commands = [h['command'] for entry in hooks
                    if 'SendMessage' in entry['matcher']
                    for h in entry['hooks']]
        self.assertTrue(any(c.endswith('/hooks/check-worker-resume')
                            for c in commands), commands)

    def test_the_entry_point_is_executable(self):
        self.assertTrue(os.access(HOOKS / 'check-worker-resume', os.X_OK))

    def test_the_skill_says_what_to_do_when_a_worker_stops_silent(self):
        # A deny with no stated alternative strands the parent, which is
        # the case the hook now refuses: a worker that ended without a
        # report. The skill has to name the move that replaces resume.
        skill = (HOOKS.parent / 'skills' / 'bulk-reader'
                 / 'SKILL.md').read_text(encoding='utf-8')
        clause = skill[skill.index('stops without a report'):][:400]
        self.assertIn('new invocation', clause.lower())
        self.assertIn('partial', clause)


if __name__ == '__main__':
    unittest.main()
