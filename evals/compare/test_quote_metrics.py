"""Regression controls for parent context accounting and exact body quotations."""
import contextlib
import io
import json
from pathlib import Path
import random
import tempfile
import unittest

import judge


def assistant(mid, blocks, parent=None):
    return {'type': 'assistant', 'parent_tool_use_id': parent,
            'message': {'id': mid, 'content': blocks}}


def use(name, value):
    return {'type': 'tool_use', 'id': name, 'name': name, 'input': value}


class ParentContextTests(unittest.TestCase):
    def test_tool_payloads_count_once_with_real_unicode_and_newlines(self):
        for name, field in [('Agent', 'prompt'), ('Write', 'content'), ('Bash', 'command')]:
            with self.subTest(name=name):
                payload = '秘密の本文\n' * 5000
                event = assistant('m', [use(name, {field: payload})])
                child = assistant('child', [use('Write', {'content': 'CHILD_ONLY'})], 'Agent')
                tr = judge.Transcript([event, event, child])
                expected = '{' + json.dumps(field) + ':' + payload + '}'
                self.assertEqual(tr.parent_added_text(), expected)
                self.assertEqual(tr.metrics()['parent_added_utf8_bytes'], len(expected.encode()))
                self.assertEqual(tr.metrics()['parent_added_chars'], len(expected))
                self.assertNotIn('CHILD_ONLY', tr.parent_added_text())
                self.assertEqual(tr.final_text(), '')

    def test_final_text_remains_natural_language_and_nested_input_is_stable(self):
        blocks = [{'type': 'text', 'text': 'done'},
                  use('Agent', {'z': ['raw\n漢', {'b': True}], 'a': 12})]
        tr = judge.Transcript([assistant('m', blocks)])
        self.assertEqual(tr.final_text(), 'done')
        self.assertEqual(tr.parent_added_text(), 'done\n{"a":12,"z":[raw\n漢,{"b":true}]}')

    def test_idless_messages_remain_distinct_and_user_dedup_is_preserved(self):
        event = assistant(None, [use('Agent', {'prompt': 'x'})])
        user = {'type': 'user', 'message': {'id': 'u', 'content': [
            {'type': 'tool_result', 'tool_use_id': 'Agent', 'content': 'result'}]}}
        tr = judge.Transcript([event, event, user, user])
        self.assertEqual(tr.parent_added_text(), '{"prompt":x}\n{"prompt":x}\nresult')


class ExactQuoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def assert_both(self, body, reply, expected, tool_input=False):
        with self.subTest(bytes=len(reply.encode()), expected=expected):
            self.assertEqual(judge.quote_leak(reply, ['f'], {'f': body})[0], expected)
            target = self.root / 'target.txt'
            target.write_text(body)
            blocks = [use('Agent', {'prompt': reply})] if tool_input else [
                {'type': 'text', 'text': reply}]
            event = assistant('m', blocks)
            transcript = self.root / 'transcript.jsonl'
            transcript.write_text(json.dumps(event) + '\n' + json.dumps(event) + '\n')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(judge.leakcheck(str(transcript), str(target)), 0 if expected else 1)

    def test_utf8_and_strict_byte_boundary(self):
        for reply, expected in [('x' * 2048, False), ('x' * 2049, True),
                                ('漢' * 682 + 'ab', False),
                                ('漢' * 683, True), ('漢' * 1000, True)]:
            self.assert_both(reply, reply, expected)

    def test_every_offset_and_end_window(self):
        rng = random.Random(27)
        body = ''.join(rng.choice('abcdefghijklmnopqrstuvwxyz0123456789') for _ in range(5000))
        for start in (1, 17, 511, 513, 2951):
            self.assert_both(body, body[start:start + 2049], True)
        self.assert_both(body, body[1:2049], False)
        self.assert_both(body, body[1:1025] + '!' + body[1025:2050], False)

    def test_dense_discrete_and_real_lines(self):
        self.assert_both('a\n' * 100, 'a', False)
        self.assert_both('a\n' * 100, 'a\n' * 20, False)
        self.assert_both('a\n' * 100, 'a\n' * 21, True)
        body = ''.join('line%d\n' % i for i in range(30))
        self.assert_both(body, ' ... '.join(body.splitlines()), False)
        self.assert_both(body, '\n'.join(body.splitlines()[3:24]), True)
        self.assert_both(body, '\r\n'.join(body.splitlines()[3:24]), True)
        self.assert_both('a\n' * 10 + '\n' + 'a\n' * 11, 'a\n' * 21, False)

    def test_tool_prompt_preserves_line_and_byte_leaks(self):
        self.assert_both('漢' * 1000, '漢' * 1000, True, tool_input=True)
        body = ''.join('row%d\n' % i for i in range(21))
        self.assert_both(body, body, True, tool_input=True)
        self.assert_both('a\n' * 21, 'a', False, tool_input=True)

    def test_large_dense_fixture_short_reply(self):
        self.assert_both('a\n' * 200000, 'a', False)
        self.assert_both('a' * 1000000, 'b' * 2049, False)
        self.assert_both('a' * 1000000 + '漢' * 683, '漢' * 683, True)

    def test_rolling_matcher_against_exhaustive_small_oracle(self):
        rng = random.Random(902)
        for _ in range(100):
            left = ''.join(rng.choice('ab漢') for _ in range(30))
            right = ''.join(rng.choice('ab漢') for _ in range(25))
            a, b = left.encode(), right.encode()
            expected = any(a[i:i + 9] in b for i in range(len(a) - 8))
            self.assertEqual(judge.contiguous_bytes(left, right, 9), expected)


if __name__ == '__main__':
    unittest.main()
