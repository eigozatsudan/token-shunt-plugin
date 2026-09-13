"""Unread hook eval catalogs must not count as a successful eval."""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RUN_SH = Path(__file__).resolve().parents[1] / "run.sh"
JQ_NONEMPTY_ARRAY = "type == \"array\" and length > 0"
PASS_FAIL_OK = re.compile(r"pass:\s+\d+\s+fail:\s+0\b")


class HookEvalCatalogTests(unittest.TestCase):
    def test_jq_e_accepts_nonempty_array(self):
        result = subprocess.run(
            ["jq", "-e", JQ_NONEMPTY_ARRAY],
            input='[{"id":"tiny"}]\n',
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_catalogs_fail_run_sh(self):
        with tempfile.TemporaryDirectory() as tmp:
            evals = Path(tmp) / "evals"
            evals.mkdir()
            shutil.copy2(RUN_SH, evals / "run.sh")
            catalogs = ("hook-evals.json", "bash-hook-evals.json")
            for name in catalogs:
                for contents in ("not-json\n", "[]\n", "{}\n", None):
                    with self.subTest(catalog=name, contents=contents):
                        for other in catalogs:
                            (evals / other).write_text('[{"id":"unused"}]\n')
                        if contents is None:
                            (evals / name).unlink()
                        else:
                            (evals / name).write_text(contents)
                        result = subprocess.run(
                            ["bash", str(evals / "run.sh")], cwd=evals,
                            text=True, capture_output=True, timeout=120)
                        combined = result.stdout + "\n" + result.stderr
                        self.assertNotEqual(result.returncode, 0, combined)
                        self.assertIsNone(PASS_FAIL_OK.search(combined), combined)
                        self.assertIn(name, result.stderr)


if __name__ == "__main__":
    unittest.main()
