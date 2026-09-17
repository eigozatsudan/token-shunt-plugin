"""Lock A: a path that went to a worker is not the parent's to Read.

Design: reviews/delegated-read-lock-design-2026-09-17.md section 2.

`check-file-size` passes a targeted Read by design, because the step 4 edit
contract needs one, and the skill's own clause did not hold: with the
wording pinned, 13 of 60 delegate arms still read a delegated path
(reviews/parent-no-read-rate-2026-09-17.md). Six of the 31 leaked path
instances are a path the parent had itself sent to a worker, which is the
part a hook can see (reviews/parent-no-read-shape-2026-09-17.md section 1).

The lock has two halves: the launch writes the paths it handed over, and
the parent's next Read of one of them is denied. Both halves are here.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

HOOKS = Path(__file__).resolve().parent.parent / 'plugin' / 'hooks'
sys.path.insert(0, str(HOOKS))
import delegated_paths as dp  # noqa: E402


class LockFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / 'state'
        self.files = self.tmp / 'work'
        self.files.mkdir()
        self.big = self.files / 'user.rb'
        self.big.write_text('x' * 200, encoding='utf-8')
        self.small = self.files / 'notifiable.rb'
        self.small.write_text('y' * 30, encoding='utf-8')

    def launch(self, *paths, **kw):
        prompt = kw.get('prompt', 'Question. Paths: ' + ' '.join(str(p) for p in paths))
        return {'session_id': kw.get('session', 's1'),
                'tool_name': kw.get('tool_name', 'Agent'),
                'tool_input': {'subagent_type': kw.get('subagent_type',
                                                       'token-shunt:bulk-reader'),
                               'model': 'haiku', 'prompt': prompt},
                'tool_response': kw.get('response', {'agentId': 'agent_1'})}

    def read(self, path, **kw):
        event = {'session_id': kw.get('session', 's1'),
                 'tool_name': 'Read',
                 'tool_input': {'file_path': str(path)}}
        if kw.get('agent_id'):
            event['agent_id'] = kw['agent_id']
        event['tool_input'].update(kw.get('extra') or {})
        return event

    def record(self, event):
        return dp.record(event, root=self.root)

    def deny(self, event):
        return dp.deny_reason(event, root=self.root)


class LockATests(LockFixture):
    def test_a_delegated_path_is_denied_to_the_parent(self):
        self.record(self.launch(self.big))
        self.assertIsNotNone(self.deny(self.read(self.big)))

    def test_the_worker_may_read_what_it_was_given(self):
        # The state is keyed by session, and the worker shares the session.
        # Denying it would deny the delegation itself.
        self.record(self.launch(self.big))
        self.assertIsNone(self.deny(self.read(self.big, agent_id='agent_1')))

    def test_a_path_that_was_never_delegated_is_not_denied(self):
        self.record(self.launch(self.big))
        self.assertIsNone(self.deny(self.read(self.small)))

    def test_a_targeted_read_of_a_delegated_path_is_denied_too(self):
        # This is the hole check-file-size leaves open on purpose: a slice
        # of a delegated file passed every check on Django
        # (reviews/django-dose-2026-09-17.md section 5).
        self.record(self.launch(self.big))
        self.assertIsNotNone(
            self.deny(self.read(self.big, extra={'offset': 525, 'limit': 15})))

    def test_a_launch_that_did_not_start_a_worker_records_nothing(self):
        self.record(self.launch(self.big, response={'error': 'no such agent'}))
        self.assertIsNone(self.deny(self.read(self.big)))

    def test_another_agent_type_is_not_our_delegation(self):
        self.record(self.launch(self.big, subagent_type='general-purpose'))
        self.assertIsNone(self.deny(self.read(self.big)))

    def test_the_task_tool_is_the_same_launch(self):
        self.record(self.launch(self.big, tool_name='Task'))
        self.assertIsNotNone(self.deny(self.read(self.big)))

    def test_another_session_is_not_this_one(self):
        self.record(self.launch(self.big, session='s1'))
        self.assertIsNone(self.deny(self.read(self.big, session='s2')))

    def test_a_writer_launch_locks_its_paths_too(self):
        # check-final-answer treats both worker types alike; a path handed
        # to the writer is no more the parent's to read.
        self.record(self.launch(self.big, subagent_type='token-shunt:code-writer'))
        self.assertIsNotNone(self.deny(self.read(self.big)))

    def test_the_same_file_by_another_spelling_is_the_same_file(self):
        link = self.tmp / 'link.rb'
        os.symlink(self.big, link)
        self.record(self.launch(self.big))
        self.assertIsNotNone(self.deny(self.read(link)))


class NothingKnownDeniesNothingTests(LockFixture):
    """`reader_scope`'s rule: an unreadable state refuses nothing."""

    def test_no_state_at_all_denies_nothing(self):
        self.assertIsNone(self.deny(self.read(self.big)))

    def test_an_unreadable_state_denies_nothing(self):
        self.record(self.launch(self.big))
        for entry in self.root.iterdir():
            entry.write_text('{ not json', encoding='utf-8')
        self.assertIsNone(self.deny(self.read(self.big)))

    def test_a_read_without_a_path_denies_nothing(self):
        self.record(self.launch(self.big))
        event = self.read(self.big)
        event['tool_input'] = {}
        self.assertIsNone(self.deny(event))

    def test_a_launch_prompt_with_no_path_records_nothing(self):
        self.record(self.launch(prompt='Question with no path at all.'))
        self.assertIsNone(self.deny(self.read(self.big)))

    def test_a_named_file_that_does_not_exist_is_not_recorded(self):
        missing = self.files / 'gone.rb'
        self.record(self.launch(missing))
        self.assertIsNone(self.deny(self.read(missing)))

    def test_a_session_without_an_id_is_not_recorded(self):
        event = self.launch(self.big)
        del event['session_id']
        self.record(event)
        self.assertIsNone(self.deny(self.read(self.big)))


class DenyTextTests(LockFixture):
    def test_the_deny_does_not_offer_a_targeted_read_as_the_way_out(self):
        # check-file-size says "For edits, use a targeted Read of the
        # original that passes the hook". Repeating that here would hand
        # back the exact move this lock exists to stop.
        self.record(self.launch(self.big))
        reason = self.deny(self.read(self.big))
        self.assertNotIn('targeted Read', reason)

    def test_the_deny_names_what_to_do_instead(self):
        # A deny that names no alternative strands the parent, which is the
        # failure check-worker-resume was fixed for
        # (evals/test_worker_resume.py).
        self.record(self.launch(self.big))
        reason = self.deny(self.read(self.big))
        self.assertIn('new', reason)
        self.assertIn('worker', reason)

    def test_the_deny_names_the_path(self):
        self.record(self.launch(self.big))
        self.assertIn(str(self.big), self.deny(self.read(self.big)))


class EntryPointTests(LockFixture):
    """The two scripts hooks.json will name."""

    def test_the_read_hook_emits_a_pretooluse_deny(self):
        self.record(self.launch(self.big))
        out = dp.read_main(json.dumps(self.read(self.big)), root=self.root)
        payload = json.loads(out)['hookSpecificOutput']
        self.assertEqual('PreToolUse', payload['hookEventName'])
        self.assertEqual('deny', payload['permissionDecision'])
        self.assertTrue(payload['permissionDecisionReason'].startswith('token-shunt: '))

    def test_the_read_hook_stays_silent_when_it_allows(self):
        self.assertEqual('', dp.read_main(json.dumps(self.read(self.big)),
                                          root=self.root))

    def test_malformed_stdin_allows(self):
        self.assertEqual('', dp.read_main('{ not json', root=self.root))

    def test_the_launch_hook_returns_no_output(self):
        self.assertEqual('', dp.launch_main(json.dumps(self.launch(self.big)),
                                            root=self.root))


class DeclaredBeforeClosedTests(unittest.TestCase):
    """The lock closes an affordance, so the skill has to say it is gone.

    check-file-size passes a targeted Read for the step 4 edit contract.
    Lock A denies that for a delegated path, so delegate-then-edit stops
    working. No case does both today (child_reads_once and the edit keys
    never meet), but breaking it silently is not the same as declaring it
    (reviews/delegated-read-lock-design-2026-09-17.md section 2.1).
    """

    def test_the_skill_declares_delegate_then_edit_out_of_scope(self):
        skill = ' '.join((HOOKS.parent / 'skills' / 'bulk-reader'
                          / 'SKILL.md').read_text(encoding='utf-8').split())
        tail = skill[skill.index('Out of scope in v0.1'):]
        self.assertIn('already gone to a worker', tail)
        self.assertIn('keep it out of the worker call', tail)

    def test_no_case_needs_both(self):
        cases = json.loads((Path(__file__).resolve().parent.parent / 'evals'
                            / 'compare' / 'cases.json').read_text(
                                encoding='utf-8'))['cases']
        for case in cases:
            delegate = (case.get('expect') or {}).get('delegate') or {}
            if not delegate.get('child_reads_once'):
                continue
            blob = json.dumps(case.get('expect'))
            with self.subTest(case=case['id']):
                self.assertNotIn('parent_targeted_read', blob)
                self.assertNotIn('edit_flow', blob)


class RegistrationTests(unittest.TestCase):
    """Both halves have to be wired, or the lock is inert."""

    def hooks(self, event, matcher):
        entries = json.loads((HOOKS / 'hooks.json').read_text(
            encoding='utf-8'))['hooks'][event]
        return [h['command'] for entry in entries
                if matcher in entry['matcher']
                for h in entry['hooks']]

    def test_the_launch_half_runs_after_a_worker_starts(self):
        commands = self.hooks('PostToolUse', 'Agent')
        self.assertTrue(any(c.endswith('/hooks/record-delegated-paths')
                            for c in commands), commands)

    def test_the_read_half_runs_before_a_read(self):
        commands = self.hooks('PreToolUse', 'Read')
        self.assertTrue(any(c.endswith('/hooks/check-delegated-read')
                            for c in commands), commands)

    def test_both_scripts_are_executable(self):
        for name in ('record-delegated-paths', 'check-delegated-read'):
            self.assertTrue(os.access(HOOKS / name, os.X_OK), name)


if __name__ == '__main__':
    unittest.main()
