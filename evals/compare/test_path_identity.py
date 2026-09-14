"""Judge path spellings preserve file identity and recorded working directories."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from judge import judge, norm_path


class PathIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'large'
        self.target.write_text('body\n' * 5000)
        (self.root / 'sub').mkdir()

    def evaluate(self, path, cwd=True, init_cwd=None, expected=None):
        target = expected or str(self.target)
        spec = {'id': 'path-identity', 'fixtures_abs': [str(self.target)],
                'expect': {'delegate': {'parent_no_full_read': [target],
                                       'deny_bypass': {'path': target}}}}
        if cwd:
            spec['tool_cwd'] = str(self.root)
        init = {'type': 'system', 'subtype': 'init',
                'plugins': [{'name': 'token-shunt'}]}
        if init_cwd:
            init['cwd'] = init_cwd
        events = [init, {'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'id': 'read', 'name': 'Read',
             'input': {'file_path': path}}]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'read',
                 'content': 'body', 'is_error': False}]}},
            {'type': 'result', 'result': 'done', 'is_error': False}]
        trace = self.root / 'trace.jsonl'
        trace.write_text(''.join(json.dumps(e) + '\n' for e in events))
        verdict, _ = judge(str(trace), spec, {'mode': 'auto'})
        self.last_verdict = verdict
        return verdict['checks']

    def assertBlocked(self, path, **kw):
        checks = self.evaluate(path, **kw)
        self.assertFalse(checks['parent_no_full_read'], path)
        self.assertFalse(checks['deny_bypass'], path)

    def assertDistinct(self, path, **kw):
        checks = self.evaluate(path, **kw)
        self.assertTrue(checks['parent_no_full_read'], path)
        self.assertTrue(checks['deny_bypass'], path)

    def test_absolute_and_relative_aliases(self):
        for path in (str(self.target), str(self.root) + '/./large',
                     str(self.root) + '//large', str(self.root) + '/sub/../large',
                     'large', './large', 'sub/../large'):
            with self.subTest(path=path):
                self.assertTrue(os.path.samefile(self.root / path, self.target))
                self.assertBlocked(path)

    def test_relative_expected_uses_recorded_cwd(self):
        self.assertBlocked(str(self.target), expected='./large')

    def test_init_cwd_fallback_and_spec_precedence(self):
        self.assertBlocked('large', cwd=False, init_cwd=str(self.root))
        self.assertBlocked('large', init_cwd=str(self.root / 'sub'))
        self.assertDistinct('large', cwd=False, init_cwd=str(self.root / 'sub'))

    def test_no_cwd_does_not_borrow_judge_process_cwd(self):
        self.assertFalse(os.path.isabs(norm_path(os.path.relpath(self.target))))
        for path, kwargs in ((os.path.relpath(self.target), {'cwd': False}),
                             ('large', {'cwd': False, 'init_cwd': 'relative-invalid'}),
                             (str(self.target), {'cwd': False, 'expected': 'large'})):
            self.assertBlocked(path, **kwargs)
            self.assertEqual(2, sum('unresolved path identity' in reason
                                    for reason in self.last_verdict['reasons']))

    def test_distinct_paths_and_missing_absolute_path(self):
        for path in (str(self.root / 'sub/large'), str(self.root / 'large-other'),
                     '/missing-root/large'):
            self.assertDistinct(path)

    def test_symlink_alias_and_symlink_parent_semantics(self):
        other = self.root / 'other'
        (other / 'nested').mkdir(parents=True)
        (other / 'large').write_text('different file')
        (self.root / 'link').symlink_to(other / 'nested', target_is_directory=True)
        (self.root / 'alias').symlink_to(self.target)
        self.assertBlocked(str(self.root / 'alias'))
        misleading = str(self.root / 'link') + '/../large'
        self.assertFalse(os.path.samefile(misleading, self.target))
        self.assertDistinct(misleading)
        self.assertDistinct('link/../large')

    def test_root_remains_absolute(self):
        self.assertEqual('/', norm_path('/'))


if __name__ == '__main__':
    unittest.main()
