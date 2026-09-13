"""Regression checks for the operational review's confirmed Bash findings."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HOOK = Path(__file__).resolve().parents[1] / "plugin/hooks/check-bash-read"


class BashOperationalHooksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="shunt-operational-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.large = (b"x" * 819 + b"\n") * 100
        self.small = b"small\n"
        (self.root / "large.txt").write_bytes(self.large)
        (self.root / "small.txt").write_bytes(self.small)
        for name in ("#large.txt", "file#name", "file #name"):
            (self.root / name).write_bytes(self.large)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith("TOKEN_SHUNT_")}

    def assert_command(self, command, decision, output_bytes):
        # Evaluate before execution: tee and redirections can replace operands.
        result = subprocess.run([str(HOOK)], input=json.dumps({"tool_input": {
            "command": command}}), cwd=self.root, env=self.env, text=True,
            capture_output=True, timeout=10)
        # Check Bash's actual stdout as well as the hook decision, so a parsing
        # assertion cannot accidentally encode a false-positive shell model.
        actual = subprocess.run(["bash", "--noprofile", "--norc", "-c", command],
                                cwd=self.root, env=self.env, capture_output=True,
                                timeout=10)
        self.assertEqual(actual.returncode, 0, actual.stderr.decode())
        self.assertEqual(len(actual.stdout), output_bytes)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        observed = (json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]
                    if result.stdout else "pass")
        self.assertEqual(observed, decision, command)

    def test_comment_redirection_does_not_hide_stdout(self):
        self.assert_command("cat large.txt # > discarded", "deny", len(self.large))

    def test_comment_file_is_not_an_operand(self):
        self.assert_command("cat small.txt # large.txt", "pass", len(self.small))

    def test_comment_operators_are_not_commands(self):
        self.assert_command("cat small.txt # | cat large.txt; cat large.txt",
                            "pass", len(self.small))

    def test_newline_ends_comment(self):
        self.assert_command("cat small.txt # > discarded\ncat large.txt",
                            "deny", len(self.small) + len(self.large))

    def test_hash_in_filename_is_not_comment(self):
        for filename in ("'#large.txt'", '"#large.txt"', r"\#large.txt", "file#name",
                         "''#large.txt", r"file\ #name"):
            with self.subTest(filename=filename):
                self.assert_command("cat " + filename, "deny", len(self.large))

    def test_last_cat_explicit_input(self):
        self.assert_command("cat small.txt | cat large.txt", "deny", len(self.large))

    def test_last_cat_input_after_bounded_middle_stage(self):
        self.assert_command("cat small.txt | head -c 1 | cat large.txt",
                            "deny", len(self.large))

    def test_middle_cat_explicit_input(self):
        self.assert_command("cat small.txt | cat large.txt | cat",
                            "deny", len(self.large))

    def test_small_pipeline_passes(self):
        self.assert_command("cat small.txt | cat small.txt | cat",
                            "pass", len(self.small))

    def test_tee_file_is_output_not_input(self):
        self.assert_command("cat small.txt | tee large.txt | cat",
                            "pass", len(self.small))

    def test_stdout_redirect_aliases(self):
        for target in ("/dev/stdout", "/dev/fd/1", "/proc/self/fd/1"):
            if not Path(target).exists():
                continue  # These descriptor aliases are platform dependent.
            with self.subTest(target=target):
                self.assert_command("cat large.txt > " + target, "deny", len(self.large))
                self.assert_command(f'cat large.txt>"{target}"&', "deny", len(self.large))

    @unittest.skipUnless(Path("/dev/stdout").exists(), "requires /dev/stdout")
    def test_stdout_redirect_symlink(self):
        (self.root / "stdout-link").symlink_to("/dev/stdout")
        self.assert_command("cat large.txt > stdout-link", "deny", len(self.large))

    def test_regular_file_redirect_passes(self):
        self.assert_command("cat large.txt > output.txt", "pass", 0)
        self.assertEqual((self.root / "output.txt").read_bytes(), self.large)

    def test_null_redirect_passes(self):
        self.assert_command("cat large.txt > /dev/null", "pass", 0)

    def test_quoted_regular_file_redirect_passes(self):
        self.assert_command('cat large.txt>"output space.txt"', "pass", 0)
        self.assertEqual((self.root / "output space.txt").read_bytes(), self.large)

    def test_multiple_regular_file_redirects_pass(self):
        self.assert_command("cat large.txt > first.txt > final.txt", "pass", 0)
        self.assertEqual((self.root / "first.txt").read_bytes(), b"")
        self.assertEqual((self.root / "final.txt").read_bytes(), self.large)

    @unittest.skipUnless(Path("/dev/stdout").exists(), "requires /dev/stdout")
    def test_mixed_redirect_targets_conservatively_denied(self):
        # /dev/stdout reopens the already redirected descriptor here, so Bash
        # emits no captured output. Mixed targets intentionally stay conservative.
        self.assert_command("cat large.txt > first.txt > /dev/stdout",
                            "deny", 0)


if __name__ == "__main__":
    unittest.main()
