"""Exercise record persistence with an isolated source tree and a free CLI stub."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DoctorRecordTests(unittest.TestCase):
    def run_doctor(self, failure=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            shutil.copy2(ROOT / 'scripts/doctor.sh', root / 'scripts/doctor.sh')
            bindir = root / 'bin'
            bindir.mkdir()
            cli = bindir / 'claude'
            cli.write_text('''#!/bin/bash
if [[ $1 == --version ]]; then echo 'stub-cli 1.0'; exit; fi
printf '%s\\n' '{"type":"system","subtype":"init","plugins":[{"name":"token-shunt"}],"agents":["token-shunt:bulk-reader","token-shunt:code-writer"]}'
''')
            cli.chmod(0o755)
            record = root / 'docs/distribution/doctor-last-probe.txt'
            record.parent.mkdir(parents=True)
            record.write_text('previous record\n')
            if failure in ('directory', 'symlink-directory'):
                record.unlink()
                if failure == 'directory':
                    record.mkdir()
                else:
                    target = root / 'target'
                    target.mkdir()
                    record.symlink_to(target, target_is_directory=True)
            elif failure:
                stub = bindir / ('mktemp' if failure == 'write' else failure)
                if failure == 'write':
                    stub.write_text('#!/bin/bash\n'
                        'if [[ $1 == *doctor-last-probe* ]]; then\n'
                        '  target=${1/XXXXXX/failure}\n'
                        '  mkdir "$target"; printf "%s\\n" "$target"\n'
                        'else exec ' + shutil.which('mktemp') + ' "$@"; fi\n')
                else:
                    stub.write_text('#!/bin/bash\nexit 1\n')
                stub.chmod(0o755)
            result = subprocess.run(['bash', str(root / 'scripts/doctor.sh')],
                env=dict(os.environ, PATH=str(bindir) + ':' + os.environ['PATH']),
                capture_output=True, text=True, timeout=15)
            return result, ('directory' if record.is_dir() else record.read_text()), list(record.parent.glob('*.??????'))

    def test_success_replaces_record(self):
        result, record, leftovers = self.run_doctor()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('recorded probed CLI version', result.stdout)
        self.assertIn('claude --version: stub-cli 1.0', record)
        self.assertEqual([], leftovers)

    def test_prepare_failure_preserves_previous_record(self):
        result, record, _ = self.run_doctor('mkdir')
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn('recorded probed CLI version', result.stdout)
        self.assertIn('could not prepare probe record', result.stderr)
        self.assertEqual('previous record\n', record)

    def test_directory_destinations_are_not_successful_replacements(self):
        for failure in ('directory', 'symlink-directory'):
            with self.subTest(failure=failure):
                result, record, leftovers = self.run_doctor(failure)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn('recorded probed CLI version', result.stdout)
                self.assertIn('could not save probe record', result.stderr)
                self.assertEqual('directory', record)
                self.assertEqual([], leftovers)

    def test_write_failure_preserves_previous_record(self):
        result, record, _ = self.run_doctor('write')
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn('recorded probed CLI version', result.stdout)
        self.assertIn('could not save probe record', result.stderr)
        self.assertEqual('previous record\n', record)

    def test_replace_failure_preserves_previous_record(self):
        result, record, leftovers = self.run_doctor('mv')
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn('recorded probed CLI version', result.stdout)
        self.assertIn('could not save probe record', result.stderr)
        self.assertEqual('previous record\n', record)
        self.assertEqual([], leftovers)


if __name__ == '__main__':
    unittest.main()
