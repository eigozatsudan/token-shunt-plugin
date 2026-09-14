"""Async completion must precede an authorized retry, not just parent final."""
import json
from pathlib import Path
import tempfile
import unittest

from judge import Transcript, agent_resolved_models, judge
from routing_checks import check_routing
from test_routing_checks import transcript


class AsyncRetryRoutingTests(unittest.TestCase):
    def events(self, notification_position='before-retry', **changes):
        events = transcript([
            ('haiku', ['/a.py'], '', {}),
            ('sonnet', ['/a.py'], 'missing evidence', {})]).events
        launch = next(e for e in events if e.get('type') == 'user'
                      and e.get('parent_tool_use_id') is None)
        launch['message']['content'][0]['content'] = 'Async agent launched successfully.'
        launch['tool_use_result'] = {'isAsync': True, 'agentId': 'task-1'}
        notification = dict(type='system', subtype='task_notification',
                            tool_use_id='a0', task_id='task-1', status='completed',
                            summary='status: partial\nstop_reason: missing evidence')
        notification.update(changes)
        if notification_position == 'before-retry':
            events.insert(events.index(launch) + 1, notification)
        elif notification_position == 'after-retry':
            events.insert(len(events) - 1, notification)
        return events

    def evaluate(self, events):
        tr = Transcript(events)
        exp = {'retry_policy': True, 'child_msg_max': 800, 'child_no_body': True}
        routing = check_routing(tr, {}, exp, 'auto', tr.agent_uses(), agent_resolved_models)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'transcript.jsonl'
            init = {'type': 'system', 'subtype': 'init', 'plugins': [{'name': 'token-shunt'}]}
            path.write_text('\n'.join(json.dumps(e) for e in [init] + events))
            verdict, ok = judge(str(path), {'id': 'async-retry', 'expect': {'delegate': exp}},
                                {'mode': 'auto'})
        return routing, verdict, ok

    def test_matching_completion_before_retry_passes(self):
        routing, verdict, ok = self.evaluate(self.events())
        self.assertEqual(routing, [])
        self.assertTrue(ok, verdict['reasons'])

    def test_completion_after_retry_is_rejected_even_before_parent_final(self):
        routing, verdict, ok = self.evaluate(self.events('after-retry'))
        self.assertTrue(verdict['checks']['child_result_evidence'])
        self.assertFalse(ok)
        self.assertFalse(verdict['checks']['retry_policy'])
        self.assertTrue(any('previous worker result' in reason for _, reason in routing))

    def test_missing_unfinished_and_unrelated_notifications_reject_retry(self):
        variants = [self.events('missing'), self.events(status='running'),
                    self.events(status='failed'), self.events(task_id='other'),
                    self.events(tool_use_id='other'), self.events(parent_tool_use_id='a0')]
        for events in variants:
            with self.subTest(events=events[-2]):
                routing, verdict, ok = self.evaluate(events)
                self.assertFalse(ok)
                self.assertFalse(verdict['checks']['retry_policy'])
                self.assertTrue(any('previous worker result' in reason for _, reason in routing))


if __name__ == '__main__':
    unittest.main()
