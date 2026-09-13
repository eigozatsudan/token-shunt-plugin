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
