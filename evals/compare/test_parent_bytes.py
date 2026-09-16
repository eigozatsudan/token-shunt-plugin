"""How much file body reached the parent's own context.

`parent_added_utf8_bytes` counts the text the parent wrote and received, not
the file content it ingested; picking it as the primary metric cost a
measurement (reviews/redmine-effect-aborted-2026-09-17.md section 3). This
instrument counts one thing only: the bytes a Read returned to the parent
itself.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
import parent_bytes  # noqa: E402


def rows(*items):
    return "\n".join(json.dumps(i) for i in items) + "\n"


def use(uid, path, parent=None, name="Read"):
    return {"type": "assistant", "parent_tool_use_id": parent,
            "message": {"content": [
                {"type": "tool_use", "id": uid, "name": name,
                 "input": {"file_path": path}}]}}


def result(uid, text, parent=None):
    return {"type": "user", "parent_tool_use_id": parent,
            "message": {"content": [
                {"type": "tool_result", "tool_use_id": uid, "content": text}]}}


class ParentBytesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "t.jsonl"

    def write(self, text):
        self.path.write_text(text)
        return str(self.path)

    def test_a_parent_read_counts_the_bytes_it_returned(self):
        body = "x" * 100
        f = self.write(rows(use("a", "/fix/one.rb"), result("a", body)))
        self.assertEqual(100, parent_bytes.parent_read_bytes(f))

    def test_a_subagent_read_does_not_count(self):
        # The whole point of delegating is that this body is not in the parent.
        f = self.write(rows(use("a", "/fix/one.rb", parent="t1"),
                            result("a", "y" * 500, parent="t1")))
        self.assertEqual(0, parent_bytes.parent_read_bytes(f))

    def test_reads_add_up(self):
        f = self.write(rows(use("a", "/fix/one.rb"), result("a", "x" * 10),
                            use("b", "/fix/two.rb"), result("b", "x" * 5)))
        self.assertEqual(15, parent_bytes.parent_read_bytes(f))

    def test_a_tool_that_is_not_read_does_not_count(self):
        f = self.write(rows(use("a", "/fix/one.rb", name="Grep"),
                            result("a", "x" * 40)))
        self.assertEqual(0, parent_bytes.parent_read_bytes(f))

    def test_a_read_with_no_result_counts_nothing(self):
        f = self.write(rows(use("a", "/fix/one.rb")))
        self.assertEqual(0, parent_bytes.parent_read_bytes(f))

    def test_only_paths_under_a_root_are_counted_when_one_is_given(self):
        # A run reads the plugin's own contract file too; that is not corpus.
        f = self.write(rows(use("a", "/fix/one.rb"), result("a", "x" * 10),
                            use("b", "/plugin/hooks/contract"), result("b", "x" * 999)))
        self.assertEqual(10, parent_bytes.parent_read_bytes(f, root="/fix"))
        self.assertEqual(1009, parent_bytes.parent_read_bytes(f))

    def test_utf8_bytes_not_characters(self):
        f = self.write(rows(use("a", "/fix/one.rb"), result("a", "あ" * 10)))
        self.assertEqual(30, parent_bytes.parent_read_bytes(f))

    def test_a_structured_result_is_measured_too(self):
        # Some results arrive as content blocks rather than a bare string.
        f = self.write(rows(use("a", "/fix/one.rb"),
                            result("a", [{"type": "text", "text": "x" * 20}])))
        self.assertEqual(20, parent_bytes.parent_read_bytes(f))

    def test_a_broken_line_does_not_stop_the_count(self):
        f = self.write("not json\n" + rows(use("a", "/fix/one.rb"),
                                           result("a", "x" * 7)))
        self.assertEqual(7, parent_bytes.parent_read_bytes(f))

    def test_the_cli_prints_one_number_per_transcript(self):
        f = self.write(rows(use("a", "/fix/one.rb"), result("a", "x" * 12)))
        out = subprocess.run([sys.executable, str(Path(parent_bytes.__file__)), f],
                             capture_output=True, text=True)
        self.assertEqual(0, out.returncode, out.stderr)
        self.assertIn("12", out.stdout)


if __name__ == "__main__":
    unittest.main()
