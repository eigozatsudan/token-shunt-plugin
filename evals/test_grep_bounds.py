#!/usr/bin/env python3
"""The Grep bound: what it refuses, what it must never refuse."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / 'plugin/hooks'
sys.path.insert(0, str(HOOKS))
import grep_bounds as gb                                  # noqa: E402

BIG = gb.BUDGET + 1


def grep_event(path, session='s', **inp):
    body = {'output_mode': 'content', 'path': path}
    body.update(inp)
    return {'hook_event_name': 'PreToolUse', 'tool_name': 'Grep',
            'session_id': session, 'tool_input': body}


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.big = os.path.join(self.dir, 'big.txt')
        with open(self.big, 'w') as fh:
            fh.write('x' * BIG)
        self.small = os.path.join(self.dir, 'small.txt')
        with open(self.small, 'w') as fh:
            fh.write('x' * 10)

    def decide(self, event, state=None):
        return gb.decide(event, state if state is not None else gb.new_state())

    def test_an_unmeasured_over_budget_file_is_refused(self):
        reason = self.decide(grep_event(self.big, head_limit=5))
        self.assertIn('size has not been checked', reason)

    def test_a_file_within_budget_is_never_judged(self):
        # The small-task edit path keeps its own basis; bounding it here
        # would refuse ordinary work the contract allows.
        self.assertIsNone(self.decide(grep_event(self.small)))

    def test_files_with_matches_is_the_bound_and_needs_no_measurement(self):
        self.assertIsNone(self.decide(
            grep_event(self.big, output_mode='files_with_matches')))

    def test_a_directory_a_bare_search_and_a_glob_are_out_of_scope(self):
        for inp in ({'path': self.dir}, {'path': None},
                    {'path': self.big, 'glob': '*.txt'}):
            with self.subTest(inp=inp):
                event = grep_event(inp.get('path'))
                if 'glob' in inp:
                    event['tool_input']['glob'] = inp['glob']
                self.assertIsNone(self.decide(event))

    def test_a_missing_file_is_left_to_grep_itself(self):
        self.assertIsNone(self.decide(grep_event(self.big + '.gone')))


class MeasuredStateTests(TargetTests):
    def measured_state(self):
        state = gb.new_state()
        self.assertTrue(gb.record(state, self.big, 'test'))
        return state

    def test_a_measured_file_may_be_searched_within_the_bound(self):
        self.assertIsNone(self.decide(grep_event(self.big, head_limit=5),
                                      self.measured_state()))

    def test_the_bound_still_applies_after_measuring(self):
        state = self.measured_state()
        self.assertIn('no bound', self.decide(grep_event(self.big), state))
        for limit in (0, -1, 21, True, 'five'):
            with self.subTest(limit=limit):
                self.assertIn('not a bound', self.decide(
                    grep_event(self.big, head_limit=limit), state))
        self.assertIn('context window', self.decide(
            grep_event(self.big, head_limit=5, **{'-C': 3}), state))

    def test_a_changed_file_is_no_longer_measured(self):
        state = self.measured_state()
        with open(self.big, 'a') as fh:
            fh.write('more')
        self.assertIn('size has not been checked',
                      self.decide(grep_event(self.big, head_limit=5), state))

    def test_lost_state_reads_as_unmeasured(self):
        # A compact or a fresh session drops the record. Refusing costs one
        # round trip; passing would let the rule lapse silently.
        self.assertIn('size has not been checked',
                      self.decide(grep_event(self.big, head_limit=5)))

    def test_refusals_stop_at_the_cap(self):
        state = gb.new_state()
        state['denials'] = gb.DENY_CAP
        reason = self.decide(grep_event(self.big), state)
        self.assertIn('report partial', reason)


class MetadataCommandTests(unittest.TestCase):
    def test_a_bare_stat_or_wc_c_names_its_operands(self):
        for command, want in (
                ('wc -c /srv/a.py', ['/srv/a.py']),
                ('wc --bytes /srv/a.py', ['/srv/a.py']),
                ('stat -c %s -- /srv/a.py', ['/srv/a.py']),
                ('stat --format=%s /srv/a.py', ['/srv/a.py']),
                ('/usr/bin/stat /a /b', ['/a', '/b'])):
            with self.subTest(command=command):
                self.assertEqual(gb.metadata_paths(command), want)

    def test_anything_a_shell_could_expand_records_nothing(self):
        for command in ('wc -c $F', 'wc -c a.py; rm -rf /', 'wc -c `echo a`',
                        'wc -c a.py && cat b', 'wc -c *.py', 'cat /srv/a.py',
                        'wc -l /srv/a.py', '', None):
            with self.subTest(command=command):
                self.assertEqual(gb.metadata_paths(command), [])


class HookProcessTests(unittest.TestCase):
    """The executable, including the mode it reads off the event."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.big = os.path.join(self.dir, 'big.txt')
        with open(self.big, 'w') as fh:
            fh.write('x' * BIG)
        self.session = 'test-%d' % os.getpid()
        self.addCleanup(self.drop_state)

    def drop_state(self):
        key = hashlib.sha256((self.session + '\0parent').encode()).hexdigest()
        path = (Path(tempfile.gettempdir())
                / ('token-shunt-reader-%s' % os.getuid())
                / ('grep-%s.json' % key))
        if path.exists():
            path.unlink()

    def run_hook(self, event, *args):
        proc = subprocess.run([str(HOOKS / 'check-grep-bounds')] + list(args),
                              input=json.dumps(event), capture_output=True,
                              text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_a_post_tool_use_bash_records_and_then_the_grep_passes(self):
        denied = self.run_hook(grep_event(self.big, self.session, head_limit=5))
        self.assertIn('deny', denied)
        self.run_hook({'hook_event_name': 'PostToolUse', 'tool_name': 'Bash',
                       'session_id': self.session,
                       'tool_input': {'command': 'wc -c %s' % self.big}})
        self.assertEqual(
            self.run_hook(grep_event(self.big, self.session, head_limit=5)), '')

    def test_a_read_deny_that_named_the_size_counts_as_measured(self):
        self.run_hook({'hook_event_name': 'PreToolUse', 'tool_name': 'Read',
                       'session_id': self.session, 'tool_input': {}},
                      '--sized', self.big)
        self.assertEqual(
            self.run_hook(grep_event(self.big, self.session, head_limit=5)), '')

    def test_an_unusable_event_fails_the_call_rather_than_allowing_it(self):
        proc = subprocess.run([str(HOOKS / 'check-grep-bounds')],
                              input='not json', capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)


if __name__ == '__main__':
    unittest.main()
