import importlib.machinery
import importlib.util
from pathlib import Path
import unittest
import concurrent.futures
import json
import os
import subprocess
import shutil
import tempfile
import uuid

path = Path(__file__).resolve().parents[1] / 'plugin/hooks/check-reader-contract'
loader = importlib.machinery.SourceFileLoader('reader_contract', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
hook = importlib.util.module_from_spec(spec)
# Execute the source directly so loading this extensionless hook cannot leave
# bytecode inside the distributable plugin tree.
exec(compile(path.read_bytes(), str(path), 'exec'), hook.__dict__)


class ReaderContractTests(unittest.TestCase):
    def setUp(self):
        self.state = {'calls': 0, 'paths': {}}

    def pre(self, id='r', offset=1, limit=259, path='/a'):
        return hook.transition(self.state, {'hook_event_name': 'PreToolUse',
            'tool_use_id': id, 'tool_input': {'file_path': path, 'offset': offset, 'limit': limit}})

    def post(self, id='r', start=1, count=175, total=518):
        return hook.transition(self.state, {'hook_event_name': 'PostToolUse',
            'tool_use_id': id, 'tool_response': {'type': 'text', 'file': {
                'startLine': start, 'numLines': count, 'totalLines': total}}})

    def failure(self, id='r'):
        return hook.transition(self.state, {'hook_event_name': 'PostToolUseFailure',
            'tool_use_id': id, 'error': 'File content (30000 tokens) exceeds maximum allowed tokens (25000)'})

    def test_actual_endpoint_not_requested_endpoint(self):
        self.assertIsNone(self.pre())
        self.post()
        self.assertIsNotNone(self.pre(id='bad', offset=260))
        self.assertIsNone(self.pre(id='good', offset=176))

    def test_floor_half_and_no_overlap(self):
        self.pre(); self.failure()
        self.assertIsNotNone(self.pre(id='ceil', limit=130))
        self.assertIsNone(self.pre(id='floor', limit=129))
        self.post(id='floor', count=129)
        self.assertIsNotNone(self.pre(id='overlap', offset=129))
        self.assertIsNone(self.pre(id='next', offset=130))

    def test_pending_read_cannot_be_cleared_by_denied_call(self):
        self.pre()
        self.assertIsNotNone(self.pre(id='parallel', path='/b'))
        self.failure('parallel')
        self.assertEqual('r', self.state['pending']['id'])
        self.post()
        self.assertIsNone(self.pre(id='next', offset=176))

    def test_six_attempts_across_files_including_refusals(self):
        for i in range(6):
            self.assertIsNone(self.pre(str(i), limit=64 // (2**i)))
            self.failure(str(i))
        self.assertIn('budget exhausted', self.pre('seventh', path='/b'))

    def test_unknown_result_and_limit_one_refusal_stop(self):
        self.pre(limit=1); self.failure()
        self.assertIsNotNone(self.pre('again', limit=1))
        self.setUp()
        self.pre(); self.post(count=0)
        self.assertIsNotNone(self.pre('again'))

    def test_stopped_and_retry_state_survive_path_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source'
            source.write_text('body')
            link = Path(directory) / 'link'
            link.symlink_to(source)
            self.pre(path=str(source)); self.post(count=0)
            for alias in (str(source.parent) + '/./source',
                          str(source.parent) + '//source', str(link)):
                self.assertIn('No further Read', self.pre(path=alias))
            self.setUp()
            self.pre(path=str(source), limit=20); self.failure()
            self.assertIn('limit=10', self.pre(path=str(link), limit=20))
            self.assertIsNone(self.pre(path=str(link), limit=10))

    def test_max_three_paths(self):
        for i in range(3):
            self.assertIsNone(self.pre(str(i), path='/'+str(i)))
            self.post(str(i), count=1, total=1)
        self.assertIsNotNone(self.pre('fourth', path='/fourth'))


class RuntimeHookTests(unittest.TestCase):
    def test_malformed_events_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = {'hook_event_name': 'PreToolUse', 'session_id': 'session',
                    'agent_id': 'worker', 'agent_type': 'token-shunt:bulk-reader',
                    'tool_use_id': 'r', 'tool_input': {'file_path': '/a'}}
            for event in ([], None, dict(base, tool_input=[]), dict(base, tool_input=None),
                          dict(base, session_id=[]), dict(base, agent_id=123)):
                with self.subTest(event=event):
                    result = subprocess.run([str(path)], input=json.dumps(event),
                        text=True, capture_output=True, env=dict(os.environ, TMPDIR=directory))
                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertIn('token-shunt:', result.stderr)
                    self.assertNotIn('Traceback', result.stderr)

    def test_deep_json_fails_closed_without_traceback(self):
        result = subprocess.run([str(path)], input='[' * 100000 + '0' + ']' * 100000,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('token-shunt:', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_malformed_nested_response_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, TMPDIR=directory)
            for i, file in enumerate(([], None)):
                base = {'session_id': 'session', 'agent_id': str(i),
                        'agent_type': 'token-shunt:bulk-reader', 'tool_use_id': 'r',
                        'tool_input': {'file_path': '/a'}}
                def invoke(event):
                    return subprocess.run([str(path)], input=json.dumps(event),
                        text=True, capture_output=True, env=env)
                self.assertEqual(0, invoke(dict(base, hook_event_name='PreToolUse')).returncode)
                result = invoke(dict(base, hook_event_name='PostToolUse',
                    tool_response={'type': 'text', 'file': file}))
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertNotIn('Traceback', result.stderr)

    def test_registered_read_gate_without_python(self):
        hooks = json.loads((path.parent / 'hooks.json').read_text())['hooks']['PreToolUse']
        commands = [h['command'] for entry in hooks if entry['matcher'] == 'Read'
                    for h in entry['hooks']]
        self.assertTrue(any('check-file-size' in c for c in commands))
        with tempfile.TemporaryDirectory() as directory:
            for name in ('bash', 'cat', 'jq'):
                os.symlink(shutil.which(name), Path(directory) / name)
            env = dict(os.environ, PATH=directory,
                       CLAUDE_PLUGIN_ROOT=str(path.parent.parent))
            for agent, blocked in (('token-shunt:bulk-reader', True),
                                   ('token-shunt:code-writer', False), ('parent', False)):
                event = {'agent_type': agent, 'tool_input': {}}
                results = [subprocess.run(['/bin/bash', '-c', command],
                    input=json.dumps(event), text=True, capture_output=True, env=env)
                    for command in commands]
                self.assertEqual(blocked, any(r.returncode == 2 or
                    '"permissionDecision":"deny"' in r.stdout.replace(' ', '') for r in results))

    def test_parallel_processes_share_budget_and_pending_state(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, TMPDIR=directory)
            session = str(uuid.uuid4())
            def invoke(i, agent='worker'):
                event = {'hook_event_name': 'PreToolUse', 'session_id': session,
                         'agent_id': agent, 'agent_type': 'token-shunt:bulk-reader',
                         'tool_use_id': str(i), 'tool_input': {'file_path': '/a', 'limit': 20}}
                return subprocess.run([str(path)], input=json.dumps(event),
                                      text=True, capture_output=True, env=env)
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(invoke, range(8)))
            self.assertTrue(all(r.returncode == 0 for r in results))
            self.assertEqual(1, sum(not r.stdout for r in results))
            self.assertEqual(7, sum('permissionDecision' in r.stdout for r in results))
            self.assertEqual('', invoke('independent', 'other-worker').stdout)

    def test_whole_single_line_refusal_allows_one_bounded_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'one-line'
            source.write_text('x' * 70000)
            state = {'calls': 0, 'paths': {}}
            base = {'tool_use_id': 'first', 'tool_input': {'file_path': str(source)}}
            hook.transition(state, dict(base, hook_event_name='PreToolUse'))
            hook.transition(state, dict(base, hook_event_name='PostToolUseFailure',
                error='File content exceeds maximum allowed tokens'))
            self.assertEqual(1, state['paths'][str(source)]['retry'])


if __name__ == '__main__':
    unittest.main()
