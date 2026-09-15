"""Check real shell output alongside clean-context finding regressions."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

HOOKS = Path(__file__).resolve().parents[1] / 'plugin/hooks'


class CleanContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'big.txt').write_text('x\n' * 400)
        (self.root / 'small').write_text('ok\n')
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith('TOKEN_SHUNT_') and k != 'CDPATH'}

    def invoke(self, command=None, *, event=None, hook='check-bash-read'):
        if event is None:
            event = {'tool_input': {'command': command}}
        result = subprocess.run([str(HOOKS / hook)], input=json.dumps(event),
                                cwd=self.root, env=self.env, text=True,
                                capture_output=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        return json.loads(result.stdout)['hookSpecificOutput']['permissionDecision'] if result.stdout else 'pass'

    def shell(self, command):
        result = subprocess.run(['bash', '--noprofile', '--norc', '-c', command],
                                cwd=self.root, env=self.env, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout, result.stderr

    def test_active_dollars_and_literal_controls(self):
        for command in ('cat $PWD/big.txt', 'cat "$PWD/big.txt"',
                        'F=big.txt; cat $F', 'X=cat; $X big.txt',
                        'X=cat; "$X" big.txt', 'cat$IFS big.txt',
                        "$'cat' big.txt", "cat $'big.txt'",
                        'cat ${PWD}/big.txt', 'cat small | $X big.txt'):
            with self.subTest(command=command):
                self.assertEqual(self.invoke(command), 'deny')
        for command in ('cat $PWD/big.txt', 'X=cat; $X big.txt', 'cat$IFS big.txt'):
            self.assertEqual(self.shell(command)[0], b'x\n' * 400)
        (self.root / '$literal').write_text('ok\n')
        for command in ("cat '$literal'", r'cat \$literal', r'cat "\$literal"'):
            self.assertEqual(self.invoke(command), 'pass')
            self.assertEqual(self.shell(command)[0], b'ok\n')

    def test_heredoc_execution_and_false_positive(self):
        for body in ('$(cat big.txt)', '`cat big.txt`', '"$(cat big.txt)"'):
            command = 'cat <<EOF\n' + body + '\nEOF'
            self.assertEqual(self.invoke(command), 'deny')
            self.assertIn(b'x\nx\n', self.shell(command)[0])
        for command in ("cat <<'EOF'\n$(cat big.txt)\nEOF",
                        'cat <<EOF\n\\$(cat big.txt)\nEOF'):
            self.assertEqual(self.invoke(command), 'pass')
            self.assertEqual(self.shell(command)[0], b'$(cat big.txt)\n')
        # Bash treats $D as a literal delimiter, so this is data, not a read.
        command = 'cat <<$D\nEOF\ncat big.txt\n$D'
        self.assertEqual(self.invoke(command), 'pass')
        self.assertEqual(self.shell(command)[0], b'EOF\ncat big.txt\n')
        self.assertEqual(self.invoke(command + '\ncat big.txt'), 'deny')
        for delimiter in ('$(true)', '`true`'):
            command = 'cat <<' + delimiter + '\nx\n' + delimiter
            self.assertEqual(self.shell(command)[0], b'x\n')
            self.assertEqual(self.invoke(command), 'deny')
            self.assertEqual(self.invoke(command + '\ncat big.txt'), 'deny')
            quoted = "cat <<'" + delimiter + "'\nx\n" + delimiter
            self.assertEqual(self.invoke(quoted), 'pass')
            self.assertEqual(self.shell(quoted)[0], b'x\n')

    def test_unknown_pipeline_readers_and_side_output(self):
        for command in ("cat big.txt | grep ''", 'echo ok | cat big.txt $(true)',
                        'cat big.txt 1>&2 | wc -l',
                        'cat big.txt | tee /dev/stderr | wc -l'):
            self.assertEqual(self.invoke(command), 'deny', command)
            self.assertIn(b'x\nx\n', b''.join(self.shell(command)))
        for command in ('head -n5 big.txt | cat', 'tail -n5 big.txt | cat'):
            self.assertEqual(self.invoke(command), 'pass')
            self.assertEqual(self.shell(command)[0], b'x\n' * 5)
        self.assertEqual(self.invoke('cat small | grep ok'), 'pass')

    def test_zero_and_quoted_parentheses(self):
        for command in ('head -n0 big.txt', 'tail -n0 big.txt'):
            self.assertEqual(self.invoke(command), 'pass')
            self.assertEqual(self.shell(command)[0], b'')
        (self.root / 'sub').mkdir()
        (self.root / 'sub/f(1).txt').write_text('ok\n')
        self.assertEqual(self.invoke('cd sub; cat "f(1).txt"'), 'pass')

    def test_supplied_cwd_is_authoritative(self):
        target = self.root / 'target\n'
        target.mkdir()
        (target / 'small').write_text('x\n' * 400)
        for hook, inp in [('check-bash-read', {'command': 'cat small'}),
                          ('check-file-size', {'file_path': 'small'})]:
            self.assertEqual(self.invoke(hook=hook, event={'cwd': str(target), 'tool_input': inp}), 'deny')
            self.assertEqual(self.invoke(hook=hook, event={'tool_input': inp}), 'pass')
            for cwd in ('relative', None, str(target) + '\0ignored'):
                self.assertEqual(self.invoke(hook=hook, event={'cwd': cwd, 'tool_input': inp}), 'deny')

    def test_length_bound_precedes_parsing(self):
        for command in ('echo ' + 'x' * 100000, 'cat big.txt ' + '> /dev/null ' * 10000,
                        '# ' + 'x' * 100000, "cat <<'EOF'\n" + 'x' * 100000 + '\nEOF'):
            started = time.monotonic()
            self.assertEqual(self.invoke(command), 'deny')
            self.assertLess(time.monotonic() - started, 2)

    def test_dense_redirect_work_is_bounded(self):
        command = 'cat big.txt ' + '> /dev/null ' * 600 + '>&2'
        self.assertLess(len(command), 8192)
        started = time.monotonic()
        self.assertEqual(self.invoke(command), 'deny')
        self.assertLess(time.monotonic() - started, 6)

    def test_only_one_json_object_is_accepted(self):
        for hook in ('check-bash-read', 'check-file-size'):
            for raw in ('{}\n{}', '[]', 'null'):
                result = subprocess.run([str(HOOKS / hook)], input=raw, text=True,
                                        capture_output=True, env=self.env, timeout=5)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
