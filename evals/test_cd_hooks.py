"""Relative Bash file operands must follow a supported leading cd chain."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HOOK = Path(__file__).resolve().parents[1] / "plugin/hooks/check-bash-read"


class CdHooksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="shunt-cd-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "destination space").mkdir()
        (self.root / "same.txt").write_bytes(b"x" * 70000)
        (self.root / "destination space/same.txt").write_bytes(b"small\n")
        (self.root / "destination space/large.txt").write_bytes(b"x" * 70000)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith("TOKEN_SHUNT_") and k != "CDPATH"}

    def decision(self, command):
        result = subprocess.run([str(HOOK)], input=json.dumps({"tool_input": {
            "command": command}}), cwd=self.root, env=self.env, text=True,
            capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return (json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]
                if result.stdout else "pass")

    def test_same_name_uses_destination(self):
        self.assertEqual(self.decision("cd 'destination space' && cat same.txt"), "pass")

    def test_large_destination_file(self):
        self.assertEqual(self.decision("cd 'destination space' && cat large.txt"), "deny")

    def test_untracked_cd_cannot_use_original_directory(self):
        commands = (
            "cd 'destination space' && cat large.txt || true",
            "cd 'destination space' || exit; cat large.txt",
            "cd 'destination space' && cat large.txt & echo hi",
            "cd -- 'destination space' && /bin/cat large.txt || true",
            "echo ok; cd 'destination space'; cat large.txt",
            "cd 'destination space' && true || true; cat large.txt",
            "cd 'destination space' && cd . || true; cat large.txt",
        )
        # Both absent and small files in the original cwd used to mask the
        # large destination operand. Check actual Bash output as well.
        for original_exists in (False, True):
            if original_exists:
                (self.root / "large.txt").write_bytes(b"small\n")
            for command in commands:
                with self.subTest(original_exists=original_exists, command=command):
                    actual = subprocess.run(["bash", "-c", command], cwd=self.root,
                                            env=self.env, capture_output=True, timeout=10)
                    self.assertEqual(actual.returncode, 0, actual.stderr)
                    self.assertGreaterEqual(len(actual.stdout), 70000)
                    self.assertEqual(self.decision(command), "deny")

    def test_supported_leading_cd_chain(self):
        self.assertEqual(self.decision("cd 'destination space'; cd . && cat same.txt"), "pass")
        self.assertEqual(self.decision("cd 'destination space'; cd . && cat large.txt"), "deny")

    def test_no_cd_small_file_is_unchanged(self):
        (self.root / "small.txt").write_bytes(b"small\n")
        for command in ("cat small.txt", "cat small.txt || true",
                        "cat small.txt & echo hi", "echo ok; cat small.txt"):
            with self.subTest(command=command):
                self.assertEqual(self.decision(command), "pass")

    def test_destination_pipeline(self):
        self.assertEqual(self.decision("cd 'destination space' && cat large.txt | cat"), "deny")

    def test_failed_cd_keeps_current_directory(self):
        self.assertEqual(self.decision("cd nonexistent; cat same.txt"), "deny")

    def test_pipeline_cd_does_not_move_parent(self):
        self.assertEqual(self.decision("cd 'destination space' | cat; cat same.txt"), "deny")

    def test_cdpath_is_not_replaced_with_local_directory(self):
        (self.root / "alternate/destination space").mkdir(parents=True)
        (self.root / "alternate/destination space/same.txt").write_bytes(b"x" * 70000)
        self.env["CDPATH"] = str(self.root / "alternate")
        self.assertEqual(self.decision("cd 'destination space' && cat same.txt"), "deny")
        self.assertEqual(self.decision("cd './destination space' && cat same.txt"), "pass")


if __name__ == "__main__":
    unittest.main()
