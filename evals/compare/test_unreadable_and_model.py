import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from routing_checks import unreadable_line_partial
from test_routing_checks import split_read_transcript

HOOK = Path(__file__).resolve().parents[2] / 'plugin/hooks/check-agent-model'


class ModelHookTests(unittest.TestCase):
    def test_explicit_models_and_scoped_denials(self):
        for worker in ('token-shunt:bulk-reader', 'token-shunt:code-writer', 'Explore'):
            for model in (None, 'auto', 'opus', 'haiku', 'sonnet', 1, {}):
                with self.subTest(worker=worker, model=model):
                    inp = {'subagent_type': worker}
                    if model is not None:
                        inp['model'] = model
                    proc = subprocess.run([str(HOOK)], input=json.dumps({'tool_input': inp}),
                                          text=True, capture_output=True)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    denied = worker != 'Explore' and model not in ('haiku', 'sonnet')
                    if denied:
                        self.assertEqual(json.loads(proc.stdout)['hookSpecificOutput']['permissionDecision'], 'deny')
                    else:
                        self.assertEqual(proc.stdout, '')

    def test_malformed_input(self):
        for raw in ('broken', '', '{}\n{}', '{"tool_input":[]}\n{}',
                    '{"tool_input":{"subagent_type":"token-shunt:bulk-reader","model":"opus"}}\n{}'):
            with self.subTest(raw=raw):
                proc = subprocess.run([str(HOOK)], input=raw, text=True, capture_output=True)
                self.assertEqual(proc.returncode, 2)
                self.assertEqual(proc.stdout, '')

    def test_malformed_envelope_shapes_fail_closed(self):
        for value in (None, [], 123, 'text', {'tool_input': None},
                      {'tool_input': []}, {'tool_input': 123}, {'tool_input': 'text'}):
            with self.subTest(value=value):
                proc = subprocess.run([str(HOOK)], input=json.dumps(value), text=True, capture_output=True)
                self.assertEqual(proc.returncode, 2)
                self.assertEqual(proc.stdout, '')
                self.assertIn('token-shunt:', proc.stderr)
        for value in ({}, {'tool_input': {}}):
            proc = subprocess.run([str(HOOK)], input=json.dumps(value), text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout + proc.stderr, '')


class UnreadableTests(unittest.TestCase):
    def check(self, reads, final=None, child=None, lines=1):
        tr = split_read_transcript(reads)
        report = 'unconfirmed: /a.py — TOKEN; unread line 1\nstatus: partial\nstop_reason: unreadable_line'
        tr.result['result'] = report if final is None else final
        reply = tr.result_of('a0')
        reply['text'] = report if child is None else child
        exp = {'child_reads_once': ['/a.py'], 'allow_unreadable_line_partial': ['/a.py']}
        with patch('routing_checks._line_count', return_value=lines):
            return unreadable_line_partial(tr, exp, tr.agent_uses())

    def test_native_limit_one_refusal(self):
        self.assertTrue(self.check([(None, None, True), (1, 1, True)]))
        self.assertTrue(self.check([(1, 1, True)]))

    def test_bullet_status_and_ambiguous_parent_status(self):
        report = ('- unconfirmed: /a.py — TOKEN; unread line 1\n'
                  '- status: partial\n- stop_reason: unreadable_line')
        self.assertTrue(self.check([(1, 1, True)], final=report, child=report))
        self.assertFalse(self.check([(1, 1, True)], final=report + '\nstatus: complete'))

    def test_no_unsupported_credit_without_evidence(self):
        for reads in ([], [(None, None, True)], [(1, 1, False)],
                      [(2, 1, True)], [(1, 1, True), (1, 1, True)]):
            self.assertFalse(self.check(reads))
        self.assertFalse(self.check([(1, 1, True)], lines=2))
        self.assertFalse(self.check([(1, 1, True)], final='status: partial'))
        self.assertFalse(self.check([(1, 1, True)], child='done'))
