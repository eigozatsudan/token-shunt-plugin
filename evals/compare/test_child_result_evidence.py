"""The child reply contract requires an observed, correctly ordered return."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import judge


class ChildResultEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'transcript.jsonl'
        self.spec = {'id': 'child-result-evidence', 'expect': {'delegate': {
            'agent_type': 'token-shunt:bulk-reader',
            'child_msg_max': 4000, 'child_no_body': True}}}
        self.init = {'type': 'system', 'subtype': 'init',
                     'plugins': [{'name': 'token-shunt'}]}
        self.call = {'type': 'assistant', 'message': {'content': [{
            'type': 'tool_use', 'id': 'worker', 'name': 'Agent',
            'input': {'subagent_type': 'token-shunt:bulk-reader'}}]}}
        self.reply = {'type': 'user', 'message': {'content': [{
            'type': 'tool_result', 'tool_use_id': 'worker',
            'content': 'status: partial\nstop_reason: missing dependency'}]}}
        self.final = {'type': 'result', 'result': 'done'}

    def evaluate(self, events):
        self.path.write_text('\n'.join(json.dumps(e) for e in [self.init] + events))
        return judge.judge(str(self.path), self.spec, {'mode': 'haiku'})

    def test_short_reply_passes_and_overcap_reply_fails(self):
        verdict, ok = self.evaluate([self.call, self.reply, self.final])
        self.assertTrue(ok, verdict['reasons'])
        self.assertTrue(verdict['checks']['child_result_evidence'])
        reply = copy.deepcopy(self.reply)
        reply['message']['content'][0]['content'] = 'x' * 4001
        verdict, ok = self.evaluate([self.call, reply, self.final])
        self.assertFalse(ok)
        self.assertTrue(verdict['checks']['child_result_evidence'])
        self.assertFalse(verdict['checks']['child_msg_cap'])

    def test_missing_misattributed_early_and_late_replies_fail(self):
        child_reply = dict(self.reply, parent_tool_use_id='worker')
        cases = {
            'missing': [self.call, self.final],
            'child-side': [self.call, child_reply, self.final],
            'before-call': [self.reply, self.call, self.final],
            'after-final': [self.call, self.final, self.reply],
        }
        for label, events in cases.items():
            with self.subTest(label=label):
                verdict, ok = self.evaluate(events)
                self.assertFalse(ok)
                for check in ('child_result_evidence', 'child_msg_cap', 'child_no_body'):
                    self.assertFalse(verdict['checks'][check])

    def test_child_final_event_is_not_the_parent_deadline(self):
        child_final = dict(self.final, parent_tool_use_id='worker')
        verdict, ok = self.evaluate([self.call, child_final, self.reply, self.final])
        self.assertTrue(ok, verdict['reasons'])

    def test_each_agent_needs_its_own_return(self):
        another = copy.deepcopy(self.call)
        another['message']['content'][0]['id'] = 'other'
        verdict, ok = self.evaluate([self.call, another, self.reply, self.final])
        self.assertFalse(ok)
        self.assertFalse(verdict['checks']['child_result_evidence'])
        self.assertTrue(any('other' in reason for reason in verdict['reasons']))

    def test_result_identifier_must_match(self):
        reply = copy.deepcopy(self.reply)
        reply['message']['content'][0]['tool_use_id'] = 'different'
        verdict, ok = self.evaluate([self.call, reply, self.final])
        self.assertFalse(ok)
        self.assertFalse(verdict['checks']['child_result_evidence'])

    def async_events(self, summary='status: complete'):
        launch = copy.deepcopy(self.reply)
        launch['message']['content'][0]['content'] = (
            'Async agent launched successfully. ' + 'internal metadata ' * 300)
        launch['tool_use_result'] = {
            'isAsync': True, 'status': 'async_launched', 'agentId': 'task-1'}
        notification = {'type': 'system', 'subtype': 'task_notification',
                        'tool_use_id': 'worker', 'task_id': 'task-1',
                        'status': 'completed', 'summary': summary}
        return launch, notification

    def test_async_completion_measures_returned_summary(self):
        launch, notification = self.async_events()
        verdict, ok = self.evaluate([self.call, launch, notification, self.final])
        self.assertTrue(ok, verdict['reasons'])
        for summary, failed in [('x' * 4001, 'child_msg_cap'),
                                ('```python\nprint(1)\n```', 'child_no_body')]:
            with self.subTest(summary=summary[:20]):
                launch, notification = self.async_events(summary)
                verdict, ok = self.evaluate([self.call, launch, notification, self.final])
                self.assertFalse(ok)
                self.assertTrue(verdict['checks']['child_result_evidence'])
                self.assertFalse(verdict['checks'][failed])

    def test_async_launch_needs_matching_completed_parent_notification(self):
        launch, notification = self.async_events()
        cases = {
            'missing': [self.call, launch, self.final],
            'early': [self.call, notification, launch, self.final],
            'late': [self.call, launch, self.final, notification],
            'child-only': [self.call, launch, {
                'type': 'assistant', 'parent_tool_use_id': 'worker',
                'message': {'content': [{'type': 'text', 'text': 'done'}]}}, self.final],
        }
        for key, value in [('tool_use_id', 'other'), ('task_id', 'other'),
                           ('status', 'running'), ('status', 'failed'),
                           ('parent_tool_use_id', 'worker'), ('summary', '')]:
            cases[key + str(value)] = [self.call, launch,
                                      dict(notification, **{key: value}), self.final]
        no_metadata = copy.deepcopy(launch)
        no_metadata.pop('tool_use_result')
        cases['metadata-missing'] = [self.call, no_metadata, notification, self.final]
        for label, events in cases.items():
            with self.subTest(label=label):
                verdict, ok = self.evaluate(events)
                self.assertFalse(ok)
                for check in ('child_result_evidence', 'child_msg_cap', 'child_no_body'):
                    self.assertFalse(verdict['checks'][check])


if __name__ == '__main__':
    unittest.main()
