"""Run the real catalog disk verification under dotted run directories containing spaces."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
CASES = json.loads((HERE / 'cases.json').read_text())['cases']


class WriterDiscoveryDiskTests(unittest.TestCase):
    def test_catalog_uses_available_interpreter_and_discovery(self):
        self.assertNotIn('python -m', (HERE / 'cases.json').read_text())
        for cid in ('compare-code-writer-ok', 'auto-large-writer'):
            case = next(c for c in CASES if c['id'] == cid)
            self.assertIn('python3 -m unittest discover -s ', case['verify_cmd'])
            for key in ('prompt_direct', 'prompt_delegate'):
                if key in case:
                    self.assertIn(case['verify_cmd'], case[key])

    def test_real_disk_check_passes_and_rejects_unrelated_tests(self):
        for cid in ('compare-code-writer-ok', 'auto-large-writer'):
            with self.subTest(case=cid), tempfile.TemporaryDirectory(prefix='run.writer with spaces.') as directory:
                root = Path(directory)
                for path in ('fixtures/codegen/out', 'verdicts', 'snap', 'cwd'):
                    (root / path).mkdir(parents=True)
                reference = root / 'fixtures/codegen/greeter.py'
                shutil.copyfile(HERE / 'fixtures/codegen/greeter.py', reference)
                original = reference.read_bytes()
                case = next(c for c in CASES if c['id'] == cid)
                spec = json.loads(json.dumps(case).replace('{TMP}', str(root)).replace(
                    '{FIX}', str(root / 'fixtures')))
                target = Path(spec['target'])
                body = ('import sys\nimport unittest\n'
                        f'sys.path.insert(0, {str(reference.parent)!r})\n'
                        'from greeter import greet\n'
                        'class GreetingTests(unittest.TestCase):\n'
                        '    def test_greeting(self):\n'
                        '        self.assertEqual(greet("world"), "Hello, world!")\n')
                command = ('source "$1"; TMP="$2"; FIX="$2/fixtures"; '
                           'VRD="$2/verdicts"; SNAP="$2/snap"; CWD0="$2/cwd"; '
                           'disk_check "$3" auto')
                for related in (True, False):
                    target.write_text(body if related else body.replace(
                        'self.assertEqual(greet("world"), "Hello, world!")',
                        'self.assertEqual(1, 1)'))
                    run = subprocess.run(
                        ['bash', '-c', command, 'test', str(HERE / 'run.sh'),
                         str(root), json.dumps(spec)], capture_output=True, text=True,
                        env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
                    verdict = json.loads((root / 'verdicts' / f'{cid}.auto.disk.json').read_text())
                    self.assertEqual(run.returncode == 0, verdict['disk_ok'], run.stderr)
                    self.assertEqual(verdict['disk_ok'], related, verdict)
                    self.assertEqual(reference.read_bytes(), original)
                    if not related:
                        self.assertIn('mutation not detected', verdict['reason'])


if __name__ == '__main__':
    unittest.main()
