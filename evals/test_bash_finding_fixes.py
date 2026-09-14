"""Leading redirects, parser work bounds, and attributable Bash denies."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

HOOK = Path(__file__).resolve().parents[1] / "plugin/hooks/check-bash-read"


class BashFindingFixesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="shunt-bash-findings-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.large = b"x" * 80000
        (self.root / "large").write_bytes(self.large)
        (self.root / "small").write_bytes(b"ok\n")
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith("TOKEN_SHUNT_") and k != "CDPATH"}

    def check(self, command, expected, stdout=None, stderr=0):
        result = subprocess.run([str(HOOK)], input=json.dumps({"tool_input": {
            "command": command}}), cwd=self.root, env=self.env, text=True,
            capture_output=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)["hookSpecificOutput"] if result.stdout else {}
        self.assertEqual(payload.get("permissionDecision", "pass"), expected, command)
        if expected == "deny":
            self.assertIn("token-shunt", payload["permissionDecisionReason"])
        if stdout is not None:
            actual = subprocess.run(["bash", "--noprofile", "--norc", "-c", command],
                                    cwd=self.root, env=self.env, capture_output=True,
                                    timeout=8)
            self.assertEqual(actual.returncode, 0, actual.stderr.decode())
            self.assertEqual(len(actual.stdout), stdout, command)
            self.assertEqual(len(actual.stderr), stderr, command)
        return payload

    def test_staging_cannot_reuse_pre_execution_file_size(self):
        for prep in ('cp large staged', 'mv copy staged', 'ln -f large staged',
                     'tee staged < large > /dev/null', 'install large staged',
                     "python3 -c 'import shutil; shutil.copyfile(\"large\", \"staged\")'"):
            for existing in (False, True):
                with self.subTest(prep=prep, existing=existing):
                    (self.root / 'copy').write_bytes(self.large)
                    staged = self.root / 'staged'
                    staged.unlink(missing_ok=True)
                    if existing:
                        staged.write_text('small')
                    self.check(prep + '; cat staged', 'deny', len(self.large))
        (self.root / 'staged').unlink()
        self.check('cp large staged | cat staged', 'deny')
        self.check('cat staged >&2 | cp large staged | cat', 'deny')
        self.check('cp large staged | head -c 1', 'pass')
        self.check('cd . && cat small', 'pass', 3)
        self.check('cp large staged', 'pass', 0)
        self.check('head -c 1 staged', 'pass', 1)

    def test_append_assignment_prefixes_are_real_bash_assignments(self):
        for command in ('x+=v cat large', 'x=1 y+=v cat large',
                        '2>errors x+=v cat large', 'true; x+=v cat large',
                        'cat small | x+=v cat large'):
            self.check(command, 'deny', len(self.large))
        self.check('x+=v head -c 1 large', 'pass', 1)
        self.check('x+=v cat large | head -c 1', 'pass', 1)

    def test_command_word_expansion_and_literal_controls(self):
        for command in ('{cat,} large', '{c,}at large',
                        'x+=v {cat,} large', 'true; {cat,} large',
                        'cat small | {cat,} large', '{cat,} large > output',
                        '[c]at large', '/bin/{cat,} large'):
            self.check(command, 'deny')
        for command in ("'{cat,}' large", r'\{cat,\} large',
                        "'[c]at' large", '"cat" small'):
            self.check(command, 'pass')
        result = subprocess.run(['bash', '-c', '{cat,} large'], cwd=self.root,
                                capture_output=True)
        self.assertEqual(result.stdout, self.large)

    def test_leading_redirect_reader_paths(self):
        for command in ("2>errors cat large", "22>>errors cat large",
                        "cat small | 2>errors cat large",
                        "true; 2>errors cat large", "true && 2>errors cat large",
                        "2>errors FLAG=yes 3>other cat large",
                        "<<EOF cat large\nEOF", "<<'EOF' cat large\nEOF",
                        "<<-EOF cat large\n\tEOF"):
            with self.subTest(command=command):
                self.check(command, "deny", 80000)
        for command in ("1>&2 cat large", "001>&2 cat large", "1<&2 cat large",
                        "1<&2 cat large | head -c 1",
                        "cat large >output 1<&2",
                        "1>&2 cat large | head -c 1",
                        "3>&2 FLAG=yes 1>&3 cat large | head -c 1"):
            with self.subTest(command=command):
                self.check(command, "deny", 0, 80000)

    def test_supported_reader_alternates(self):
        for command in ("2>errors head -c 70000 large",
                        "2>errors tail -c 70000 large"):
            with self.subTest(command=command):
                self.check(command, "deny", 70000)
        for command in ("2>errors less large", "2>errors more large"):
            self.check(command, "deny")
        self.check("2>errors head -c 1 large", "pass", 1)
        self.check("1>&2 head -c 1 large | head -c 1", "pass", 0, 1)

    def test_safe_routes_and_small_files(self):
        for command, stdout, stderr in (
            (">output cat large", 0, 0), ("001>output cat large", 0, 0),
            ("2>errors cat small", 3, 0),
            (">output <<EOF cat large\nEOF", 0, 0),
            (">output <<'EOF' cat large\ncat large\nEOF", 0, 0), ("1>&2 cat small", 0, 3),
            ("2>errors cat large | head -c 1", 1, 0),
            ("3>&1 1>&3 cat large | head -c 1", 1, 0),
            (">output 2>errors cat large | head -c 1", 0, 0),
        ):
            with self.subTest(command=command):
                self.check(command, "pass", stdout, stderr)

    def test_heredoc_body_is_data(self):
        for prefix, delimiter, body in (
            ("<<EOF", "EOF", "cat large"),
            ("<<'EOF'", "EOF", "cat large # literal"),
            (r"<<E\OF", "EOF", "cat large"),
            ("<<-EOF", "\tEOF", "\tcat large"),
        ):
            self.check(f"{prefix} cat small\n{body}\n{delimiter}", "pass", 3)
        self.check("<<EOF cat small\ncat large\nEOF\ncat large", "deny", 80003)
        self.check("<<A <<B cat small\ncat large\nA\ncat large\nB", "pass", 3)
        self.check("<<'A # B' cat small\ncat large\nA # B", "pass", 3)

    def test_heredoc_delimiter_variants_do_not_hide_following_reader(self):
        self.check("<<E\\\nOF cat small\nEOF\ncat large", "deny", 80003)
        self.check("<<EOF cat small\nEO\\\nF\ncat large", "deny", 80003)
        self.check("<<E\\\nOF cat small\nEO\\\nF\ncat large", "deny", 80003)
        self.check("<<$'EOF' cat small\nEOF\ncat large", "deny", 80003)
        self.check('<<$"EOF" cat small\nEOF\ncat large', "deny", 80003)

    def test_input_redirect_cannot_create_pure_stdin_byte_proof(self):
        self.check("cat large | <small head -c 1", "deny", 1)
        self.check("cat large | <<EOF head -c 1\nx\nEOF", "deny", 1)

    def test_repeated_redirects_finish_before_hook_timeout(self):
        for prefix in ("", "3>errors "):
            command = prefix + "cat large " + "> /dev/null " * 300 + ">&2"
            started = time.monotonic()
            self.check(command, "deny", 0, 80000)
            self.assertLess(time.monotonic() - started, 8)
        self.check("cat large " + "> /dev/null " * 300, "pass", 0)

    def test_named_descriptor_cannot_manufacture_stdout_isolation(self):
        for command in ("{fd}>/dev/null cat large",
                        "{reader_fd}>/dev/null cat large | cat",
                        "true; {fd}>/dev/null cat large"):
            with self.subTest(command=command):
                self.check(command, "deny", 80000)
        (self.root / "{fd}").write_bytes(b"ok\n")
        self.check("cat '{fd}'", "pass", 3)
        self.check(r"cat \{fd\}", "pass", 3)
        self.check("cat '{fd}'>output", "pass", 0)
        self.check(r"cat \{fd\}>output", "pass", 0)

    def test_arithmetic_shift_does_not_mask_following_reader(self):
        self.check("echo $((1<<2))\ncat large", "deny", 80002)
        self.check("echo $((1<<2))\ncat small", "pass", 5)

    def test_prefix_redirect_cd_cannot_leave_stale_inspection_directory(self):
        (self.root / "target").mkdir()
        (self.root / "target/only-there").write_bytes(self.large)
        for prefix in ("2>/dev/null ", "FLAG=yes ", "3>/dev/null FLAG=yes "):
            with self.subTest(prefix=prefix):
                self.check(prefix + "cd target && cat only-there", "deny", 80000)
        self.check("cd target && cat only-there", "deny", 80000)
        (self.root / "target/tiny").write_bytes(b"ok\n")
        self.check("cd target && cat tiny", "pass", 3)

    def test_deny_origins_are_explicit(self):
        self.check("cd '$UNKNOWN'; cat small", "deny")
        self.check("cat <(cat large)", "deny")


if __name__ == "__main__":
    unittest.main()
