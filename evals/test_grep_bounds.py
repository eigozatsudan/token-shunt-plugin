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

    def refuse(self, state, path, times):
        """Record refusals the way the executable does, per path."""
        for _ in range(times):
            gb.note_denial(grep_event(path), state)

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

    def test_a_directory_and_a_bare_search_are_out_of_scope(self):
        # Neither resolves to one size, and enumerating them in front of
        # the call would cost more than the rule is worth. A glob is a
        # different matter once `path` names one file: see below.
        for inp in ({'path': self.dir}, {'path': None},
                    {'path': self.dir, 'glob': '*.txt'}):
            with self.subTest(inp=inp):
                event = grep_event(inp.get('path'))
                if 'glob' in inp:
                    event['tool_input']['glob'] = inp['glob']
                self.assertIsNone(self.decide(event))

    def test_a_glob_beside_one_named_file_does_not_lift_the_rule(self):
        """`path` names one file, so the size is not in doubt.

        The glob exemption is for a set of files with no single size.
        Read as "any glob at all", it made the escape from this rule one
        extra key on the call the hook had just refused.
        """
        for glob in ('*', 'big.txt', '**/*.py'):
            with self.subTest(glob=glob):
                self.assertIn('size has not been checked', self.decide(
                    grep_event(self.big, head_limit=5, glob=glob)))

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
        # Every spelling of the window, including the one the Grep schema
        # uses for rg's -C, which named none of the banned flags.
        for key in ('-A', '-B', '-C', 'context'):
            with self.subTest(key=key):
                self.assertIn('context window', self.decide(
                    grep_event(self.big, head_limit=5, **{key: 3}), state))

    def test_a_context_window_that_is_not_a_number_is_still_a_window(self):
        """head_limit fails closed on a bad type; the window must too.

        Counting only ints read `-C: "50"` as no window at all, which is
        the one reading that lets the output go unbounded.
        """
        state = self.measured_state()
        for value in ('50', 50.0, True, [5], {'n': 5}):
            with self.subTest(value=value):
                self.assertIn('context window', self.decide(
                    grep_event(self.big, head_limit=5, **{'-C': value}),
                    state))

    def test_an_absent_or_zero_window_is_not_a_window(self):
        state = self.measured_state()
        for value in (None, 0):
            with self.subTest(value=value):
                self.assertIsNone(self.decide(
                    grep_event(self.big, head_limit=5, **{'-C': value}),
                    state))

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
        self.refuse(state, self.big, gb.DENY_CAP)
        reason = self.decide(grep_event(self.big), state)
        self.assertIn('report partial', reason)

    def test_the_cap_counts_the_path_it_names(self):
        # The message names one path. Counting every path in the scope
        # together tells a file refused once that it was refused six times
        # (reviews/deny-cap-evidence-2026-09-16.md section 4).
        state = gb.new_state()
        other = os.path.join(self.dir, 'other.txt')
        with open(other, 'w') as fh:
            fh.write('x' * (gb.BUDGET + 1))
        self.refuse(state, other, gb.DENY_CAP)
        reason = self.decide(grep_event(self.big), state)
        self.assertIsNotNone(reason)
        self.assertNotIn('refused', reason)
        self.assertIn('refused %d times' % gb.DENY_CAP,
                      self.decide(grep_event(other), state))

    def test_the_cap_does_not_refuse_a_search_that_now_conforms(self):
        # The cap exists to stop hammering. A measured, bounded search is
        # not hammering, and refusing it leaves delegating or giving up as
        # the only way out (reviews/deny-cap-evidence-2026-09-16.md
        # section 4, item 2).
        state = self.measured_state()
        self.refuse(state, self.big, gb.DENY_CAP)
        self.assertIsNone(self.decide(grep_event(self.big, head_limit=5), state))

    def test_the_cap_still_answers_a_search_that_does_not_conform(self):
        state = self.measured_state()
        self.refuse(state, self.big, gb.DENY_CAP)
        for bad in ({}, {'head_limit': 999}, {'head_limit': 5, '-C': 3}):
            with self.subTest(bad=bad):
                reason = self.decide(grep_event(self.big, **bad), state)
                self.assertIn('refused %d times' % gb.DENY_CAP, reason)

    def test_a_scope_wide_count_from_an_older_session_is_not_carried(self):
        # State written before the counter was per path holds an int. It
        # cannot say which path earned it, so it starts the run over rather
        # than capping a path that was never refused.
        state = gb.new_state()
        state['denials'] = gb.DENY_CAP
        reason = self.decide(grep_event(self.big), state)
        self.assertIsNotNone(reason)
        self.assertNotIn('refused', reason)


class CodeWriterTests(TargetTests):
    """The writer has Read, Write, Grep, Glob — and no way to measure.

    check-file-size exempts its Reads, so no deny ever names a size, and
    without Bash it cannot run `wc -c`. Its content Grep on an over-budget
    file is therefore always unmeasured; what it must not be told is to
    hand the work to bulk-reader, which is not a route it has.
    """

    def writer_event(self, **inp):
        event = grep_event(self.big, **inp)
        event['agent_type'] = 'token-shunt:code-writer'
        return event

    def test_the_cap_does_not_send_the_writer_to_bulk_reader(self):
        state = gb.new_state()
        self.refuse(state, self.big, gb.DENY_CAP)
        reason = self.decide(self.writer_event(), state)
        self.assertNotIn('bulk-reader', reason)
        self.assertIn('files_with_matches', reason)

    def test_the_parent_is_still_sent_to_bulk_reader(self):
        state = gb.new_state()
        self.refuse(state, self.big, gb.DENY_CAP)
        self.assertIn('bulk-reader', self.decide(grep_event(self.big), state))

    def test_the_writer_is_not_told_to_run_a_command_it_cannot_run(self):
        self.assertNotIn('wc -c', self.decide(self.writer_event()))

    def test_the_parent_is_still_told_to_measure(self):
        self.assertIn('wc -c', self.decide(grep_event(self.big)))

    def test_a_spoofed_agent_type_in_the_tool_input_is_ignored(self):
        # Only the harness's top-level field is trusted; the model can put
        # anything in tool_input.
        event = grep_event(self.big, agent_type='token-shunt:code-writer')
        self.assertIn('wc -c', self.decide(event))

    def test_the_writer_keeps_the_routes_it_does_have(self):
        for inp in ({'output_mode': 'files_with_matches'},
                    {'output_mode': 'count'}):
            with self.subTest(inp=inp):
                self.assertIsNone(self.decide(self.writer_event(**inp)))


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

    def test_a_command_that_never_prints_a_size_records_nothing(self):
        """The hook cannot see stdout, so the command must have shown one.

        `stat -c %n` prints the name and nothing else; `stat -f` describes
        the filesystem. Recording either would mark the file measured
        without the caller ever having been told how big it is, which is
        the whole of the first rule.
        """
        for command in ('stat -c %n /srv/a.py', 'stat --format=%n /srv/a.py',
                        'stat --printf=%N /srv/a.py', 'stat -c %%s /srv/a.py',
                        'stat -f /srv/a.py', 'stat -f -c %s /srv/a.py',
                        # The same formats written as GNU also accepts
                        # them, with the value attached to the flag.
                        'stat -c%n /srv/a.py', 'stat -Lc%n /srv/a.py',
                        'stat --printf=%y /srv/a.py',
                        # And a flag whose meaning we do not know: a
                        # missed record costs a round trip, a wrong one
                        # licenses the search.
                        'stat -t /srv/a.py', 'stat --terse /srv/a.py'):
            with self.subTest(command=command):
                self.assertEqual(gb.metadata_paths(command), [])

    def test_a_format_that_does_print_the_size_still_records(self):
        for command in ('stat -c %s /srv/a.py', 'stat -c "%n %s" /srv/a.py',
                        'stat --printf=%10s /srv/a.py', 'stat -c%s /srv/a.py',
                        'stat -Lc%s /srv/a.py', 'stat -L /srv/a.py'):
            with self.subTest(command=command):
                self.assertEqual(gb.metadata_paths(command), ['/srv/a.py'])

    def test_a_comment_hides_the_file_the_size_was_not_taken_of(self):
        """`wc -c small # large` counts small; bash never sees large."""
        self.assertEqual(gb.metadata_paths('wc -c /srv/a.py # /srv/big.py'), [])

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

    def run_hook(self, event, *args, cwd=None):
        proc = subprocess.run([str(HOOKS / 'check-grep-bounds')] + list(args),
                              input=json.dumps(event), capture_output=True,
                              text=True, cwd=cwd)
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

    def test_the_real_read_deny_records_the_size_it_named(self):
        """Through `check-file-size` itself, not through `--sized`.

        The test above calls the recording mode directly, which says
        nothing about whether the deny path ever reaches it: unwire
        `record_sized` and it still passes. This one denies a real
        over-threshold Read and then searches the file.
        """
        wide = os.path.join(self.dir, 'wide.txt')
        with open(wide, 'w') as fh:
            fh.write(('y' * 200 + '\n') * 400)
        event = {'hook_event_name': 'PreToolUse', 'tool_name': 'Read',
                 'session_id': self.session, 'cwd': self.dir,
                 'tool_input': {'file_path': wide}}
        proc = subprocess.run([str(HOOKS / 'check-file-size')],
                              input=json.dumps(event), capture_output=True,
                              text=True)
        self.assertIn('deny', proc.stdout)
        self.assertIn(str(os.path.getsize(wide)), proc.stdout)
        self.assertEqual(self.run_hook(
            grep_event(wide, self.session, head_limit=5)), '')

    def test_each_refusal_is_counted_until_the_cap(self):
        """The counter lives in the executable, not in `decide()`.

        The cap tests record refusals through `note_denial` themselves, so
        the call that gets there could be deleted without turning any of
        them red. This one drives the hook end to end instead.
        """
        for _ in range(gb.DENY_CAP):
            denied = self.run_hook(
                grep_event(self.big, self.session, head_limit=5))
            self.assertIn('size has not been checked', denied)
        capped = self.run_hook(grep_event(self.big, self.session, head_limit=5))
        self.assertIn('refused %d times' % gb.DENY_CAP, capped)

    def test_stat_of_a_symlink_does_not_measure_what_it_points_at(self):
        """`stat` prints the link's own size, not the target's.

        Recording the target marked a 20 KB file measured on the strength
        of a 27-byte answer -- a size the caller was never shown.
        """
        link = os.path.join(self.dir, 'link.txt')
        os.symlink(self.big, link)
        self.run_hook({'hook_event_name': 'PostToolUse', 'tool_name': 'Bash',
                       'session_id': self.session,
                       'tool_input': {'command': 'stat -c %s ' + link}})
        self.assertIn('size has not been checked', self.run_hook(
            grep_event(self.big, self.session, head_limit=5)))
        # `stat -L` and `wc -c` both follow the link, so both do measure it.
        self.run_hook({'hook_event_name': 'PostToolUse', 'tool_name': 'Bash',
                       'session_id': self.session,
                       'tool_input': {'command': 'wc -c ' + link}})
        self.assertEqual(self.run_hook(
            grep_event(self.big, self.session, head_limit=5)), '')

    def test_a_relative_path_resolves_against_the_session_cwd(self):
        # The hook process runs wherever the CLI starts it. Only the event's
        # cwd says what "big.txt" meant to the caller, as check-file-size:238
        # and check-bash-read:248 already do for Read and Bash.
        elsewhere = tempfile.mkdtemp()
        event = grep_event('big.txt', self.session, head_limit=5)
        event['cwd'] = self.dir
        denied = self.run_hook(event, cwd=elsewhere)
        self.assertIn('size has not been checked', denied)
        self.run_hook({'hook_event_name': 'PostToolUse', 'tool_name': 'Bash',
                       'session_id': self.session, 'cwd': self.dir,
                       'tool_input': {'command': 'wc -c big.txt'}},
                      cwd=elsewhere)
        self.assertEqual(self.run_hook(event, cwd=elsewhere), '')

    def test_a_same_named_small_file_beside_the_hook_is_not_the_target(self):
        # The dangerous shape: judging the wrong file passes the search on
        # the big one, because the decoy is within budget.
        elsewhere = tempfile.mkdtemp()
        with open(os.path.join(elsewhere, 'big.txt'), 'w') as fh:
            fh.write('x' * 10)
        event = grep_event('big.txt', self.session)
        event['cwd'] = self.dir
        self.assertIn('size has not been checked',
                      self.run_hook(event, cwd=elsewhere))

    def test_a_cwd_that_is_not_a_usable_absolute_path_denies(self):
        # check-file-size denies rather than guessing; so does this.
        for cwd in ('relative/dir', '/nonexistent-%d' % os.getpid(), 5):
            with self.subTest(cwd=cwd):
                event = grep_event('big.txt', self.session, head_limit=5)
                event['cwd'] = cwd
                self.assertIn('cwd', self.run_hook(event))

    def test_an_absolute_path_is_unaffected_by_a_broken_cwd(self):
        # A Read deny names absolute paths; losing them to an unusable cwd
        # would make the size unknowable for the rest of the session.
        event = {'hook_event_name': 'PreToolUse', 'tool_name': 'Read',
                 'session_id': self.session, 'cwd': 'relative/dir',
                 'tool_input': {}}
        self.run_hook(event, '--sized', self.big)
        self.assertEqual(
            self.run_hook(grep_event(self.big, self.session, head_limit=5)), '')

    def test_an_unusable_event_fails_the_call_rather_than_allowing_it(self):
        proc = subprocess.run([str(HOOKS / 'check-grep-bounds')],
                              input='not json', capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)


if __name__ == '__main__':
    unittest.main()
