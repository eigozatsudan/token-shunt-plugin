"""Exercise the catalog's writer gates through the judge and actual disk_check."""
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

from judge import judge


HERE = Path(__file__).resolve().parent
CASES = json.loads((HERE / 'cases.json').read_text())['cases']


def call(uid, name, inp, parent=None):
    return {'type': 'assistant', 'parent_tool_use_id': parent,
            'message': {'model': 'claude-haiku' if parent else 'claude-sonnet',
                        'content': [{'type': 'tool_use', 'id': uid, 'name': name, 'input': inp}]}}


def result(uid, error=False, parent=None):
    return {'type': 'user', 'parent_tool_use_id': parent,
            'message': {'content': [{'type': 'tool_result', 'tool_use_id': uid,
                                     'content': 'status: partial\nstop_reason: done', 'is_error': error}]}}


def module(lines):
    if lines == 49:
        body = 'def greet(name):\n    return "Hello, %s!" % name\n\ndef greet_world():\n    return greet("world")\n'
    else:
        body = ('import unittest\nfrom greeter import greet\n\nclass GreetingTest(unittest.TestCase):\n'
                '    def test_greet(self):\n        self.assertEqual(greet("world"), "Hello, world!")\n')
    return body + '# padding\n' * (lines - len(body.splitlines()))


class WriterBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='writer boundary ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'verdicts').mkdir()
        (self.root / 'fixtures/codegen').mkdir(parents=True)
        shutil.copyfile(HERE / 'fixtures/codegen/greeter.py', self.root / 'fixtures/codegen/greeter.py')

    def spec(self, lines):
        case = next(c for c in CASES if c['id'] == f'auto-routing-boundary-{lines}-lines-writer')
        return json.loads(json.dumps(case).replace('{TMP}', str(self.root)).replace('{FIX}', str(HERE / 'fixtures')))

    def events(self, lines, mode, command=None, check='success'):
        spec = self.spec(lines)
        target = str(self.root / f'w{lines}.py')
        events = [{'type': 'system', 'subtype': 'init',
                   'plugins': [] if mode == 'direct' else [{'name': 'token-shunt'}]}]
        worker = 'worker' if lines == 50 and mode != 'direct' else None
        if worker:
            events.append(call(worker, 'Agent', {'subagent_type': 'token-shunt:code-writer',
                                                'model': 'haiku', 'prompt': spec['prompt_delegate']}))
        events += [call('write', 'Write', {'file_path': target, 'content': module(lines)}, worker),
                   result('write', parent=worker)]
        if worker:
            reply = result(worker)
            reply['message']['content'][0]['content'] = (target + '\n50 lines\n- Generated tests\n- Used reference\n- Parent verification pending\nstatus: complete\nstop_reason: complete')
            events.append(reply)
        verification = [call('verify', 'Bash', {'command': command or 'python -m py_compile ' + shlex.quote(target)}),
                        result('verify', error=check == 'failed')]
        final = {'type': 'result', 'result': 'Done', 'is_error': False}
        if check == 'late':
            events += verification[:1] + [final] + verification[1:]
        elif check == 'missing_result':
            events += verification[:1] + [final]
        elif check == 'missing':
            events.append(final)
        elif check == 'child_only':
            for event in verification:
                event['parent_tool_use_id'] = 'worker'
            events += verification + [final]
        else:
            events += verification + [final]
        return events

    def judged(self, lines, mode, **kwargs):
        transcript = self.root / 'transcript.jsonl'
        transcript.write_text('\n'.join(json.dumps(e) for e in self.events(lines, mode, **kwargs)))
        return judge(str(transcript), self.spec(lines), {'mode': mode})

    def disk(self, lines, mode, body):
        (self.root / f'w{lines}.py').write_bytes(body if isinstance(body, bytes) else body.encode('utf-8'))
        command = 'source "$1"; TMP="$2"; FIX="$2/fixtures"; VRD="$2/verdicts"; disk_check "$3" "$4"'
        run = subprocess.run(['bash', '-c', command, 'test', str(HERE / 'run.sh'), str(self.root),
                              json.dumps(self.spec(lines)), mode], capture_output=True, text=True)
        verdict = json.loads((self.root / 'verdicts' / f'{self.spec(lines)["id"]}.{mode}.disk.json').read_text())
        self.assertEqual(run.returncode == 0, verdict['disk_ok'], run.stderr)
        return verdict['disk_ok']

    def test_real_cases_all_normal_routes(self):
        for lines in (49, 50):
            for mode in self.spec(lines)['modes']:
                for python in ('python', 'python3'):
                    with self.subTest(lines=lines, mode=mode, python=python):
                        command = python + ' -m py_compile ' + shlex.quote(str(self.root / f'w{lines}.py'))
                        verdict, ok = self.judged(lines, mode, command=command)
                        self.assertTrue(ok, verdict['reasons'])
                self.assertTrue(self.disk(lines, mode, module(lines)))

    def test_verification_requires_completed_parent_result_before_report(self):
        for lines in (49, 50):
            for mode in self.spec(lines)['modes']:
                for check in ('missing', 'missing_result', 'failed', 'late', 'child_only'):
                    with self.subTest(lines=lines, mode=mode, check=check):
                        verdict, ok = self.judged(lines, mode, check=check)
                        self.assertFalse(ok, verdict)
                        self.assertTrue(any('py_compile' in str(r) for r in verdict['reasons']))

    def test_command_is_exact_not_a_substring(self):
        for lines in (49, 50):
            target = shlex.quote(str(self.root / f'w{lines}.py'))
            for command in ('echo python -m py_compile ' + target,
                            'python -m py_compile /other.py',
                            'python -m py_compile ' + target + ' || true'):
                with self.subTest(lines=lines, command=command):
                    self.assertFalse(self.judged(lines, 'direct', command=command)[1])

    def test_disk_rejects_empty_invalid_short_and_wrong_module(self):
        for lines in (49, 50):
            for mode in self.spec(lines)['modes']:
                variants = ['', 'def greet(:\n' + '# padding\n' * (lines - 1),
                            '\n'.join(module(lines).splitlines()[:-1]) + '\n', '# filler\n' * lines]
                for body in variants:
                    with self.subTest(lines=lines, mode=mode, body=body[:20]):
                        self.assertFalse(self.disk(lines, mode, body))

    def test_exact_49_and_at_least_50(self):
        self.assertFalse(self.disk(49, 'direct', module(49) + '# extra\n'))
        self.assertTrue(self.disk(50, 'auto', module(50) + '# extra\n'))

    def test_unittest_and_greet_import_aliases(self):
        body = module(50).replace('import unittest', 'from unittest import TestCase as Case')
        body = body.replace('unittest.TestCase', 'Case').replace('from greeter import greet', 'from greeter import greet as hello')
        body = body.replace('greet("world")', 'hello("world")')
        self.assertTrue(self.disk(50, 'direct', body))
        self.assertFalse(self.disk(50, 'direct', module(50).replace('import unittest', '# no unittest import')))

    def test_behavioral_greet_coverage(self):
        prefix = 'import unittest\nfrom greeter import greet\n'
        variants = [
            (True, 'import atexit\natexit.register(print, "finished")\nclass Tests(unittest.TestCase):\n    def test_greet(self):\n        self.assertEqual(greet("world"), "Hello, world!")\n'),
            (False, 'import sys\nsys.exit(0)\n'),
            (False, 'import os\nos._exit(0)\n'),
            (False, 'class Tests(unittest.TestCase):\n    def test_dead(self):\n        if False:\n            greet("world")\n        self.assertTrue(True)\n'),
            (False, 'class Tests(unittest.TestCase):\n    def test_math(self):\n        self.assertEqual(2 + 2, 4)\n'),
            (False, 'def unused():\n    greet("world")\nclass Tests(unittest.TestCase):\n    def test_math(self):\n        self.assertTrue(True)\n'),
            (False, 'greet("world")\nclass Tests(unittest.TestCase):\n    def test_math(self):\n        self.assertTrue(True)\n'),
            (False, 'class Tests(unittest.TestCase):\n    def test_call_only(self):\n        greet("world")\n'),
            (True, 'def helper():\n    return greet("world")\nclass Tests(unittest.TestCase):\n    def test_helper(self):\n        self.assertEqual(helper(), "Hello, world!")\n'),
            (True, 'class Tests(unittest.TestCase):\n    def setUp(self):\n        self.greeting = greet("world")\n    def test_setup(self):\n        self.assertEqual(self.greeting, "Hello, world!")\n'),
            (True, 'class Tests(unittest.TestCase):\n    def test_empty(self):\n        with self.assertRaises(ValueError):\n            greet("")\n'),
        ]
        for mode in self.spec(50)['modes']:
            for expected, tests in variants:
                body = prefix + tests
                body += '# padding\n' * (50 - len(body.splitlines()))
                with self.subTest(mode=mode, tests=tests):
                    self.assertEqual(self.disk(50, mode, body), expected)

    def test_reference_loaded_by_absolute_path_and_wrong_reference(self):
        for correct in (True, False):
            path = self.root / ('fixtures/codegen/greeter.py' if correct else 'other.py')
            if not correct:
                path.write_text('def greet(name):\n    return "Hello, " + name + "!"\n')
            body = ('import unittest\nimport importlib.util\n'
                    f'spec = importlib.util.spec_from_file_location("custom", {str(path)!r})\n'
                    'mod = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(mod)\n'
                    'hello = mod.greet\nclass Tests(unittest.TestCase):\n'
                    '    def test_greeting(self):\n        self.assertEqual(hello("world"), "Hello, world!")\n')
            body += '# padding\n' * (50 - len(body.splitlines()))
            self.assertEqual(self.disk(50, 'direct', body), correct)

    def test_python_source_encodings(self):
        for lines in (49, 50):
            for mode in self.spec(lines)['modes']:
                with self.subTest(lines=lines, mode=mode):
                    self.assertTrue(self.disk(lines, mode, b'\xef\xbb\xbf' + module(lines).encode()))
                    body = module(lines).replace('# padding', '# café', 1)
                    body = '# coding: latin-1\n' + body.rsplit('# padding\n', 1)[0]
                    self.assertTrue(self.disk(lines, mode, body.encode('latin-1')))
                    self.assertFalse(self.disk(lines, mode, b'\xef\xbb\xbfdef greet(:\n' + b'# padding\n' * (lines - 1)))


if __name__ == '__main__':
    unittest.main()
