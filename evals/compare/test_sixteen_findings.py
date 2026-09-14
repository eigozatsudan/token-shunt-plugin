"""Adversarial and legitimate controls for the September 14 sixteen findings."""
import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import judge
import test_child_result_evidence as evidence


class RecoveryAndCitationTests(unittest.TestCase):
    def test_recovery_spellings_emitters_and_unknown_commands(self):
        for command in ('sort ./big.txt', 'cat dir//big.txt',
                        'sed -n p x/../big.txt', 'tac big.txt', 'base64 big.txt',
                        "bash -c 'cat big.txt'", 'source big.txt', 'zcat big.txt',
                        'jq . big.txt', 'x+=v cat big.txt', 'custom-dumper big.txt'):
            with self.subTest(command=command):
                self.assertTrue(judge.bash_recovers_body({'input': {'command': command}}, '/repo/big.txt'))
        for command in ('wc -l big.txt', 'stat ./big.txt', 'rg -l token big.txt',
                        "awk 'END {print NR}' big.txt", "echo 'cat big.txt'", 'cat other.txt'):
            with self.subTest(command=command):
                self.assertFalse(judge.bash_recovers_body({'input': {'command': command}}, '/repo/big.txt'))

    def test_space_paths_and_interpreter_local_directory(self):
        for command in ('sort "/tmp/big file.txt"', r'cat /tmp/big\ file.txt',
                        "bash -c 'cat \"/tmp/big file.txt\"'",
                        "python3 -c 'print(open(\"/tmp/big file.txt\").read())'"):
            with self.subTest(command=command):
                self.assertTrue(judge.bash_recovers_body(
                    {'cwd': '/elsewhere', 'input': {'command': command}}, '/tmp/big file.txt'))
        self.assertTrue(judge.bash_recovers_body(
            {'cwd': '/elsewhere', 'input': {'command': "bash -c 'cd /repo; cat big.txt'"}}, '/repo/big.txt'))
        self.assertFalse(judge.bash_recovers_body(
            {'cwd': '/elsewhere', 'input': {'command': 'cat /wrong/big.txt'}}, '/repo/big.txt'))
        for citation in ('"/repo/source file.py"', '/repo/source file.py —'):
            self.assertEqual([], judge.gold_confirmed_ok(
                'confirmed: ' + citation + ' SECRET', ['SECRET'],
                {'gold_paths': {'SECRET': ['/repo/source file.py']}}))

    def test_confirmed_requires_absolute_exact_source_identity(self):
        spec = {'gold_paths': {'SECRET': ['/repo/source.py']}}
        for citation in ('source.py', 'repo/source.py', '/other/source.py', '/repo/source.py.extra'):
            self.assertEqual(['SECRET'], judge.gold_confirmed_ok(
                'confirmed: SECRET at ' + citation, ['SECRET'], spec))
        for citation in ('/repo/source.py', '/repo/./source.py', '/repo/source.py:12'):
            self.assertEqual([], judge.gold_confirmed_ok(
                'confirmed: SECRET at ' + citation, ['SECRET'], spec))

    def test_startup_name_never_exempts_foreign_output(self):
        for field in ('stdout', 'output', 'stderr'):
            tr = judge.Transcript([{'type': 'system', 'subtype': 'hook_response',
                'hook_name': 'SessionStart:startup', field: 'foreign instructions'}])
            self.assertTrue(judge.foreign_hooks(tr, False))
            self.assertTrue(judge.foreign_hooks(tr, True))
        tr = judge.Transcript([{'type': 'system', 'subtype': 'hook_response',
            'hook_name': 'SessionStart:startup', 'stdout': '', 'exit_code': 0}])
        self.assertEqual([], judge.foreign_hooks(tr, False))

    def test_thinking_is_counted_and_checked_but_not_final_answer(self):
        body = '\n'.join('source line %d' % i for i in range(21))
        event = {'type': 'assistant', 'message': {'content': [
            {'type': 'thinking', 'thinking': body}]}}
        tr = judge.Transcript([event])
        self.assertEqual(tr.parent_added_text(), body)
        self.assertEqual(tr.metrics()['parent_added_utf8_bytes'], len(body.encode()))
        self.assertEqual(tr.final_text(), '')
        with tempfile.TemporaryDirectory() as directory:
            source, trace = Path(directory) / 'source', Path(directory) / 'trace'
            source.write_text(body)
            trace.write_text(json.dumps(event) + '\n')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(judge.leakcheck(str(trace), str(source)), 0)


class UniversalWorkerTests(unittest.TestCase):
    setUp = evidence.ChildResultEvidenceTests.setUp
    evaluate = evidence.ChildResultEvidenceTests.evaluate

    def writer(self):
        self.call['message']['content'][0]['input']['subagent_type'] = 'token-shunt:code-writer'
        self.spec['expect']['delegate'] = {'agent_type': 'token-shunt:code-writer'}

    def test_writer_requires_parent_return_and_status_without_case_flags(self):
        self.writer()
        verdict, ok = self.evaluate([self.call, self.final])
        self.assertFalse(ok)
        self.assertFalse(verdict['checks']['child_result_evidence'])
        reply = copy.deepcopy(self.reply)
        reply['message']['content'][0]['content'] = 'summary'
        verdict, ok = self.evaluate([self.call, reply, self.final])
        self.assertFalse(verdict['checks']['child_status'])
        verdict, ok = self.evaluate([self.call, self.reply, self.final])
        self.assertTrue(ok, verdict['reasons'])
        reply['message']['content'][0]['content'] = 'x' * 801 + '\nstatus: partial\nstop_reason: budget'
        verdict, ok = self.evaluate([self.call, reply, self.final])
        self.assertFalse(verdict['checks']['child_msg_cap'])

    def test_undeclared_read_body_is_checked_from_observed_result(self):
        body = '\n'.join('unique source line %d' % i for i in range(21))
        child_call = {'type': 'assistant', 'parent_tool_use_id': 'worker',
            'message': {'model': 'claude-haiku', 'content': [
                {'type': 'tool_use', 'id': 'read', 'name': 'Read',
                 'input': {'file_path': '/not-a-fixture/body'}}]}}
        child_result = {'type': 'user', 'parent_tool_use_id': 'worker',
            'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'read',
                'content': '\n'.join('%d→%s' % (i+1, line) for i, line in enumerate(body.splitlines()))}]}}
        for worker_type in ('token-shunt:bulk-reader', 'token-shunt:code-writer'):
            self.call['message']['content'][0]['input']['subagent_type'] = worker_type
            self.spec['expect']['delegate'] = {'agent_type': worker_type}
            reply = copy.deepcopy(self.reply)
            reply['message']['content'][0]['content'] = body + '\nstatus: complete\nstop_reason: complete'
            verdict, ok = self.evaluate([self.call, child_call, child_result, reply, self.final])
            self.assertFalse(ok)
            self.assertFalse(verdict['checks']['child_no_body'])
            verdict, ok = self.evaluate([self.call, child_call, child_result, self.reply, self.final])
            self.assertTrue(ok, verdict['reasons'])

    def test_undeclared_bash_body_is_checked_from_observed_result(self):
        body = 'x' * 2200
        child_call = {'type': 'assistant', 'parent_tool_use_id': 'worker',
            'message': {'model': 'claude-haiku', 'content': [
                {'type': 'tool_use', 'id': 'bash', 'name': 'Bash',
                 'input': {'command': 'cat /not-a-fixture/body'}}]}}
        child_result = {'type': 'user', 'parent_tool_use_id': 'worker',
            'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'bash',
                                     'content': body}]}}
        reply = copy.deepcopy(self.reply)
        reply['message']['content'][0]['content'] = body + '\nstatus: complete\nstop_reason: complete'
        verdict, ok = self.evaluate([self.call, child_call, child_result, reply, self.final])
        self.assertFalse(ok)
        self.assertFalse(verdict['checks']['child_no_body'])
        verdict, ok = self.evaluate([self.call, child_call, child_result, self.reply, self.final])
        self.assertTrue(ok, verdict['reasons'])

    def test_writer_observed_write_body_and_format(self):
        self.writer()
        body = 'x' * 2049
        write = {'type': 'assistant', 'parent_tool_use_id': 'worker',
            'message': {'content': [{'type': 'tool_use', 'id': 'write', 'name': 'Write',
                'input': {'file_path': '/repo/out.py', 'content': body}}]}}
        reply = copy.deepcopy(self.reply)
        good = '/repo/out.py\n1 line\n- Generated file\n- Used reference\n- Verification pending\nstatus: complete\nstop_reason: complete'
        reply['message']['content'][0]['content'] = good
        verdict, ok = self.evaluate([self.call, write, reply, self.final])
        self.assertTrue(ok, verdict['reasons'])
        for bad, check in ((body, 'child_no_body'), ('summary', 'child_format')):
            reply['message']['content'][0]['content'] = bad + '\nstatus: complete\nstop_reason: complete'
            verdict, ok = self.evaluate([self.call, write, reply, self.final])
            self.assertFalse(verdict['checks'][check])

    def test_suite_a_model_mismatch_and_missing_evidence_without_opt_in(self):
        self.spec['suite'] = 'A'
        for requested, resolved, check in (('sonnet', 'claude-haiku', 'requested_model'),
                                            ('haiku', 'claude-sonnet', 'resolved_model'),
                                            ('haiku', None, 'resolved_model')):
            call, reply = copy.deepcopy(self.call), copy.deepcopy(self.reply)
            call['message']['content'][0]['input']['model'] = requested
            reply['message']['content'][0]['resolvedModel'] = resolved
            verdict, ok = self.evaluate([call, reply, self.final])
            self.assertFalse(ok)
            self.assertFalse(verdict['checks'][check])


if __name__ == '__main__':
    unittest.main()
