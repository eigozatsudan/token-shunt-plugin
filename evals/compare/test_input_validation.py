"""Malformed model arguments must produce an attributable failed verdict."""
import json
from pathlib import Path
import tempfile
import unittest

import judge
import test_aggregate


class InputValidationTests(unittest.TestCase):
    def test_invalid_arguments_fail_with_location(self):
        examples = [('Read', None), ('Agent', []), ('Agent', {'prompt': 3}), ('Agent', {'type': []}),
                    ('Bash', {'command': None}), ('Edit', {'old_string': 7}),
                    ('Read', {'file_path': []})]
        examples += [('Read', {field: value}) for field in ('offset', 'limit')
                     for value in ('1.5', '1', None, True, 1.5, 0, -1, {}, [])]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'events.jsonl'
            for name, inp in examples:
                for child in (None, 'worker'):
                    with self.subTest(name=name, inp=inp, child=child):
                        events = [{'type': 'assistant', 'parent_tool_use_id': child,
                                   'message': {'content': [{'type': 'tool_use', 'id': 'bad-call',
                                                           'name': name, 'input': inp}]}},
                                  {'type': 'result', 'result': 'ok'}]
                        path.write_text('\n'.join(map(json.dumps, events)))
                        verdict, ok = judge.judge(path, {'id': 'invalid', 'expect': {}}, {'mode': 'direct'})
                        self.assertFalse(ok)
                        self.assertFalse(verdict['checks']['transcript'])
                        self.assertIn('bad-call', verdict['reasons'][0])
                        self.assertIn('input', verdict['reasons'][0])

    def test_valid_read_arguments_preserved(self):
        inp = {'file_path': '/tmp/source', 'offset': 1, 'limit': 1}
        tr = judge.Transcript([{'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'id': 'valid', 'name': 'Read', 'input': inp}]}}])
        self.assertEqual(tr.tool_uses[0]['input'], inp)

    def test_invalid_token_requirement_is_spec_failure(self):
        for value in (1, 'auto', {}, [True], ['auot']):
            verdict, ok = judge.judge('/does/not/exist', {
                'id': 'invalid', 'require_parent_tokens': value, 'expect': {}}, {'mode': 'direct'})
            self.assertFalse(ok)
            self.assertFalse(verdict['checks']['spec'])

    def test_gold_file_path_must_be_valid_even_with_gold(self):
        for value in (None, [], 1, '', '  '):
            verdict, ok = judge.judge('/does/not/exist', {
                'id': 'gold', 'gold_file': value, 'gold': ['value'], 'expect': {}},
                {'mode': 'direct'})
            self.assertFalse(ok)
            self.assertFalse(verdict['checks']['spec'])

    def test_declared_gold_cannot_silently_disable_accuracy(self):
        for gold in (None, [], '', [''], [1]):
            verdict, ok = judge.judge('/does/not/exist', {
                'id': 'gold', 'gold_file': 'gold.json', 'gold': gold, 'expect': {}}, {'mode': 'direct'})
            self.assertFalse(ok)
            self.assertFalse(verdict['checks']['spec'])


class AggregateInputTests(unittest.TestCase):
    setUp = test_aggregate.AggregateTests.setUp
    put = test_aggregate.AggregateTests.put
    add = test_aggregate.AggregateTests.add
    run_aggregate = test_aggregate.AggregateTests.run_aggregate
    def test_boolean_and_list_token_requirements(self):
        for requirement, fail_missing in ((True, True), (False, False),
                                          (['auto'], True), (['direct'], False)):
            with self.subTest(requirement=requirement):
                self.manifest['planned'] = []
                spec = self.add()
                spec['require_parent_tokens'] = requirement
                self.put('s/auto-bulk-facts.auto.json', spec)
                p = self.root / 'v/auto-bulk-facts.auto.json'
                verdict = json.loads(p.read_text())
                verdict['metrics'].pop('parent_input_tokens')
                p.write_text(json.dumps(verdict))
                status, _ = self.run_aggregate()
                self.assertEqual(status, int(fail_missing))
