import unittest
from judge import Transcript, agent_resolved_models
from routing_checks import rejected_model_launch, check_routing


class ModelLaunchDenialTests(unittest.TestCase):
    def events(self, error=True, reason=None, model=None, child=False):
        reason = reason or 'token-shunt: Agent model must be explicitly haiku or sonnet.'
        inp = {'subagent_type': 'token-shunt:bulk-reader', 'prompt': '/a.py'}
        if model is not None:
            inp['model'] = model
        events = [
            {'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'name': 'Agent', 'id': 'a0', 'input': inp}]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'a0', 'is_error': error, 'content': reason}]}}
        ]
        if child:
            events.insert(1, {'type': 'assistant', 'parent_tool_use_id': 'a0',
                             'message': {'model': 'claude-haiku', 'content': [
                                 {'type': 'text', 'text': 'worked'}]}})
        return events

    def test_model_hook_denial_not_a_launched_worker(self):
        tr = Transcript(self.events())
        self.assertTrue(rejected_model_launch(tr, tr.parent_tool_uses()[0]))
        self.assertEqual([], tr.agent_uses())

    def test_do_not_hide_errors_or_child_activity(self):
        for kwargs in ({'error': False}, {'reason': 'permission denied'},
                       {'model': 'haiku'}, {'child': True}):
            with self.subTest(**kwargs):
                tr = Transcript(self.events(**kwargs))
                self.assertFalse(rejected_model_launch(tr, tr.parent_tool_uses()[0]))
                self.assertEqual(1, len(tr.agent_uses()))

    def test_resend_starts_haiku_without_escalation(self):
        evs = self.events()
        evs += [
            {'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'name': 'Agent', 'id': 'a1', 'input': {
                    'subagent_type': 'token-shunt:bulk-reader', 'model': 'haiku',
                    'prompt': '/a.py'}}]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'a1', 'resolvedModel': 'claude-haiku',
                 'content': 'status: complete\nstop_reason: facts found'}]}},
            {'type': 'result', 'result': 'done'}
        ]
        tr = Transcript(evs)
        self.assertEqual([], check_routing(tr, {}, {'retry_policy': True},
                                          'auto', tr.agent_uses(), agent_resolved_models))
