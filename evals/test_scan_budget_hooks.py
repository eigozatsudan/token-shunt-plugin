"""Regression checks for bounded scans, including lines longer than the budget."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HOOKS = Path(__file__).resolve().parents[1] / 'plugin' / 'hooks'


class ScanBudgetHooksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='shunt-budget-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith('TOKEN_SHUNT_')}
        self.env['TOKEN_SHUNT_SCAN_BUDGET_BYTES'] = '1024'
        self.env['TOKEN_SHUNT_SCAN_BUDGET_MS'] = '10000'
        (self.root / 'huge.txt').write_bytes(b'x' * (1024 * 1024))

    def run_hook(self, hook, inp):
        proc = subprocess.run([str(HOOKS / hook)],
                              input=json.dumps({'tool_input': inp}),
                              text=True, capture_output=True, env=self.env,
                              cwd=self.root, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, '')
        return json.loads(proc.stdout)['hookSpecificOutput'] if proc.stdout else None

    def read(self, name, **kwargs):
        return self.run_hook('check-file-size', {
            'file_path': str(self.root / name), **kwargs})

    def bash(self, command):
        return self.run_hook('check-bash-read', {'command': command})

    def assert_budget_deny(self, result):
        self.assertIsNotNone(result)
        self.assertEqual(result['permissionDecision'], 'deny')
        reason = result['permissionDecisionReason']
        self.assertIn('Scan budget exceeded', reason)
        count = re.search(r'read_bytes=(\d+)/1024', reason)
        self.assertIsNotNone(count, reason)
        self.assertLessEqual(int(count[1]), 1025, reason)

    def test_huge_line_skipped_before_target_is_bounded(self):
        self.assert_budget_deny(self.read('huge.txt', offset=2, limit=1))

    def test_huge_target_line_is_denied(self):
        for result in [self.read('huge.txt', limit=1),
                       self.bash('head -n 1 huge.txt'),
                       self.bash('tail -n 1 huge.txt')]:
            self.assertEqual(result['permissionDecision'], 'deny')

    def test_whole_file_scan_respects_small_budget(self):
        (self.root / 'medium.txt').write_bytes(b'x' * 4096)
        self.assert_budget_deny(self.read('medium.txt'))
        self.assert_budget_deny(self.bash('cat medium.txt'))

    def test_budget_boundary_and_final_newline(self):
        for body in [b'x' * 1024, b'x' * 1023 + b'\n']:
            (self.root / 'exact.txt').write_bytes(body)
            with self.subTest(newline=body.endswith(b'\n')):
                self.assertIsNone(self.read('exact.txt'))
                self.assertIsNone(self.bash('head -n 1 exact.txt'))
                self.assertIsNone(self.bash('tail -n 1 exact.txt'))
        (self.root / 'over.txt').write_bytes(b'x' * 1025)
        self.assert_budget_deny(self.read('over.txt'))

    def test_small_range_before_huge_line_still_passes(self):
        (self.root / 'prefix.txt').write_bytes(b'ok\n' + b'x' * (1024 * 1024))
        self.assertIsNone(self.read('prefix.txt', limit=1))
        self.assertIsNone(self.bash('head -n 1 prefix.txt'))

    def test_small_tail_after_huge_line_still_passes(self):
        for ending in [b'ok', b'ok\n']:
            (self.root / 'suffix.txt').write_bytes(b'x' * (1024 * 1024) + b'\n' + ending)
            with self.subTest(ending=ending):
                self.assertIsNone(self.bash('tail -n 1 suffix.txt'))
                self.assertEqual(self.bash('tail -n 2 suffix.txt')['permissionDecision'], 'deny')

    def test_truncated_prefix_is_not_treated_as_eof(self):
        (self.root / 'prefix.txt').write_bytes(b'first\n' + b'x' * 2048 + b'\nlast\n')
        self.assert_budget_deny(self.read('prefix.txt', offset=2, limit=1))
        self.assert_budget_deny(self.read('prefix.txt', offset=3, limit=1))

    def test_line_and_byte_thresholds_match_actual_ranges(self):
        self.env['TOKEN_SHUNT_MIN_LINES'] = '2'
        self.env['TOKEN_SHUNT_MIN_BYTES'] = '8'
        for body in [b'\n\na', b'ab\ncd\nef', b'12345678\n',
                     b'12345678', b'a\n123456789\nz\n', b'\x00\n\x00\n\x00']:
            (self.root / 'ranges.txt').write_bytes(body)
            lines = body.split(b'\n')
            records = [part + b'\n' for part in lines[:-1]]
            if lines[-1]:
                records.append(lines[-1])
            for count in [1, 2, 3]:
                for command, chosen in [('head', records[:count]),
                                        ('tail', records[-count:])]:
                    with self.subTest(body=body, count=count, command=command):
                        expected = len(chosen) > 2 or len(b''.join(chosen)) > 8
                        result = self.bash(f'{command} -n {count} ranges.txt')
                        self.assertEqual(result is not None, expected)

    def test_failed_input_reader_cannot_pass(self):
        bindir = self.root / 'bin'
        bindir.mkdir()
        wrapper = bindir / 'head'
        wrapper.write_text('#!/bin/sh\nprintf "ok\\n"\nexit 1\n')
        wrapper.chmod(0o755)
        self.env['PATH'] = str(bindir) + os.pathsep + self.env['PATH']
        result = self.read('huge.txt', limit=1)
        self.assertEqual(result['permissionDecision'], 'deny')

    def test_awk_never_receives_entire_huge_line(self):
        # Observe actual input fed to the line parser, independently of the
        # hook's reported counters. The observer buffers only this 1MiB fixture.
        real_awk = shutil.which('awk')
        bindir = self.root / 'bin'
        bindir.mkdir()
        log = self.root / 'parser-bytes.jsonl'
        wrapper = bindir / 'awk'
        wrapper.write_text(
            '#!' + sys.executable + '\n'
            'import sys, subprocess, json\n'
            'data = sys.stdin.buffer.read()\n'
            f'with open({str(log)!r}, "a") as out: out.write(json.dumps(len(data)) + "\\n")\n'
            f'proc = subprocess.run([{real_awk!r}, *sys.argv[1:]], input=data)\n'
            'raise SystemExit(proc.returncode)\n')
        wrapper.chmod(0o755)
        self.env['PATH'] = str(bindir) + os.pathsep + self.env['PATH']
        for invoke in [lambda: self.read('huge.txt', offset=2, limit=1),
                       lambda: self.bash('head -n 1 huge.txt')]:
            log.write_text('')
            invoke()
            counts = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertTrue(counts)
            self.assertLessEqual(max(counts), 1025)


if __name__ == '__main__':
    unittest.main()
