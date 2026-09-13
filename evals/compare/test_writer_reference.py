"""Catalog writer references must complete in the writer before every write."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from judge import judge

HERE = Path(__file__).resolve().parent
CASES = json.loads((HERE / 'cases.json').read_text())['cases']


def call(uid, name, inputs, parent='worker'):
    return {'type': 'assistant', 'parent_tool_use_id': parent,
            'message': {'model': 'claude-haiku', 'content': [
                {'type': 'tool_use', 'id': uid, 'name': name, 'input': inputs}]}}


def result(uid, parent='worker', error=False, text='done'):
    return {'type': 'user', 'parent_tool_use_id': parent,
            'message': {'content': [{'type': 'tool_result', 'tool_use_id': uid,
                                    'content': text, 'is_error': error}]}}


class WriterReferenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='writer reference ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        reference = self.root / 'fixtures/codegen/greeter.py'
        reference.parent.mkdir(parents=True)
        reference.write_text('def greet(name):\n    return "Hello, " + name + "!"\n')

    def evaluate(self, case_id, variant='ordered', metadata='root'):
        raw = next(c for c in CASES if c['id'] == case_id)
        spec = json.loads(json.dumps(raw).replace('{TMP}', str(self.root))
                          .replace('{FIX}', str(self.root / 'fixtures')))
        ref = str(self.root / 'fixtures/codegen/greeter.py')
        if metadata == 'root':
            spec['fixture_root'] = str(self.root / 'fixtures')
            spec['tool_cwd'] = str(self.root / ('fixtures' if variant == 'relative' else 'work'))
        else:
            spec['fixtures_abs'] = [ref]
        read_path = ref
        if variant == 'wrong_basename':
            read_path = str(self.root / 'elsewhere/greeter.py')
        elif variant == 'wrong_root':
            read_path = str(self.root / 'elsewhere/codegen/greeter.py')
        elif variant == 'normalized':
            read_path = str(self.root / 'fixtures') + '/codegen/./greeter.py'
        elif variant in ('relative', 'wrong_relative'):
            read_path = 'codegen/greeter.py'
        read = call('read', 'Read', {'file_path': read_path})
        read_result = result('read')
        write = call('write', 'Write', {'file_path': spec['target'], 'content': '# test'})
        if variant.startswith('normalized_write'):
            write['message']['content'][0]['input']['file_path'] = str(Path(spec['target']).parent) + '/./' + Path(spec['target']).name
        elif variant.startswith('relative_write'):
            write['message']['content'][0]['input']['file_path'] = os.path.relpath(spec['target'], spec['tool_cwd'])
        sequence = [read, read_result, write, result('write')]
        if variant.endswith('_missing_read'):
            sequence = [write, result('write')]

        if variant == 'parallel':
            read['message']['content'] += write['message']['content']
            sequence = [read, result('write'), read_result]
        elif variant == 'late':
            sequence = [read, write, result('write'), read_result]
        elif variant == 'before_call':
            sequence = [read_result, read, write, result('write')]
        elif variant == 'failed':
            read_result['message']['content'][0]['is_error'] = True
        elif variant in ('other_child', 'parent_result'):
            read_result['parent_tool_use_id'] = 'other' if variant == 'other_child' else None
        elif variant == 'first_write_early':
            sequence.insert(0, call('early-write', 'Write', {'file_path': spec['target'], 'content': '# early'}))
        events = [{'type': 'system', 'subtype': 'init', 'plugins': [{'name': 'token-shunt'}]},
                  call('worker', 'Agent', {'subagent_type': 'token-shunt:code-writer',
                                          'model': 'haiku', 'prompt': ref}, None)]
        events += sequence + [result('worker', None, text='status: complete; stop_reason: written'),
                              call('verify', 'Bash', {'command': spec['verify_cmd']}, None),
                              result('verify', None, text='Ran 1 test\nOK'),
                              {'type': 'result', 'result': 'verified'}]
        path = self.root / 'trace.jsonl'
        path.write_text(''.join(json.dumps(e) + '\n' for e in events))
        return judge(str(path), spec, {'mode': 'haiku'})

    def test_absolute_reference_in_real_catalog_cases(self):
        for case_id in ('compare-code-writer-ok', 'auto-large-writer'):
            for metadata in ('root', 'fixtures_abs'):
                with self.subTest(case=case_id, metadata=metadata):
                    verdict, ok = self.evaluate(case_id, metadata=metadata)
                    self.assertTrue(ok, verdict['reasons'])
                    self.assertTrue(verdict['checks']['child_ref_before_write'])

    def test_target_path_spellings_do_not_skip_reference_check(self):
        for case_id in ('compare-code-writer-ok', 'auto-large-writer'):
            for spelling in ('normalized_write', 'relative_write'):
                for missing in (False, True):
                    with self.subTest(case=case_id, spelling=spelling, missing=missing):
                        verdict, ok = self.evaluate(case_id, spelling + ('_missing_read' if missing else ''))
                        self.assertEqual(ok, not missing, verdict['reasons'])
                        self.assertEqual(verdict['checks']['child_ref_before_write'], not missing)

    def test_normalized_absolute_reference(self):
        verdict, ok = self.evaluate('compare-code-writer-ok', 'normalized')
        self.assertTrue(ok, verdict['reasons'])

    def test_relative_reference_remains_supported(self):
        verdict, ok = self.evaluate('compare-code-writer-ok', 'relative')
        self.assertTrue(ok, verdict['reasons'])

    def test_wrong_paths_and_invalid_order_are_rejected(self):
        for case_id in ('compare-code-writer-ok', 'auto-large-writer'):
            for variant in ('wrong_basename', 'wrong_root', 'wrong_relative', 'parallel', 'late',
                            'before_call', 'failed', 'other_child', 'parent_result',
                            'first_write_early'):
                with self.subTest(case=case_id, variant=variant):
                    verdict, ok = self.evaluate(case_id, variant)
                    self.assertFalse(ok)
                    self.assertFalse(verdict['checks']['child_ref_before_write'])


if __name__ == '__main__':
    unittest.main()
