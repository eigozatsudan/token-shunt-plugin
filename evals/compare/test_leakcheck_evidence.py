"""An unreadable generated body is unverified, never evidence of absence."""
import builtins
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import judge


class LeakcheckEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.transcript = self.root / 'transcript.jsonl'
        self.target = self.root / 'generated.py'
        self.body = 'x' * 3000
        self.target.write_text(self.body)

    def check(self, text):
        self.transcript.write_text(json.dumps({'type': 'assistant', 'message': {
            'content': [{'type': 'text', 'text': text}]}}) + '\n')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return judge.leakcheck(str(self.transcript), str(self.target))

    def test_clean_and_leaked_body_have_distinct_exit_codes(self):
        self.assertEqual(self.check('Created the requested file.'), 1)
        self.assertEqual(self.check(self.body), 0)

    def test_unreadable_regular_file_is_not_clean(self):
        # Deterministic even under root: reproduce PermissionError at the body
        # open while retaining a real regular target and readable transcript.
        real_open = builtins.open

        def open_body(path, *args, **kwargs):
            if str(path) == str(self.target):
                raise PermissionError('generated body cannot be read')
            return real_open(path, *args, **kwargs)

        self.assertTrue(self.target.is_file())
        with mock.patch.object(judge, 'open', side_effect=open_body, create=True):
            self.assertEqual(self.check('Created the requested file.'), 2)

    def test_missing_body_is_unverified(self):
        self.target.unlink()
        self.assertEqual(self.check('Created the requested file.'), 2)


if __name__ == '__main__':
    unittest.main()
