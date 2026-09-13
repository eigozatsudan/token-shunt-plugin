"""Unittest command equivalence must describe execution, not quoted text."""
import json
from pathlib import Path
import tempfile
import unittest

import judge


class ParentBashUnittestTests(unittest.TestCase):
    def evaluate(self, command, output='Ran 6 tests in 0.001s\nOK', error=False):
        events = [
            {'type': 'system', 'subtype': 'init', 'plugins': []},
            {'type': 'assistant', 'message': {'content': [{
                'type': 'tool_use', 'id': 'verify', 'name': 'Bash',
                'input': {'command': command}}]}},
            {'type': 'user', 'message': {'content': [{
                'type': 'tool_result', 'tool_use_id': 'verify',
                'content': output, 'is_error': error}]}},
            {'type': 'result', 'result': 'done'}]
        spec = {'id': 'unittest-alias', 'expect': {'direct': {'parent_bash': {
            'contains': ['python -m unittest'], 'stdout_contains': ['OK'],
            'stdout_forbidden': ['FAILED', 'ERROR'], 'ran_tests_min': 1}}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'transcript.jsonl'
            path.write_text('\n'.join(json.dumps(e) for e in events))
            return judge.judge(str(path), spec, {'mode': 'direct'})

    def test_python_and_python3_module_execution(self):
        for command in ('python -m unittest greeter_test -v',
                        'python3 -m unittest greeter_test -v',
                        'cd /tmp/run.with.dot/out && python3 -m unittest greeter_test -v'):
            with self.subTest(command=command):
                verdict, ok = self.evaluate(command)
                self.assertTrue(ok, verdict['reasons'])

    def test_nonexecuted_and_failed_commands_remain_rejected(self):
        for command in ('echo "python -m unittest"',
                        'echo "python3 -m unittest"',
                        'false && python3 -m unittest',
                        'python3 -m unittest || true',
                        'python3 -c "print(1)" # python -m unittest',
                        'printf OK; python3 -m unittest',
                        'cd /tmp && echo python3 -m unittest'):
            with self.subTest(command=command):
                verdict, ok = self.evaluate(command)
                self.assertFalse(ok)
                self.assertFalse(verdict['checks']['parent_bash'])
        for output, error in [('Ran 0 tests\nOK', False),
                              ('Ran 1 test\nFAILED\nOK', False),
                              ('Ran 1 test\nOK', True)]:
            verdict, ok = self.evaluate('python3 -m unittest greeter_test', output, error)
            self.assertFalse(ok)
            self.assertFalse(verdict['checks']['parent_bash'])


if __name__ == '__main__':
    unittest.main()
