"""Optional logging must preserve hook protocol output and avoid FIFO stalls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HOOKS = Path(__file__).resolve().parents[1] / 'plugin' / 'hooks'


class HookLoggingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith('TOKEN_SHUNT_')}

    def helper(self, target, **kwargs):
        return subprocess.run([sys.executable, str(HOOKS / 'write-hook-log')],
            input='{"decision":"pass"}', text=True, timeout=2,
            env=dict(self.env, TOKEN_SHUNT_HOOK_LOG=str(target)), **kwargs)

    def test_normal_append_and_private_creation(self):
        target = self.root / 'log'
        for _ in range(2):
            result = self.helper(target, capture_output=True)
            self.assertEqual((0, '', ''), (result.returncode, result.stdout, result.stderr))
        self.assertEqual([{'decision': 'pass'}] * 2,
                         [json.loads(line) for line in target.read_text().splitlines()])
        self.assertEqual(0, target.stat().st_mode & 0o077)

    def test_special_destinations_and_symlinks_are_silent(self):
        fifo = self.root / 'fifo'
        os.mkfifo(fifo)
        target = self.root / 'untouched'
        target.write_text('original')
        link = self.root / 'link'
        link.symlink_to(target)
        for destination in (fifo, link, '/dev/stdout', '/dev/stderr', '/dev/null', self.root):
            with self.subTest(destination=destination):
                result = self.helper(destination, capture_output=True)
                self.assertEqual((0, '', ''), (result.returncode, result.stdout, result.stderr))
        self.assertEqual('original', target.read_text())

    def test_regular_stream_aliases_are_rejected_by_inode(self):
        for stream in ('stdout', 'stderr'):
            target = self.root / stream
            alias = self.root / (stream + '-hardlink')
            target.write_text('original')
            os.link(target, alias)
            with target.open('a') as capture:
                options = {'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE}
                options[stream] = capture
                result = self.helper(alias, **options)
            self.assertEqual(0, result.returncode)
            self.assertEqual('original', target.read_text())

    def test_real_hook_preserves_regular_stderr_alias(self):
        target = self.root / 'stderr'
        alias = self.root / 'stderr-alias'
        target.write_text('original')
        os.link(target, alias)
        for hook in ('check-file-size', 'check-bash-read'):
            with target.open('a') as capture:
                result = subprocess.run([str(HOOKS / hook)], input='{}', text=True,
                    stdout=subprocess.PIPE, stderr=capture, timeout=3,
                    env=dict(self.env, TOKEN_SHUNT_HOOK_LOG=str(alias)))
            self.assertEqual((0, ''), (result.returncode, result.stdout))
            self.assertEqual('original', target.read_text())

    def test_real_hooks_keep_one_decision_and_append_regular_logs(self):
        source = self.root / 'big.txt'
        source.write_text('x\n' * 400)
        fifo = self.root / 'fifo'
        os.mkfifo(fifo)
        log = self.root / 'log'
        for name, tool_input in (
                ('check-file-size', {'file_path': str(source)}),
                ('check-bash-read', {'command': 'cat ' + str(source)})):
            for target in ('/dev/stdout', '/dev/stderr', fifo, log):
                with self.subTest(hook=name, target=target):
                    result = subprocess.run([str(HOOKS / name)],
                        input=json.dumps({'tool_input': tool_input}), text=True,
                        capture_output=True, timeout=3,
                        env=dict(self.env, TOKEN_SHUNT_HOOK_LOG=str(target)))
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual('', result.stderr)
                    self.assertEqual('deny', json.loads(result.stdout)
                        ['hookSpecificOutput']['permissionDecision'])
        self.assertEqual(2, len(log.read_text().splitlines()))


if __name__ == '__main__':
    unittest.main()
