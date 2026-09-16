"""The retention rule reaches the parent at every worker launch.

Section 1 of reviews/a-suite-failures-9346d19-2026-09-16.md: the worker
returned three absolute paths and the parent wrote basenames. The send-back
repairs that after the fact, but only when it is on, and nothing states the
rule between the worker's report and the answer the parent writes from it.

The report arrives as a `<task-notification>`, which no hook event observes
(reviews/stop-hook-spec-2026-09-15.md section 1), so the last deliverable
moment is the launch itself. PostToolUse is the event this CLI delivers
`additionalContext` from; PreToolUse accepts the field in its schema but
never turns it into a message.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

HOOKS = Path(__file__).resolve().parent.parent / 'plugin' / 'hooks'
sys.path.insert(0, str(HOOKS))
import worker_launch as wl  # noqa: E402


def launch(subagent_type, tool_name='Agent'):
    return {'tool_name': tool_name,
            'tool_input': {'subagent_type': subagent_type, 'model': 'haiku',
                           'prompt': 'question plus paths'},
            'tool_response': {'agentId': 'agent_1'}}


class ReminderTests(unittest.TestCase):
    def test_a_reader_launch_carries_the_retention_rule(self):
        note = wl.decide(launch('token-shunt:bulk-reader'))
        self.assertIsNotNone(note)
        self.assertIn('verbatim', note)
        self.assertIn('absolute path', note)
        self.assertIn('unconfirmed:', note)

    def test_the_rule_names_the_failure_it_prevents(self):
        # "keep the path" alone is what the call contract already said and
        # the parent still shortened to basenames; the reminder has to name
        # that move.
        self.assertIn('basename', wl.decide(launch('token-shunt:bulk-reader')))

    def test_the_reminder_says_it_is_not_for_the_worker(self):
        # The call contract warns that instructions addressed to the parent
        # end up pasted into the worker prompt, and a worker told how to
        # write the parent's answer reports nothing useful.
        note = wl.decide(launch('token-shunt:bulk-reader'))
        self.assertIn('addressed to you', note)
        self.assertIn('prompt', note)

    def test_a_writer_launch_carries_it_too(self):
        # check-final-answer judges retention for both worker types, so the
        # reminder cannot be narrower than the check.
        self.assertIsNotNone(wl.decide(launch('token-shunt:code-writer')))

    def test_the_task_tool_name_is_the_same_launch(self):
        self.assertIsNotNone(
            wl.decide(launch('token-shunt:bulk-reader', tool_name='Task')))

    def test_another_agent_is_not_ours_to_instruct(self):
        self.assertIsNone(wl.decide(launch('general-purpose')))
        self.assertIsNone(wl.decide(launch(None)))

    def test_another_tool_is_not_a_launch(self):
        event = launch('token-shunt:bulk-reader')
        event['tool_name'] = 'Read'
        self.assertIsNone(wl.decide(event))

    def test_a_malformed_event_is_not_a_launch(self):
        self.assertIsNone(wl.decide({'tool_name': 'Agent'}))
        self.assertIsNone(wl.decide({'tool_name': 'Agent',
                                     'tool_input': 'bulk-reader'}))

    def test_a_launch_that_did_not_start_is_not_reminded(self):
        # PostToolUse also fires for a call the tool refused. Nothing was
        # delegated, so there is no report to retain.
        event = launch('token-shunt:bulk-reader')
        event['tool_response'] = {'error': 'agent type not found'}
        self.assertIsNone(wl.decide(event))


class HookTests(unittest.TestCase):
    def run_hook(self, event):
        proc = subprocess.run([str(HOOKS / 'check-worker-launch')],
                              input=json.dumps(event), text=True,
                              capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_the_payload_is_post_tool_use_additional_context(self):
        out = json.loads(self.run_hook(launch('token-shunt:bulk-reader')))
        payload = out['hookSpecificOutput']
        self.assertEqual(payload['hookEventName'], 'PostToolUse')
        self.assertTrue(payload['additionalContext'].startswith('token-shunt: '))
        self.assertNotIn('permissionDecision', payload)

    def test_a_foreign_launch_is_quiet(self):
        self.assertEqual('', self.run_hook(launch('general-purpose')))

    def test_unparsable_input_is_not_a_turn_failure(self):
        proc = subprocess.run([str(HOOKS / 'check-worker-launch')],
                              input='{not json', text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, '')


class RegistrationTests(unittest.TestCase):
    def test_the_agent_launch_is_matched_by_the_registered_hook(self):
        hooks = json.loads((HOOKS / 'hooks.json').read_text(
            encoding='utf-8'))['hooks']['PostToolUse']
        commands = [h['command'] for entry in hooks
                    if 'Agent' in entry['matcher']
                    for h in entry['hooks']]
        self.assertTrue(any(c.endswith('/hooks/check-worker-launch')
                            for c in commands), commands)

    def test_the_entry_point_is_executable(self):
        self.assertTrue(os.access(HOOKS / 'check-worker-launch', os.X_OK))

    def test_the_judge_attributes_the_new_matcher_to_us(self):
        # A registered hook whose matcher is not in the allow-list makes
        # every delegating case fail as a foreign hook.
        sys.path.insert(0, str(Path(__file__).resolve().parent / 'compare'))
        import judge
        self.assertIn('check-worker-launch', judge.TS_HOOKS)
        for name in ('PostToolUse:Agent', 'PostToolUse:Task',
                     'PostToolUse:Agent|Task'):
            self.assertIn(name, judge.TS_HOOK_NAMES)


if __name__ == '__main__':
    unittest.main()
