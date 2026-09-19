"""Lock B: what the parent has already taken on limits what it may Read next.

Design: docs/superpowers/specs/2026-09-19-cumulative-intake-design.md.

The hole is design 26.2 in its multi-turn form: every individual Read is
under the per-call threshold and the conversation still ends up holding the
corpus. Measured, one of 14 auto conversations took 32,098 bytes across
turns 2-4 while the other 13 stayed at or below 8,670
(reviews/multiturn-context-2026-09-18.md section 4-2).

Two halves, like Lock A. PostToolUse adds the bytes a successful parent read
returned; PreToolUse denies the next full-file read once the already
accumulated total is over budget. The read that crosses the line is not the
one that is denied: PreToolUse has no tool_response, so measuring what is
about to be read would mean estimating it, and spec section 2 buys one
overshoot rather than one estimate.

Charging is wider than denying on purpose (spec 3.3): a targeted Read is
charged but never denied, because two eval cases in the release gate reach
their Edit through a targeted Read of the original.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HOOKS = Path(__file__).resolve().parent.parent / 'plugin' / 'hooks'
sys.path.insert(0, str(HOOKS))
import intake_ledger as il  # noqa: E402


class LedgerFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / 'state'
        for name in ('TOKEN_SHUNT_SESSION_BUDGET_BYTES',):
            self.addCleanup(os.environ.pop, name, None)
            os.environ.pop(name, None)

    def read_event(self, path='/work/fixtures/m.py', **kw):
        event = {'session_id': kw.get('session', 's1'), 'tool_name': 'Read',
                 'tool_input': {'file_path': path}}
        if kw.get('offset') is not None:
            event['tool_input']['offset'] = kw['offset']
        if kw.get('limit') is not None:
            event['tool_input']['limit'] = kw['limit']
        if kw.get('agent_id'):
            event['agent_id'] = kw['agent_id']
        return event

    def done(self, body='x' * 100, **kw):
        """A PostToolUse Read event carrying what came back."""
        event = self.read_event(kw.pop('path', '/work/fixtures/m.py'), **kw)
        event['hook_event_name'] = 'PostToolUse'
        event['tool_response'] = kw.get('response', {
            'type': 'text',
            'file': {'filePath': event['tool_input']['file_path'],
                     'content': body}})
        return event

    def charge(self, event):
        return il.charge(event, root=self.root)

    def deny(self, event):
        return il.deny_reason(event, root=self.root)

    def total(self, session='s1'):
        return il.ledger(session, root=self.root)['bytes']

    def fill(self, amount, session='s1'):
        """Put `amount` bytes of successful parent reads on the ledger."""
        self.charge(self.done('x' * amount, session=session))
        self.assertEqual(amount, self.total(session))


class ChargingTests(LedgerFixture):
    def test_a_successful_parent_read_adds_its_body_bytes(self):
        self.charge(self.done('x' * 40))
        self.assertEqual(40, self.total())

    def test_the_bytes_are_utf8_not_characters(self):
        self.charge(self.done('あ' * 10))
        self.assertEqual(30, self.total())

    def test_reads_accumulate_across_the_session(self):
        self.charge(self.done('x' * 40))
        self.charge(self.done('y' * 60))
        self.assertEqual(100, self.total())
        self.assertEqual(2, il.ledger('s1', root=self.root)['reads'])

    def test_another_session_has_its_own_ledger(self):
        self.charge(self.done('x' * 40))
        self.assertEqual(0, self.total('s2'))

    def test_a_workers_read_is_not_charged_to_the_parent(self):
        # Charging it would fill the ledger fastest in the conversations that
        # delegated correctly, denying the parent for the worker's work.
        self.charge(self.done('x' * 40, agent_id='agent_1'))
        self.assertEqual(0, self.total())

    def test_a_read_that_came_back_as_an_error_is_zero_bytes(self):
        # Matches parent_turn_reads.py: a denied read put nothing in the
        # parent. The correction that counted denied Reads as breakthroughs
        # came from getting this rule wrong in the instrument.
        self.charge(self.done(response={'is_error': True,
                                        'content': 'denied'}))
        self.assertEqual(0, self.total())

    def test_a_read_failure_event_is_zero_bytes(self):
        event = self.done('x' * 40)
        event['hook_event_name'] = 'PostToolUseFailure'
        self.charge(event)
        self.assertEqual(0, self.total())

    def test_an_image_is_not_charged(self):
        self.charge(self.done('x' * 40, path='/work/fixtures/diagram.png'))
        self.assertEqual(0, self.total())

    def test_a_notebook_is_not_charged(self):
        self.charge(self.done('x' * 40, path='/work/fixtures/n.ipynb'))
        self.assertEqual(0, self.total())

    def test_a_targeted_read_is_charged_like_any_other(self):
        self.charge(self.done('x' * 40, offset=10, limit=50))
        self.assertEqual(40, self.total())

    def test_an_event_without_a_session_charges_nothing(self):
        event = self.done('x' * 40)
        event.pop('session_id')
        self.assertEqual(0, self.charge(event))


class DenyTests(LedgerFixture):
    def test_nothing_is_denied_under_budget(self):
        self.fill(1000)
        self.assertIsNone(self.deny(self.read_event()))

    def test_a_full_read_is_denied_once_the_total_is_over_budget(self):
        self.fill(23392)
        self.assertIsNotNone(self.deny(self.read_event()))

    def test_the_budget_itself_is_not_over_it(self):
        self.fill(16384)
        self.assertIsNone(self.deny(self.read_event()))

    def test_the_read_that_crosses_the_line_is_not_the_one_denied(self):
        # PreToolUse cannot know what this read will return without
        # estimating, so the crossing read passes and the next one is denied.
        self.fill(16000)
        self.assertIsNone(self.deny(self.read_event()))
        self.charge(self.done('x' * 9000))
        self.assertIsNotNone(self.deny(self.read_event()))

    def test_a_targeted_read_is_never_denied(self):
        # auto-edit-grep-location and compare-edit-dense-lines reach their
        # Edit through a targeted Read of the original (design 26.5). A
        # monotone cap that denies it would fail release-gate cases by
        # itself.
        self.fill(23392)
        self.assertIsNone(self.deny(self.read_event(offset=10, limit=50)))

    def test_an_offset_without_a_limit_is_still_a_full_read(self):
        self.fill(23392)
        self.assertIsNotNone(self.deny(self.read_event(offset=10)))

    def test_the_workers_read_is_never_denied(self):
        self.fill(23392)
        self.assertIsNone(self.deny(self.read_event(agent_id='agent_1')))

    def test_an_image_is_not_denied(self):
        # Nothing the ledger refuses to charge can push it over the line.
        self.fill(23392)
        self.assertIsNone(self.deny(self.read_event('/work/f/diagram.png')))

    def test_the_budget_is_configurable(self):
        os.environ['TOKEN_SHUNT_SESSION_BUDGET_BYTES'] = '1000'
        self.fill(1200)
        self.assertIsNotNone(self.deny(self.read_event()))

    def test_zero_disables_the_lock(self):
        os.environ['TOKEN_SHUNT_SESSION_BUDGET_BYTES'] = '0'
        self.fill(99999)
        self.assertIsNone(self.deny(self.read_event()))

    def test_a_malformed_budget_falls_back_to_the_default(self):
        os.environ['TOKEN_SHUNT_SESSION_BUDGET_BYTES'] = 'plenty'
        self.assertEqual(16384, il.budget())


class DenyWordingTests(LedgerFixture):
    def reason(self, taken=23392):
        if not self.total():
            self.fill(taken)
        return self.deny(self.read_event())

    def test_it_names_what_was_taken_and_what_the_budget_is(self):
        reason = self.reason()
        self.assertIn('23,392', reason)
        self.assertIn('16,384', reason)

    def test_it_says_the_budget_does_not_reset(self):
        # Without this the parent infers that delegating frees room, which
        # is the detour spec 3.2 closed.
        self.assertIn('does not reset', self.reason())

    def test_it_sends_the_path_to_the_worker(self):
        self.assertIn('/token-shunt:bulk-reader', self.reason())

    def test_it_does_not_advertise_a_targeted_read_as_the_way_through(self):
        # check-file-size names one on purpose; there it is bound by the same
        # thresholds. Here it is not denied at all, so naming it would
        # promote a documented hole to a recommended route.
        self.assertNotIn('offset', self.reason())
        self.assertNotIn('limit', self.reason())
        self.assertNotIn('targeted', self.reason())


class BrokenStateTests(LedgerFixture):
    def test_an_unparsable_ledger_reads_as_empty_and_denies_nothing(self):
        self.fill(23392)
        source = il.state_file('s1', root=self.root)
        source.write_text('{not json', encoding='utf-8')
        self.assertEqual(0, self.total())
        self.assertIsNone(self.deny(self.read_event()))

    def test_a_ledger_of_the_wrong_shape_reads_as_empty(self):
        self.fill(23392)
        il.state_file('s1', root=self.root).write_text('[]', encoding='utf-8')
        self.assertEqual(0, self.total())

    def test_a_negative_stored_total_reads_as_empty(self):
        self.fill(23392)
        il.state_file('s1', root=self.root).write_text(
            '{"bytes": -5, "reads": 1}', encoding='utf-8')
        self.assertEqual(0, self.total())

    def test_an_unwritable_state_directory_denies_nothing(self):
        self.root.write_text('not a directory', encoding='utf-8')
        self.assertEqual(0, self.charge(self.done('x' * 40)))
        self.assertIsNone(self.deny(self.read_event()))

    def test_a_read_with_no_session_is_never_denied(self):
        event = self.read_event()
        event.pop('session_id')
        self.assertIsNone(self.deny(event))


class NoResetTests(LedgerFixture):
    def test_delegating_does_not_clear_the_ledger(self):
        # If a worker launch reset it, one trivial delegation would buy
        # unlimited reading and the mechanism would be a contract clause
        # again.
        self.fill(23392)
        il.record_main(json.dumps({
            'session_id': 's1', 'tool_name': 'Agent', 'hook_event_name':
            'PostToolUse', 'tool_input': {
                'subagent_type': 'token-shunt:bulk-reader',
                'prompt': 'read it'},
            'tool_response': {'agentId': 'agent_1'}}), root=self.root)
        self.assertEqual(23392, self.total())
        self.assertIsNotNone(self.deny(self.read_event()))


class BashTests(LedgerFixture):
    """`cat big` puts the same bytes in the parent as a Read does."""

    def bash_event(self, command='cat /work/fixtures/m.py', **kw):
        return {'session_id': kw.get('session', 's1'), 'tool_name': 'Bash',
                'tool_use_id': kw.get('use', 'call_1'),
                'tool_input': {'command': command}}

    def test_a_reader_bash_call_marked_before_running_is_charged_after(self):
        il.mark_reader(self.bash_event(), root=self.root)
        done = self.bash_event()
        done['hook_event_name'] = 'PostToolUse'
        done['tool_response'] = {'stdout': 'x' * 40, 'stderr': ''}
        self.charge(done)
        self.assertEqual(40, self.total())

    def test_an_unmarked_bash_call_is_not_charged(self):
        # Only the calls check-bash-read recognised as readers are charged;
        # nothing here re-derives that classification.
        done = self.bash_event('npm test')
        done['hook_event_name'] = 'PostToolUse'
        done['tool_response'] = {'stdout': 'x' * 40, 'stderr': ''}
        self.charge(done)
        self.assertEqual(0, self.total())

    def test_a_mark_is_spent_once(self):
        il.mark_reader(self.bash_event(), root=self.root)
        done = self.bash_event()
        done['hook_event_name'] = 'PostToolUse'
        done['tool_response'] = {'stdout': 'x' * 40, 'stderr': ''}
        self.charge(done)
        self.charge(done)
        self.assertEqual(40, self.total())

    def test_a_reader_bash_call_is_denied_over_budget(self):
        self.fill(23392)
        self.assertIsNotNone(il.bash_deny_reason(self.bash_event(),
                                                 root=self.root))

    def test_a_reader_bash_call_under_budget_is_marked_not_denied(self):
        self.fill(1000)
        self.assertIsNone(il.bash_deny_reason(self.bash_event(),
                                              root=self.root))
        done = self.bash_event()
        done['hook_event_name'] = 'PostToolUse'
        done['tool_response'] = {'stdout': 'x' * 40, 'stderr': ''}
        self.charge(done)
        self.assertEqual(1040, self.total())

    def test_a_workers_bash_read_is_neither_marked_nor_denied(self):
        self.fill(23392)
        event = self.bash_event()
        event['agent_id'] = 'agent_1'
        self.assertIsNone(il.bash_deny_reason(event, root=self.root))


class EntryPointTests(LedgerFixture):
    def test_the_pretooluse_half_emits_a_deny_decision(self):
        self.fill(23392)
        out = json.loads(il.read_main(json.dumps(self.read_event()),
                                      root=self.root))
        decision = out['hookSpecificOutput']
        self.assertEqual('PreToolUse', decision['hookEventName'])
        self.assertEqual('deny', decision['permissionDecision'])
        self.assertTrue(
            decision['permissionDecisionReason'].startswith('token-shunt: '))

    def test_the_pretooluse_half_says_nothing_when_allowed(self):
        self.fill(1000)
        self.assertEqual('', il.read_main(json.dumps(self.read_event()),
                                          root=self.root))

    def test_the_posttooluse_half_charges_and_says_nothing(self):
        self.assertEqual('', il.record_main(json.dumps(self.done('x' * 40)),
                                            root=self.root))
        self.assertEqual(40, self.total())

    def test_unreadable_stdin_denies_nothing(self):
        self.assertEqual('', il.read_main('{not json', root=self.root))
        self.assertEqual('', il.record_main('', root=self.root))


class WiringTests(unittest.TestCase):
    """The halves only work registered, and the Bash half only from inside
    check-bash-read: that script owns the reader classification and nothing
    here re-derives it."""

    def setUp(self):
        self.hooks = HOOKS
        self.config = json.loads((HOOKS / 'hooks.json').read_text())

    def commands(self, event, matcher):
        for entry in self.config['hooks'][event]:
            if entry.get('matcher') == matcher:
                return [h['command'].rsplit('/', 1)[-1] for h in entry['hooks']]
        return []

    def test_the_pretooluse_half_runs_on_read_after_the_delegation_lock(self):
        names = self.commands('PreToolUse', 'Read')
        self.assertIn('check-intake-budget', names)
        self.assertLess(names.index('check-delegated-read'),
                        names.index('check-intake-budget'))

    def test_the_posttooluse_half_charges_reads_and_bash_output(self):
        self.assertIn('record-intake', self.commands('PostToolUse', 'Read'))
        self.assertIn('record-intake', self.commands('PostToolUse', 'Bash'))

    def test_the_entry_points_are_executable(self):
        for name in ('check-intake-budget', 'record-intake'):
            self.assertTrue(os.access(self.hooks / name, os.X_OK), name)


class EndToEndTests(unittest.TestCase):
    """The hooks as the harness runs them: a process, stdin, stdout."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = dict(os.environ, TMPDIR=str(self.tmp))
        self.env.pop('TOKEN_SHUNT_SESSION_BUDGET_BYTES', None)

    def run_hook(self, name, event, *args):
        return subprocess.run([str(HOOKS / name)] + list(args),
                              input=json.dumps(event), text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=self.env, timeout=10)

    def read_event(self, **kw):
        event = {'session_id': 's1', 'tool_name': 'Read',
                 'tool_input': {'file_path': '/work/fixtures/m.py'}}
        event.update(kw)
        return event

    def fill(self, amount):
        done = self.read_event(hook_event_name='PostToolUse')
        done['tool_response'] = {'type': 'text', 'file': {'content': 'x' * amount}}
        got = self.run_hook('record-intake', done)
        self.assertEqual(0, got.returncode, got.stderr)
        self.assertEqual('', got.stdout)

    def test_a_full_read_over_budget_is_denied_through_the_entry_point(self):
        self.fill(23392)
        got = self.run_hook('check-intake-budget', self.read_event())
        self.assertEqual(0, got.returncode, got.stderr)
        decision = json.loads(got.stdout)['hookSpecificOutput']
        self.assertEqual('deny', decision['permissionDecision'])
        self.assertIn('23,392', decision['permissionDecisionReason'])

    def test_a_read_under_budget_passes_silently(self):
        self.fill(1000)
        got = self.run_hook('check-intake-budget', self.read_event())
        self.assertEqual(0, got.returncode)
        self.assertEqual('', got.stdout)

    def test_a_known_reader_bash_call_is_denied_by_check_bash_read(self):
        # The gate lives inside check-bash-read because that is where a
        # command is recognised as a reader; the ledger never parses a
        # command line of its own.
        self.fill(23392)
        target = self.tmp / 'm.py'
        target.write_text('x' * 100, encoding='utf-8')
        got = self.run_hook('check-bash-read', {
            'session_id': 's1', 'tool_name': 'Bash', 'tool_use_id': 'call_1',
            'tool_input': {'command': 'cat %s' % target}})
        self.assertEqual(0, got.returncode, got.stderr)
        self.assertIn('budget', got.stdout)
        self.assertIn('deny', got.stdout)

    def test_bash_that_reads_nothing_is_untouched_over_budget(self):
        self.fill(23392)
        got = self.run_hook('check-bash-read', {
            'session_id': 's1', 'tool_name': 'Bash', 'tool_use_id': 'call_2',
            'tool_input': {'command': 'echo hello'}})
        self.assertEqual(0, got.returncode, got.stderr)
        self.assertEqual('', got.stdout)

    def test_a_reader_under_budget_is_charged_for_what_it_printed(self):
        target = self.tmp / 'm.py'
        target.write_text('x' * 100, encoding='utf-8')
        call = {'session_id': 's1', 'tool_name': 'Bash',
                'tool_use_id': 'call_3',
                'tool_input': {'command': 'cat %s' % target}}
        self.assertEqual('', self.run_hook('check-bash-read', call).stdout)
        done = dict(call, hook_event_name='PostToolUse',
                    tool_response={'stdout': 'x' * 100, 'stderr': ''})
        self.run_hook('record-intake', done)
        root = self.tmp / ('token-shunt-intake-%d' % os.getuid())
        stored = json.loads(next(root.glob('*.json')).read_text())
        self.assertEqual(100, stored['bytes'])


if __name__ == '__main__':
    unittest.main()
