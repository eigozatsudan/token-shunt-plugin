"""Concrete bypass regressions from the independent harness review."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HOOKS = Path(__file__).resolve().parents[1] / 'plugin/hooks'


class ReviewHooksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='shunt-review-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith('TOKEN_SHUNT_') and k != 'CDPATH'}
        (self.root / 'big.txt').write_bytes(b'x\n' * 400)
        (self.root / 'small.txt').write_text('ok\n')
        (self.root / 'sub').mkdir()
        (self.root / 'sub/f').write_bytes(b'x' * 70000)

    def decision(self, hook='check-bash-read', **tool_input):
        result = subprocess.run([str(HOOKS / hook)], cwd=self.root,
                                env=self.env, input=json.dumps({'tool_input': tool_input}),
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return (json.loads(result.stdout)['hookSpecificOutput']['permissionDecision']
                if result.stdout else 'pass')

    def test_process_substitution_never_gets_isolation_or_byte_bound(self):
        for command in ['cat big.txt > >(cat)', 'tee >(cat big.txt)',
                        'cat big.txt | tee >(cat) | head -c5',
                        'diff <(cat big.txt) <(cat small.txt)', 'cat <(cat big.txt)']:
            with self.subTest(command=command):
                self.assertEqual(self.decision(command=command), 'deny')
        self.assertEqual(self.decision(command="printf '%s' '<(cat big.txt)'"), 'pass')
        self.assertEqual(self.decision(command='echo hello # >(cat big.txt)'), 'pass')

    def test_old_style_tail_plus_requires_full_threshold(self):
        self.assertEqual(self.decision(command='tail +5 big.txt'), 'deny')
        self.assertEqual(self.decision(command='tail +5 small.txt'), 'pass')
        self.assertEqual(self.decision(command='tail -5 big.txt'), 'pass')
        (self.root / '+5').write_text('small\n')
        self.assertEqual(self.decision(command='tail -- +5'), 'pass')

    def test_unresolved_expansions(self):
        for command in ['cat *.txt', 'cat ~/big.txt', 'cat {big,small}.txt',
                        'head -n 400 *.txt', 'cat b?g.txt', 'cat [b]ig.txt',
                        'cat *.txt | cat', 'true; cat *.txt']:
            with self.subTest(command=command):
                self.assertEqual(self.decision(command=command), 'deny')
        (self.root / '*.txt').write_text('literal\n')
        self.assertEqual(self.decision(command="cat '*.txt'"), 'pass')
        self.assertEqual(self.decision(command=r'cat \*.txt'), 'pass')
        self.assertEqual(self.decision(command='cat *.txt | head -c5'), 'pass')
        self.assertEqual(self.decision(command='cat *.txt > output'), 'pass')

    def test_redirect_cd_does_not_use_stale_directory(self):
        for command in ['cd sub > /dev/null; cat f', 'cd sub 2>/dev/null && cat f',
                        'cd sub > /dev/null; head -n 1 f']:
            with self.subTest(command=command):
                self.assertEqual(self.decision(command=command), 'deny')

    def test_underreported_stat_checks_actual_bytes_and_newlines(self):
        bindir = self.root / 'bin'
        bindir.mkdir()
        fake_stat = bindir / 'stat'
        fake_stat.write_text('#!/bin/sh\nprintf "0\\n"\n')
        fake_stat.chmod(0o755)
        self.env['PATH'] = str(bindir) + os.pathsep + self.env['PATH']
        for data in [b'x' * 65537, b'x' * 65536 + b'\n', b'x' * 65535 + b'\n\n']:
            (self.root / 'grown').write_bytes(data)
            with self.subTest(size=len(data)):
                self.assertEqual(self.decision(command='cat grown'), 'deny')
                for tool in ['head', 'tail']:
                    self.assertEqual(self.decision(command=f'{tool} -c70000 grown'), 'deny')
                    self.assertEqual(self.decision(command=f'{tool} -c65536 grown'), 'pass')
                self.assertEqual(self.decision('check-file-size', file_path=str(self.root / 'grown')), 'deny')
                self.assertEqual(self.decision('check-file-size', file_path=str(self.root / 'grown'), limit=2), 'deny')
        (self.root / 'grown').write_bytes(b'x' * 65535 + b'\n')
        self.assertEqual(self.decision(command='cat grown'), 'pass')
        for tool in ['head', 'tail']:
            self.assertEqual(self.decision(command=f'{tool} -c70000 grown'), 'pass')
            self.assertEqual(self.decision(command=f'{tool} -c70000 small.txt'), 'pass')
        self.env['TOKEN_SHUNT_SCAN_BUDGET_BYTES'] = '1024'
        for tool in ['head', 'tail']:
            self.assertEqual(self.decision(command=f'{tool} -c70000 grown'), 'deny')
            self.assertEqual(self.decision(command=f'{tool} -c65536 grown'), 'pass')

    def test_opt_in_log_attributes_decision_without_dumping_stdin(self):
        log = self.root / 'hook.jsonl'
        self.env['TOKEN_SHUNT_HOOK_LOG'] = str(log)
        for name, tool_input in [
                ('check-bash-read', {'command': 'cat big.txt'}),
                ('check-file-size', {'file_path': str(self.root / 'big.txt')})]:
            result = subprocess.run([str(HOOKS / name)], cwd=self.root, env=self.env,
                                    input=json.dumps({'tool_input': tool_input,
                                                      'tool_use_id': 'tool-1', 'session_id': 'session-1',
                                                      'unrelated_secret': 'do not log'}),
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            record = json.loads(log.read_text().splitlines()[-1])
            self.assertEqual(record['tool_use_id'], 'tool-1')
            self.assertEqual(record['session_id'], 'session-1')
            self.assertEqual(record['decision'], 'deny')
            for field, value in tool_input.items():
                self.assertEqual(record[field], value)
            self.assertNotIn('unrelated_secret', record)
            self.assertNotIn('tool_input', record)

    def test_unsupported_bash_guard(self):
        # Exercise the exact guard with an injected version; BASH_VERSINFO is
        # readonly, so use a copy replacing only its version expression.
        for name in ['check-file-size', 'check-bash-read', 'check-jq']:
            source = (HOOKS / name).read_text()
            self.assertIn('${BASH_VERSINFO[0]:-0}', source)
            copy = self.root / name
            copy.write_text(source.replace('${BASH_VERSINFO[0]:-0}', '3', 1))
            result = subprocess.run([shutil.which('bash'), str(copy)], input='{}',
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0 if name == 'check-jq' else 2)
            self.assertIn('Bash 4', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
