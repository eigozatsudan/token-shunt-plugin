"""Catalog substitution must preserve paths and environment values."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from render_command import render

ROOT = Path(__file__).resolve().parents[1]


class HarnessInputsTests(unittest.TestCase):
    def test_safety_denial_is_distinct_from_routing_denial(self):
        source = (ROOT / 'evals/run.sh').read_text()
        function = source[source.index('check_expect()'):source.index('echo "== fixtures =="')]
        for reason, safety, routing in (
                ('token-shunt: A preceding cd has an unresolved destination.', True, False),
                ('token-shunt: Use /token-shunt:bulk-reader.', True, True),
                ('unrelated denial', False, False)):
            for expect, passes in (('deny_safety', safety), ('deny', routing)):
                payload = json.dumps({'hookSpecificOutput': {
                    'permissionDecision': 'deny', 'permissionDecisionReason': reason}})
                result = subprocess.run(['bash', '-c', function + '\ncheck_expect "$1" "$2" "$3"',
                                         'test', expect, payload, '0'], capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, passes, (expect, reason))
        for payload, code in (('{}', '0'), ('broken', '0'),
                              ('{"hookSpecificOutput":{"permissionDecision":"pass"}}', '0')):
            result = subprocess.run(['bash', '-c', function + '\ncheck_expect deny_safety "$1" "$2"',
                                     'test', payload, code], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)

    def test_fixture_quotes_do_not_execute_path_characters(self):
        fixture = '/tmp/a b\'c"$HOME`false`'
        for template in ('printf "%s" @FIX@/file',
                         "printf '%s' '@FIX@/file'",
                         'printf "%s" "@FIX@/file"'):
            result = subprocess.run(['bash', '-c', render(template, fixture)],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout, fixture + '/file')

    def test_ambient_hook_settings_removed_before_explicit_catalog_settings(self):
        source = (ROOT / 'evals/run.sh').read_text()
        function = source[source.index('run_hook()'):source.index('\ncheck_expect()')]
        with tempfile.TemporaryDirectory() as directory:
            hook = Path(directory) / 'echo-env'
            hook.write_text('#!/bin/bash\nprintf "%s|%s|%s" "${TOKEN_SHUNT_MIN_BYTES-unset}" "${CDPATH-unset}" "$KEEP_TEST"\n')
            hook.chmod(0o755)
            for settings, expected in (({}, 'unset|unset|retained'),
                                       ({'TOKEN_SHUNT_MIN_BYTES': '123'}, '123|unset|retained')):
                result = subprocess.run(
                    ['bash', '-c', function + '\nHOOKS=$1; run_hook echo-env "{}" "$2"; printf "%s" "$OUT"',
                     'test', directory, json.dumps(settings)],
                    env={**os.environ, 'TOKEN_SHUNT_MIN_BYTES': '999999',
                         'CDPATH': '/unwanted', 'KEEP_TEST': 'retained'},
                    capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout, expected)

    def test_environment_values_keep_spaces_and_newlines(self):
        source = (ROOT / 'evals/run.sh').read_text()
        function = source[source.index('run_hook()'):source.index('\ncheck_expect()')]
        with tempfile.TemporaryDirectory() as directory:
            hook = Path(directory) / 'echo-env'
            hook.write_text('#!/bin/bash\nprintf "%s" "$EXAMPLE"\n')
            hook.chmod(0o755)
            value = 'space value\nand another line'
            result = subprocess.run(
                ['bash', '-c', function + '\nHOOKS=$1; run_hook echo-env "{}" "$2"; printf "%s" "$OUT"',
                 'test', directory, json.dumps({'EXAMPLE': value})],
                capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout, value)


if __name__ == '__main__':
    unittest.main()
