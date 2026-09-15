"""A routing denial must belong to the target Read, not just occur nearby."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import judge


class DenyRouteEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = str(self.root / 'target.txt')
        self.spec = {'id': 'deny-route-evidence', 'tool_cwd': str(self.root),
                     'expect': {'delegate': {'deny_route': {'path': self.path}}}}
        self.reason = 'File exceeds token-shunt thresholds. Use /token-shunt:bulk-reader.'

    def events(self):
        def use(uid, name, inp):
            return {'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'id': uid, 'name': name, 'input': inp}]}}
        def result(uid, text, error=False):
            return {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': uid, 'resolvedModel': 'claude-haiku', 'content': text, 'is_error': error}]}}
        return [
            {'type': 'system', 'subtype': 'init', 'plugins': [{'name': 'token-shunt'}]},
            use('r', 'Read', {'file_path': self.path}),
            {'type': 'system', 'subtype': 'hook_response', 'hook_name': 'PreToolUse:Read',
             'stdout': json.dumps({'hookSpecificOutput': {'permissionDecision': 'deny',
                                                       'permissionDecisionReason': self.reason}})},
            result('r', self.reason, True),
            use('a', 'Agent', {'subagent_type': 'token-shunt:bulk-reader',
                              'model': 'haiku', 'prompt': self.path}),
            result('a', 'status: partial\nstop_reason: missing evidence'),
            {'type': 'result', 'result': 'partial'}]

    def evaluate(self, events):
        path = self.root / 'transcript.jsonl'
        path.write_text('\n'.join(json.dumps(e) for e in events))
        return judge.judge(str(path), self.spec, {'mode': 'auto'})

    def test_bound_denial_accepts_native_representations(self):
        for name in ('PreToolUse:Read', '/plugin/hooks/check-file-size'):
            for output in ('stdout', 'output'):
                for tool in ('Agent', 'Task'):
                    ev = self.events()
                    ev[2]['hook_name'] = name
                    ev[2][output] = ev[2].pop('stdout')
                    ev[2]['tool_use_id'] = 'r'
                    ev[4]['message']['content'][0]['name'] = tool
                    verdict, ok = self.evaluate(ev)
                    self.assertTrue(ok, verdict['reasons'])
        self.spec['expect']['delegate']['deny_route']['allow_range'] = True
        ev = self.events()
        ev[1]['message']['content'][0]['input'].update(file_path='./target.txt', offset=1, limit=1)
        verdict, ok = self.evaluate(ev)
        self.assertTrue(ok, verdict['reasons'])

    def test_unbound_wrong_scope_or_out_of_order_denials_fail(self):
        for variant in ('not_found', 'success', 'wrong_id', 'missing_result', 'child_result',
                        'child_hook', 'bash_hook', 'wrong_hook_id', 'post_hook',
                        'hook_before_read', 'hook_after_result', 'agent_before_result', 'missing_hook'):
            with self.subTest(variant=variant):
                ev = self.events()
                block = ev[3]['message']['content'][0]
                if variant == 'not_found': block['content'] = 'File not found'
                elif variant == 'success': block['is_error'] = False
                elif variant == 'wrong_id': block['tool_use_id'] = 'another-read'
                elif variant == 'missing_result': ev.pop(3)
                elif variant == 'child_result': ev[3]['parent_tool_use_id'] = 'another-worker'
                elif variant == 'child_hook': ev[2]['parent_tool_use_id'] = 'another-worker'
                elif variant == 'bash_hook': ev[2]['hook_name'] = 'PreToolUse:Bash'
                elif variant == 'wrong_hook_id': ev[2]['tool_use_id'] = 'another-read'
                elif variant == 'post_hook': ev[2]['hook_event'] = 'PostToolUse'
                elif variant == 'hook_before_read': ev[1], ev[2] = ev[2], ev[1]
                elif variant == 'hook_after_result': ev[2], ev[3] = ev[3], ev[2]
                elif variant == 'agent_before_result': ev[3], ev[4] = ev[4], ev[3]
                elif variant == 'missing_hook': ev.pop(2)
                verdict, ok = self.evaluate(ev)
                self.assertFalse(ok)
                self.assertFalse(verdict['checks']['deny_route'])

    def metadata_events(self, command=None, read=None):
        """The route the skill actually produces: measure, then delegate."""
        ev = self.events()
        ev.pop(3)                                   # no failed Read result
        ev.pop(2)                                   # no deny
        ev.pop(1)                                   # no Read at all
        meta = {'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'id': 'm', 'name': 'Bash',
             'input': {'command': command or ('wc -c %s' % self.path)}}]}}
        done = {'type': 'user', 'message': {'content': [
            {'type': 'tool_result', 'tool_use_id': 'm',
             'content': '13982 %s' % self.path, 'is_error': False}]}}
        head = [ev[0], meta, done]
        if read is not None:
            head += [{'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'id': 'r2', 'name': 'Read',
                 'input': dict(read, file_path=self.path)}]}},
                {'type': 'user', 'message': {'content': [
                    {'type': 'tool_result', 'tool_use_id': 'r2',
                     'content': 'body text', 'is_error': False}]}}]
        return head + ev[1:]

    def test_measuring_then_delegating_is_a_conforming_route(self):
        # SKILL.md section 1 tells the parent to judge size from metadata
        # before the first Read. When that alone decides the route, no Read
        # is issued and there is no deny to match — the rule worked, and
        # the round trip a deny would have cost was saved
        # (reviews/deny-route-case-2026-09-15.md).
        verdict, ok = self.evaluate(self.metadata_events())
        self.assertTrue(verdict['checks']['deny_route'], verdict['reasons'])

    def test_stat_counts_as_the_measurement_too(self):
        verdict, _ = self.evaluate(
            self.metadata_events(command='stat -c %%s %s' % self.path))
        self.assertTrue(verdict['checks']['deny_route'], verdict['reasons'])

    def test_delegating_with_no_measurement_at_all_is_not_a_route(self):
        # Neither evidence: nothing establishes the parent judged size
        # before handing the file over.
        ev = self.metadata_events()
        ev.pop(2); ev.pop(1)
        verdict, _ = self.evaluate(ev)
        self.assertFalse(verdict['checks']['deny_route'])

    def test_a_command_that_printed_no_size_does_not_count(self):
        # `stat -c%n` prints the path. The parent that ran it knows no
        # more about the size than before, in either spelling.
        for command in ('stat -c %%n %s', 'stat -c%%n %s', 'stat -t %s'):
            with self.subTest(command=command):
                verdict, _ = self.evaluate(
                    self.metadata_events(command=command % self.path))
                self.assertFalse(verdict['checks']['deny_route'])

    def test_a_measurement_that_never_came_back_does_not_count(self):
        """An errored or unanswered command told the parent nothing."""
        for mutate in ('error', 'no_result'):
            with self.subTest(mutate=mutate):
                ev = self.metadata_events()
                if mutate == 'error':
                    ev[2]['message']['content'][0].update(
                        is_error=True, content='wc: No such file')
                else:
                    ev.pop(2)
                verdict, _ = self.evaluate(ev)
                self.assertFalse(verdict['checks']['deny_route'])

    def test_a_measurement_of_some_other_file_does_not_count(self):
        verdict, _ = self.evaluate(
            self.metadata_events(command='wc -c %s/elsewhere.txt' % self.root))
        self.assertFalse(verdict['checks']['deny_route'])

    def test_reading_the_body_after_measuring_is_still_a_failure(self):
        # The point of the case is that the parent does not take the body
        # into its own context. Measuring first does not license that.
        verdict, _ = self.evaluate(self.metadata_events(read={}))
        self.assertFalse(verdict['checks']['deny_route'])

    def test_a_ranged_read_after_measuring_does_not_excuse_the_route(self):
        verdict, _ = self.evaluate(
            self.metadata_events(read={'offset': 1, 'limit': 40}))
        self.assertFalse(verdict['checks']['deny_route'])

    def test_measuring_after_the_delegation_is_not_evidence(self):
        ev = self.metadata_events()
        ev.append(ev.pop(1)); ev.append(ev.pop(1))     # move both after Agent
        verdict, _ = self.evaluate(ev)
        self.assertFalse(verdict['checks']['deny_route'])

    def test_read_and_agent_in_same_message_do_not_prove_completed_denial(self):
        ev = self.events()
        ev[1]['message']['content'].append(copy.deepcopy(ev[4]['message']['content'][0]))
        ev.pop(4)
        verdict, ok = self.evaluate(ev)
        self.assertFalse(verdict['checks']['deny_route'])


if __name__ == '__main__':
    unittest.main()
