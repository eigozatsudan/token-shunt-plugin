"""Regression controls for parent context accounting and exact body quotations."""
import contextlib
import copy
import io
import json
from pathlib import Path
import random
import tempfile
import unittest
import uuid

import judge


def assistant(mid, blocks, parent=None):
    event = {'type': 'assistant', 'parent_tool_use_id': parent,
             'message': {'id': mid, 'content': blocks}}
    if mid:
        event['uuid'] = str(uuid.uuid4())
    return event


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

    def test_same_id_later_different_context_text_is_joined(self):
        thinking = assistant('m', [{'type': 'thinking', 'thinking': 'plan'}])
        for name, field in [('Agent', 'prompt'), ('Write', 'content'), ('Bash', 'command')]:
            with self.subTest(name=name):
                payload = '秘密の本文\n' * 20
                tool_event = assistant('m', [use(name, {field: payload})])
                tr = judge.Transcript([thinking, tool_event])
                expected = 'plan\n{' + json.dumps(field) + ':' + payload + '}'
                self.assertEqual(tr.parent_added_text(), expected)
                self.assertEqual(tr.metrics()['parent_added_utf8_bytes'], len(expected.encode()))
        first = assistant('n', [{'type': 'text', 'text': 'hello'}])
        second = assistant('n', [use('Write', {'content': 'body'})])
        self.assertEqual(judge.Transcript([first, second]).parent_added_text(),
                         'hello\n{"content":body}')
        duplicate = assistant('n', [use('Write', {'content': 'body'})])
        self.assertEqual(judge.Transcript([first, second, duplicate]).parent_added_text(),
                         'hello\n{"content":body}')

    def test_identical_inputs_on_distinct_tool_calls_are_both_counted(self):
        blocks = [dict(use('Agent', {'prompt': 'same task'}), id=uid)
                  for uid in ('a1', 'a2')]
        events = [assistant('m', [block]) for block in blocks]
        expected = '{"prompt":same task}\n{"prompt":same task}'
        # Retransmission and a later combined representation must not add copies.
        events += [copy.deepcopy(events[0]), assistant('m', blocks)]
        self.assertEqual(judge.Transcript(events).parent_added_text(), expected)

    def test_equal_text_in_distinct_events_is_not_a_retransmission(self):
        events = [assistant('m', [{'type': 'text', 'text': 'same'}]) for _ in range(2)]
        events.append(copy.deepcopy(events[0]))
        self.assertEqual(judge.Transcript(events).parent_added_text(), 'same\nsame')

    def test_unidentified_text_events_are_kept_conservatively(self):
        event = assistant('m', [{'type': 'text', 'text': 'same'}])
        del event['uuid']
        self.assertEqual(judge.Transcript([event, copy.deepcopy(event)]).parent_added_text(),
                         'same\nsame')


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

    def test_same_id_later_write_content_is_detected_by_leakcheck(self):
        thinking = assistant('m', [{'type': 'thinking', 'thinking': 'plan'}])
        for body in (''.join('line%d\n' % i for i in range(21)), 'x' * 2049):
            with self.subTest(bytes=len(body.encode()), lines=body.count('\n') + 1):
                target = self.root / 'target.txt'
                target.write_text(body)
                write = assistant('m', [use('Write', {'content': body})])
                transcript = self.root / 'transcript.jsonl'
                transcript.write_text(json.dumps(thinking) + '\n' + json.dumps(write) + '\n')
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(judge.leakcheck(str(transcript), str(target)), 0)

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


class ParentUsageSumTests(unittest.TestCase):
    def result(self, inp, cache_read, cache_creation, output, model_usage, parent=None):
        event = {'type': 'result', 'result': 'ok',
                 'usage': {'input_tokens': inp,
                           'cache_read_input_tokens': cache_read,
                           'cache_creation_input_tokens': cache_creation,
                           'output_tokens': output},
                 'modelUsage': model_usage}
        if parent is not None:
            event['parent_tool_use_id'] = parent
        return event

    def test_multiple_parent_results_sum_per_turn_usage(self):
        last_tree = {'claude-sonnet-5': {'inputTokens': 99}}
        events = [
            self.result(8, 114810, 10275, 1355, {'first': {'inputTokens': 1}}),
            self.result(999999, 999999, 999999, 999999,
                        {'child': {'inputTokens': 10 ** 9}}, parent='worker'),
            self.result(4, 68994, 2480, 1113, {'second': {'inputTokens': 2}}),
            self.result(2, 36492, 947, 97, last_tree),
        ]
        metrics = judge.Transcript(events).metrics()
        self.assertEqual(metrics['parent_input_tokens'], {
            'uncached': 14, 'cache_read': 220296, 'cache_creation': 13702})
        self.assertEqual(
            metrics['parent_input_tokens']['uncached']
            + metrics['parent_input_tokens']['cache_read']
            + metrics['parent_input_tokens']['cache_creation'], 234012)
        self.assertEqual(metrics['parent_output_tokens'], 2565)
        self.assertEqual(metrics['usage_parent']['input_tokens'], 14)
        self.assertEqual(metrics['usage_parent']['cache_read_input_tokens'], 220296)
        self.assertEqual(metrics['usage_parent']['cache_creation_input_tokens'], 13702)
        self.assertEqual(metrics['usage_parent']['output_tokens'], 2565)
        self.assertEqual(metrics['usage_tree'], last_tree)

    def evaluate(self, results):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'usage.jsonl'
            events = [{'type': 'system', 'subtype': 'init', 'plugins': []}] + results
            path.write_text('\n'.join(json.dumps(e) for e in events))
            spec = {'id': 'usage-required', 'require_parent_tokens': ['direct'],
                    'expect': {'direct': {'plugin': False}}}
            return judge.judge(str(path), spec, {'mode': 'direct'})

    def test_missing_usage_is_not_measured_zero_with_multiple_results(self):
        for count in (1, 2):
            with self.subTest(results=count):
                verdict, ok = self.evaluate([{'type': 'result', 'result': 'ok'}] * count)
                self.assertFalse(ok)
                self.assertIsNone(verdict['metrics']['parent_input_tokens'])
                self.assertIsNone(verdict['metrics']['parent_output_tokens'])
                self.assertFalse(verdict['checks']['parent_tokens'])

    def test_each_turn_needs_valid_values_for_every_token_category(self):
        for key in ('input_tokens', 'output_tokens', 'cache_read_input_tokens',
                    'cache_creation_input_tokens'):
            for value in (None, True, -1, '1', 1.5):
                for count in (1, 2):
                    with self.subTest(key=key, value=value, results=count):
                        results = [self.result(1, 2, 3, 4, {}) for _ in range(count)]
                        if value is None:
                            del results[0]['usage'][key]
                        else:
                            results[0]['usage'][key] = value
                        verdict, ok = self.evaluate(results)
                        self.assertFalse(ok)
                        self.assertFalse(verdict['checks']['parent_tokens'])
                        self.assertIsNone(verdict['metrics']['usage_parent'].get(key))

    def test_measured_zeros_are_valid(self):
        verdict, ok = self.evaluate([self.result(0, 0, 0, 0, {}) for _ in range(2)])
        self.assertTrue(ok, verdict['reasons'])
        self.assertEqual(verdict['metrics']['parent_output_tokens'], 0)

    def test_result_retransmission_and_child_results_do_not_change_totals(self):
        first = dict(self.result(1, 2, 3, 4, {'parent': {}}), uuid='r1')
        last = dict(self.result(5, 6, 7, 8, {'parent': {'inputTokens': 6}}), uuid='r2')
        child = self.result(100, 100, 100, 100, {'child': {}}, parent='worker')
        metrics = judge.Transcript([first, copy.deepcopy(first), last, child]).metrics()
        self.assertEqual(metrics['parent_input_tokens'],
                         {'uncached': 6, 'cache_read': 8, 'cache_creation': 10})
        self.assertEqual(metrics['parent_output_tokens'], 12)
        self.assertEqual(metrics['usage_tree'], last['modelUsage'])


class ChildNoBodyUnverifiedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def evaluate(self, fixture_path, child_text, **metadata):
        paths = fixture_path if isinstance(fixture_path, list) else [fixture_path]
        events = [
            {'type': 'system', 'subtype': 'init',
             'plugins': [{'name': 'token-shunt'}]},
            assistant('ma', [use('Agent', {
                'subagent_type': 'token-shunt:bulk-reader', 'model': 'haiku', 'prompt': ' '.join(paths)})]),
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'Agent', 'resolvedModel': 'claude-haiku', 'content': child_text}]}},
            {'type': 'result', 'result': 'ok', 'usage': {
                'input_tokens': 10, 'cache_read_input_tokens': 0,
                'cache_creation_input_tokens': 0, 'output_tokens': 5}},
        ]
        transcript = self.root / 'transcript.jsonl'
        transcript.write_text('\n'.join(json.dumps(e) for e in events) + '\n')
        spec = {'id': 'child-no-body-unverified',
                'fixtures': paths,
                'fixtures_abs': paths,
                'expect': {'delegate': {
                    'agent_type': 'token-shunt:bulk-reader',
                    'child_no_body': True, 'child_msg_max': 4000}}}
        spec.update(metadata)
        return judge.judge(str(transcript), spec, {'mode': 'delegate'})

    def test_missing_fixture_one_line_quote_fails_child_no_body(self):
        missing = str(self.root / 'does-not-exist-oneline.json')
        verdict, ok = self.evaluate(missing, 'Y' * 3000)
        self.assertFalse(ok)
        self.assertEqual(verdict['verdict'], 'fail')
        self.assertFalse(verdict['checks']['child_no_body'])

    def test_readable_oneline_fixture_quote_still_fails_via_2kib(self):
        target = self.root / 'oneline.txt'
        body = 'Y' * 3000
        target.write_text(body)
        verdict, ok = self.evaluate(str(target), body)
        self.assertFalse(ok)
        self.assertFalse(verdict['checks']['child_no_body'])
        self.assertTrue(any('2KiB' in reason for reason in verdict['reasons']))

    def test_missing_fixture_short_summary_is_unverified_not_pass(self):
        missing = str(self.root / 'does-not-exist-summary.json')
        verdict, ok = self.evaluate(missing, 'ok')
        self.assertFalse(ok)
        self.assertEqual(verdict['verdict'], 'fail')
        self.assertFalse(verdict['checks']['child_no_body'])

    def test_one_readable_fixture_does_not_excuse_another_missing_body(self):
        readable = self.root / 'a.txt'
        readable.write_text('unrelated short body')
        missing = self.root / 'b.txt'
        for text in ('ok', 'Y' * 3000):
            with self.subTest(length=len(text)):
                verdict, ok = self.evaluate([str(readable), str(missing)], text)
                self.assertFalse(ok)
                self.assertFalse(verdict['checks']['child_no_body'])
                self.assertTrue(any(str(missing) in r for r in verdict['reasons']))

    def test_relative_absolute_aliases_and_empty_files_are_readable(self):
        target = self.root / 'gen' / 'ref.txt'
        target.parent.mkdir()
        target.write_text('')
        for rel in ('gen/ref.txt', './gen/ref.txt', 'fixtures/gen/ref.txt'):
            for rooted in (False, True):
                with self.subTest(rel=rel, rooted=rooted):
                    metadata = {'fixtures_abs': [str(target)]}
                    if rooted:
                        metadata['fixture_root'] = str(self.root)
                    verdict, ok = self.evaluate(rel, 'status: partial\nstop_reason: empty file', **metadata)
                    self.assertTrue(ok, verdict['reasons'])

    def test_missing_path_cannot_alias_a_different_file_with_same_basename(self):
        existing = self.root / 'other' / 'ref.txt'
        existing.parent.mkdir()
        existing.write_text('unrelated short body')
        for missing in (str(self.root / 'gen' / 'ref.txt'), 'gen/ref.txt'):
            with self.subTest(missing=missing):
                verdict, ok = self.evaluate(missing, 'Y' * 3000,
                                            fixtures_abs=[str(existing)])
                self.assertFalse(ok)
                self.assertFalse(verdict['checks']['child_no_body'])

    def test_ambiguous_relative_alias_cannot_confirm_body_absence(self):
        paths = [self.root / name / 'ref.txt' for name in ('first', 'second')]
        for path in paths:
            path.parent.mkdir()
            path.write_text('unrelated body')
        verdict, ok = self.evaluate('ref.txt', 'ok', fixtures_abs=list(map(str, paths)))
        self.assertFalse(ok)
        self.assertFalse(verdict['checks']['child_no_body'])


if __name__ == '__main__':
    unittest.main()
