"""The coverage instrument records; it never decides.

Spec: docs/superpowers/specs/2026-09-19-targeted-read-coverage-design.md

18 of 21 archived parent corpus Reads were targeted (offset+limit), which
Lock B never denies by design. This hook measures that route. It has no
deny path, no state file, and no threshold, and each test below names the
production change that would break it.
"""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

HOOKS = Path(__file__).resolve().parents[1] / 'plugin' / 'hooks'
SOURCE = HOOKS / 'record-coverage'
hook = importlib.util.module_from_spec(
    importlib.util.spec_from_loader(
        'record_coverage',
        importlib.machinery.SourceFileLoader('record_coverage', str(SOURCE))))
# Execute the source directly so loading this extensionless hook cannot
# leave bytecode inside the distributable plugin tree.
exec(compile(SOURCE.read_bytes(), str(SOURCE), 'exec'), hook.__dict__)


def event(path='/corpus/migration.py', start=139, lines=50, total=316,
          content='x' * 2814, offset=139, limit=50, agent_id=None,
          agent_type=None, is_error=False, **extra):
    response = {'type': 'text', 'file': {
        'filePath': path, 'content': content,
        'startLine': start, 'numLines': lines, 'totalLines': total}}
    if is_error:
        response['is_error'] = True
    body = {'hook_event_name': 'PostToolUse', 'tool_name': 'Read',
            'session_id': 's1', 'agent_id': agent_id, 'agent_type': agent_type,
            'tool_input': {'file_path': path},
            'tool_response': response}
    if offset is not None:
        body['tool_input']['offset'] = offset
    if limit is not None:
        body['tool_input']['limit'] = limit
    body.update(extra)
    return body


class RecordTests(unittest.TestCase):
    def test_the_line_range_comes_from_the_tool_response(self):
        # Fails if the hook ever counts lines itself instead of reading
        # startLine/numLines/totalLines back.
        got = hook.record(event())
        self.assertEqual(('record-coverage', 's1', None, None,
                          '/corpus/migration.py'),
                         (got['hook'], got['session_id'], got['agent_id'],
                          got['agent_type'], got['file_path']))
        self.assertEqual((139, 50, 316), (got['start'], got['lines'], got['total']))
        self.assertEqual((139, 50), (got['offset'], got['limit']))
        self.assertEqual(2814, got['bytes'])
        self.assertIs(False, got['is_error'])

    def test_a_worker_read_carries_both_of_the_fields_that_identify_it(self):
        # intake_ledger.py:134 judges a parent by `not (agent_id or
        # agent_type)`. Recording only agent_id files a worker Read whose
        # event carries agent_type alone as if the parent had made it, and
        # worker reads are full-file by design -- they would drag every
        # rate up.
        self.assertEqual(('a7', None),
                         (hook.record(event(agent_id='a7'))['agent_id'],
                          hook.record(event(agent_id='a7'))['agent_type']))
        typed = hook.record(event(agent_type='token-shunt:bulk-reader'))
        self.assertEqual('token-shunt:bulk-reader', typed['agent_type'])

    def test_a_failed_read_keeps_the_row_but_claims_no_lines(self):
        # Fails if the hook drops error rows: the count of attempts would
        # silently fall, which is how a corrected count of 21 in 10 of 14
        # once got published as 26 in 12 of 14.
        got = hook.record(event(is_error=True))
        self.assertEqual((None, None, None, 0),
                         (got['start'], got['lines'], got['total'], got['bytes']))
        self.assertIs(True, got['is_error'])
        self.assertEqual('/corpus/migration.py', got['file_path'])

    def test_a_full_read_records_no_offset_and_no_limit(self):
        # The hook must not decide what counts as "targeted"; it reports the
        # raw input and lets the aggregator define it.
        got = hook.record(event(offset=None, limit=None, start=1, lines=316))
        self.assertEqual((None, None), (got['offset'], got['limit']))
        self.assertEqual((1, 316, 316), (got['start'], got['lines'], got['total']))

    def test_a_non_read_event_records_nothing(self):
        self.assertIsNone(hook.record(dict(event(), tool_name='Bash')))

    def test_a_malformed_response_records_a_row_without_line_numbers(self):
        # Fails if the hook raises on junk: a telemetry crash must not reach
        # the tool call.
        for junk in ('', [], {'file': 'not-an-object'}, {'file': {'startLine': 'x'}}):
            with self.subTest(junk=junk):
                got = hook.record(dict(event(), tool_response=junk))
                self.assertEqual('/corpus/migration.py', got['file_path'])
                self.assertIsNone(got['start'])

    def test_an_event_without_a_path_records_nothing(self):
        self.assertIsNone(hook.record(dict(event(), tool_input={})))
        self.assertIsNone(hook.record(dict(event(), tool_input='junk')))
