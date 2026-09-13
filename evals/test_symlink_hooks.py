"""Read/Bash must measure the file opened through a symbolic link."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


HOOKS = Path(__file__).resolve().parents[1] / "plugin" / "hooks"


class SymlinkHooksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="shunt-links-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # Short lines avoid relying on any downstream tool's long-line handling.
        (self.root / "large.txt").write_bytes((b"x" * 699 + b"\n") * 100)
        (self.root / "small.txt").write_bytes(b"small\n")
        (self.root / "large-link.txt").symlink_to("large.txt")
        (self.root / "small-link.txt").symlink_to("small.txt")
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith("TOKEN_SHUNT_")}

    def decision(self, hook, tool_input, agent=None):
        payload = {"tool_input": tool_input}
        if agent:
            payload["agent_type"] = agent
        result = subprocess.run([str(HOOKS / hook)], input=json.dumps(payload),
                                text=True, capture_output=True, env=self.env,
                                cwd=self.root, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return (json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]
                if result.stdout else "pass")

    def test_full_read_matches_target(self):
        for path, expected in [("large.txt", "deny"), ("large-link.txt", "deny"),
                               ("small.txt", "pass"), ("small-link.txt", "pass")]:
            with self.subTest(path=path):
                self.assertEqual(self.decision("check-file-size", {
                    "file_path": str(self.root / path)}), expected)

    def test_targeted_read_is_still_bounded(self):
        for limit, expected in [(1, "pass"), (100, "deny")]:
            with self.subTest(limit=limit):
                self.assertEqual(self.decision("check-file-size", {
                    "file_path": str(self.root / "large-link.txt"),
                    "offset": 1, "limit": limit}), expected)

    def test_cat_matches_target(self):
        for path, expected in [("large.txt", "deny"), ("large-link.txt", "deny"),
                               ("small-link.txt", "pass")]:
            with self.subTest(path=path):
                self.assertEqual(self.decision("check-bash-read", {
                    "command": "cat " + path}), expected)

    def test_byte_ranges_use_target_size(self):
        for command in ["head", "tail"]:
            for count, expected in [(65536, "pass"), (70000, "deny")]:
                with self.subTest(command=command, count=count):
                    self.assertEqual(self.decision("check-bash-read", {
                        "command": f"{command} -c {count} large-link.txt"}), expected)

    def test_worker_can_read_link(self):
        self.assertEqual(self.decision("check-file-size", {
            "file_path": str(self.root / "large-link.txt")},
            "token-shunt:bulk-reader"), "pass")


if __name__ == "__main__":
    unittest.main()
