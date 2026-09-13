"""Regression controls from the third comparison-judge review."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import judge


class ConfirmedLabelTests(unittest.TestCase):
    def test_unconfirmed_is_never_a_confirmed_label(self):
        for text in ('unconfirmed: secret at source.py',
                     'Notes: unconfirmed: secret at source.py',
                     'UNCONFIRMED: secret at source.py',
                     'notconfirmed: secret at source.py'):
            with self.subTest(text=text):
                self.assertEqual([], judge.confirmed_items(text))
                self.assertEqual(['secret'], judge.gold_confirmed_ok(text, ['secret'],
                    {'gold_paths': {'secret': ['source.py']}}))

    def test_line_and_inline_confirmed_labels_still_work(self):
        for text in ('confirmed: secret at source.py',
                     '- confirmed: secret at source.py',
                     'Notes: confirmed: secret at source.py unconfirmed: other',
                     'Notes: CONFIRMED: secret at source.py inferred: other'):
            with self.subTest(text=text):
                self.assertEqual([], judge.gold_confirmed_ok(text, ['secret'],
                    {'gold_paths': {'secret': ['source.py']}}))
                self.assertNotIn('other', '\n'.join(judge.confirmed_items(text)))


class AsyncParentContextTests(unittest.TestCase):
    def events(self):
        return [
            {'type': 'assistant', 'message': {'id': 'call', 'content': [{
                'type': 'tool_use', 'id': 'worker', 'name': 'Agent', 'input': {'prompt': 'read'}}]}},
            {'type': 'user', 'tool_use_result': {'isAsync': True, 'agentId': 'task-1'},
             'message': {'id': 'launch', 'content': [{'type': 'tool_result', 'tool_use_id': 'worker',
                                                    'content': 'launch metadata'}]}},
            {'type': 'system', 'subtype': 'task_notification', 'tool_use_id': 'worker',
             'task_id': 'task-1', 'status': 'completed', 'summary': '回答\n' * 1000},
            {'type': 'result', 'result': 'done', 'usage': {'input_tokens': 123, 'output_tokens': 4},
             'modelUsage': {'model': {'inputTokens': 456}}},
        ]

    def test_summary_and_launch_count_once_with_unicode_metrics(self):
        events = self.events()
        tr = judge.Transcript(events[:3] + [copy.deepcopy(events[2])] + events[3:])
        expected = '{"prompt":read}\nlaunch metadata\n' + events[2]['summary']
        self.assertEqual(expected, tr.parent_added_text())
        metrics = tr.metrics()
        self.assertEqual(len(expected), metrics['parent_added_chars'])
        self.assertEqual(len(expected.encode()), metrics['parent_added_utf8_bytes'])
        self.assertEqual(len(expected.encode()) // 4, metrics['parent_added_tokens_est'])
        self.assertEqual(events[-1]['usage'], metrics['usage_parent'])
        self.assertEqual(events[-1]['modelUsage'], metrics['usage_tree'])
        self.assertEqual(123, metrics['parent_input_tokens']['uncached'])

    def test_invalid_notifications_and_child_text_do_not_count(self):
        for changes in ({'tool_use_id': 'other'}, {'task_id': 'other'},
                        {'status': 'running'}, {'status': 'failed'},
                        {'parent_tool_use_id': 'worker'}, {'summary': ''}):
            events = self.events()
            events[2].update(changes)
            tr = judge.Transcript(events)
            self.assertEqual('{"prompt":read}\nlaunch metadata', tr.parent_added_text())
        events = self.events()
        self.assertNotIn('回答', judge.Transcript([events[0], events[2], events[1]]).parent_added_text())
        child = {'type': 'assistant', 'parent_tool_use_id': 'worker',
                 'message': {'content': [{'type': 'text', 'text': 'child only'}]}}
        self.assertNotIn('child only', judge.Transcript(events + [child]).parent_added_text())

    def test_sync_reply_is_not_added_twice(self):
        events = self.events()
        del events[1]['tool_use_result']
        self.assertEqual('{"prompt":read}\nlaunch metadata', judge.Transcript(events).parent_added_text())


class UnittestTargetEvidenceTests(unittest.TestCase):
    def evaluate(self, command):
        events = [
            {'type': 'assistant', 'message': {'content': [{
                'type': 'tool_use', 'id': 'verify', 'name': 'Bash', 'input': {'command': command}}]}},
            {'type': 'user', 'message': {'content': [{
                'type': 'tool_result', 'tool_use_id': 'verify', 'content': 'Ran 1 test\nOK'}]}},
            {'type': 'result', 'result': 'done'}]
        spec = {'id': 'target-regression', 'expect': {'direct': {'parent_bash': {
            'contains': ['python3 -m unittest', 'greeter_test'],
            'stdout_contains': ['OK'], 'ran_tests_min': 1}}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'transcript.jsonl'
            path.write_text('\n'.join(json.dumps(event) for event in events))
            verdict, _ = judge.judge(str(path), spec, {'mode': 'direct'})
            return verdict['checks']['parent_bash']

    def test_only_actual_test_targets_satisfy_catalog_needle(self):
        for command in ('python3 -m unittest unrelated.py #greeter_test',
                        'python3 -m unittest unrelated.py -k greeter_test',
                        'python3 -m unittest unrelated.py -kgreeter_test',
                        'cd /tmp/greeter_test && python3 -m unittest unrelated.py',
                        'python3 -m unittest discover -s /tmp/greeter_test -p unrelated.py',
                        'python3 -m unittest discover -s /tmp -p unrelated.py -t /tmp/greeter_test',
                        'python3 -m unittest not_greeter_test.py',
                        'python3 -m unittest /tmp/greeter_test/unrelated.py',
                        'python3 -m unittest discover -p greeter_test.py -p unrelated.py',
                        'python3 -m unittest unrelated.py "#greeter_test"'):
            with self.subTest(command=command):
                self.assertFalse(self.evaluate(command))
        for command in ('python -m unittest greeter_test -v',
                        'python3 -m unittest /tmp/greeter_test.py',
                        'python3 -m unittest pkg.greeter_test.TestGreeting',
                        'cd "/tmp/path with spaces" && python3 -m unittest greeter_test -v',
                        'python3 -m unittest discover -s "/tmp/path with spaces" -p greeter_test.py',
                        'python3 -m unittest discover --start-directory=/tmp --pattern=greeter_test.py',
                        'python3 -m unittest discover /tmp greeter_test.py',
                        'python3 -m unittest discover -s/tmp -pgreeter_test.py'):
            with self.subTest(command=command):
                self.assertTrue(self.evaluate(command))


if __name__ == '__main__':
    unittest.main()
