import copy
import json
import os
import tempfile
import unittest

from flow_checks import edit_flow_errors, verification_errors, verify_artifact
from judge import Transcript, is_full_parent_read, use_targets_path


def call(uid, name, inp, child=None):
    return {'type': 'assistant', 'parent_tool_use_id': child, 'message': {'content': [
        {'type': 'tool_use', 'id': uid, 'name': name, 'input': inp}]}}


def result(uid, text='', error=False, child=None):
    return {'type': 'user', 'parent_tool_use_id': child, 'message': {'content': [
        {'type': 'tool_result', 'tool_use_id': uid, 'content': text, 'is_error': error}]}}


class EditEvidenceTest(unittest.TestCase):
    path = '/abs/edit.py'
    def events(self):
        return [call('g', 'Grep', {'path': self.path, 'pattern': 'HDR_MODE', '-n': True}),
                result('g', "5:HDR_MODE = 'off'"),
                call('r', 'Read', {'file_path': self.path, 'offset': 5, 'limit': 1}),
                result('r', "     5→HDR_MODE = 'off'"),
                call('e', 'Edit', {'file_path': self.path, 'old_string': "HDR_MODE = 'off'", 'new_string': "HDR_MODE = 'on'"}),
                result('e', 'success')]
    def errors(self, events):
        return edit_flow_errors(Transcript(events), {'path': self.path, 'original_mark': 'HDR_MODE'}, {}, use_targets_path, is_full_parent_read)
    def test_successful_order(self):
        self.assertEqual([], self.errors(self.events()))
    def test_grep_function_then_read_edit_target(self):
        ev = self.events()
        ev[0]['message']['content'][0]['input']['pattern'] = '^def render_header'
        ev[1] = result('g', "4:def render_header():")
        ev[2]['message']['content'][0]['input'].update(offset=4, limit=2)
        ev[3] = result('r', "4→def render_header():\n5→HDR_MODE = 'off'")
        self.assertEqual([], self.errors(ev))
    def test_edit_before_read(self):
        ev = self.events()
        self.assertTrue(self.errors(ev[4:] + ev[:4]))
    def test_pending_read_before_edit(self):
        ev = self.events()
        self.assertTrue(self.errors(ev[:3] + ev[4:] + ev[3:4]))
    def test_failed_grep(self):
        ev = self.events(); ev[1] = result('g', "5:HDR_MODE = 'off'", True)
        self.assertTrue(self.errors(ev))
    def test_unrelated_grep(self):
        ev = self.events(); ev[0]['message']['content'][0]['input']['path'] = '/elsewhere.py'
        self.assertTrue(self.errors(ev))
    def test_grep_ambiguous(self):
        ev = self.events(); ev[1] = result('g', "5:HDR_MODE = 'off'\n50:HDR_MODE = 'off'")
        self.assertTrue(self.errors(ev))
    def test_grep_location_not_in_read(self):
        ev = self.events(); ev[1] = result('g', "50:HDR_MODE = 'off'")
        self.assertTrue(self.errors(ev))
    def test_read_error_or_missing_old_text(self):
        for response in [result('r', 'HDR_MODE missing old value'), result('r', "HDR_MODE = 'off'", True)]:
            ev = self.events(); ev[3] = response
            self.assertTrue(self.errors(ev))
    def test_prior_unsafe_edit_not_repaired_by_later_evidence(self):
        ev = self.events()
        first = call('early', 'Edit', {'file_path': self.path, 'old_string': 'old'})
        self.assertTrue(self.errors([first, result('early')] + ev))


class VerificationEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.artifacts = [{'path': '/tmp/config.json', 'level': 'syntax', 'checker': '/eval/flow_checks.py'},
                          {'path': '/tmp/fence.md', 'level': 'minimal', 'checker': '/eval/flow_checks.py'}]
        self.exp = {'verification_level': {'config.json': 'syntax'}, 'verification_artifacts': self.artifacts}
        self.spec = {'verification_controls': [{'path': '/tmp/fence.md', 'forbid_levels': ['requirements'], 'forbid_status': ['complete'], 'allowed_status': ['partial']}]}
        self.report = '| config.json | syntax | partial |\n| fence.md | minimal | partial |'
    def events(self):
        events = []
        for i, a in enumerate(self.artifacts):
            events += [call(str(i), 'Bash', {'command': 'python3 /eval/flow_checks.py --verify ' + a['level'] + ' ' + a['path']}),
                       result(str(i), json.dumps({'path': a['path'], 'verification': a['level'], 'ok': True}))]
        return events + [{'type': 'result', 'result': self.report}]
    def errors(self, events):
        return verification_errors(Transcript(events), self.spec, self.exp)
    def test_scoped_markdown_success(self):
        self.assertEqual([], self.errors(self.events()))
    def test_explicit_fields_allow_explanation_of_unchecked_requirements(self):
        ev = self.events()
        ev[-1]['result'] = 'config.json verification: syntax status: partial; requirements remain unverified.\nfence.md verification: minimal status: partial'
        self.assertEqual([], self.errors(ev))
    def test_claim_without_execution(self):
        self.assertTrue(self.errors(self.events()[-1:]))
    def test_complete_for_generated_artifact(self):
        ev = self.events(); ev[-1]['result'] = self.report.replace('syntax | partial', 'syntax | complete')
        self.assertTrue(self.errors(ev))
    def test_control_omitted(self):
        ev = self.events(); ev[-1]['result'] = '| config.json | syntax | partial |'
        self.assertTrue(self.errors(ev))
    def test_adjacent_reports_do_not_leak_levels(self):
        self.spec['verification_controls'][0]['forbid_levels'] = ['syntax', 'requirements']
        self.assertEqual([], self.errors(self.events()))
    def test_verification_result_after_report(self):
        ev = self.events()
        report = {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': self.report}]}}
        self.assertTrue(self.errors(ev[:3] + [report] + ev[3:]))
    def test_wrong_result_or_command_or_child(self):
        for change in ['result', 'command', 'child']:
            ev = self.events()
            if change == 'result': ev[1] = result('0', '{"ok": true}')
            if change == 'command': ev[0]['message']['content'][0]['input']['command'] = 'echo python3 /eval/flow_checks.py --verify syntax /tmp/config.json'
            if change == 'child': ev[0]['parent_tool_use_id'] = 'agent'
            self.assertTrue(self.errors(ev), change)
    def test_requirements_execution_requires_the_acceptance_keys_in_the_command(self):
        self.artifacts.append({'path': '/tmp/req.json', 'level': 'requirements',
                               'require_keys': ['required_key=rk-1'],
                               'checker': '/eval/flow_checks.py'})
        self.spec['verification_controls'].append(
            {'path': '/tmp/req.json', 'expected_level': 'requirements',
             'allowed_status': ['complete'], 'forbid_levels': ['minimal', 'syntax'],
             'forbid_status': ['partial', 'failed', 'error']})
        self.report += '\n| req.json | requirements | complete |'
        events = self.events()
        # events() builds the command without --require-key: not requirements evidence.
        self.assertTrue(self.errors(events))
        events[4]['message']['content'][0]['input']['command'] += ' --require-key required_key=rk-1'
        self.assertEqual([], self.errors(events))

    def test_requirements_underclaim_is_a_false_rejection(self):
        self.artifacts.append({'path': '/tmp/req.json', 'level': 'requirements',
                               'require_keys': ['required_key=rk-1'],
                               'checker': '/eval/flow_checks.py'})
        self.spec['verification_controls'].append(
            {'path': '/tmp/req.json', 'expected_level': 'requirements',
             'allowed_status': ['complete'], 'forbid_levels': ['minimal', 'syntax'],
             'forbid_status': ['partial', 'failed', 'error']})
        self.report += '\n| req.json | syntax | partial |'
        events = self.events()
        events[4]['message']['content'][0]['input']['command'] += ' --require-key required_key=rk-1'
        errors = self.errors(events)
        self.assertTrue(any(key == 'verification_control' for key, _ in errors), errors)

    def test_expected_parse_failure_is_valid_execution(self):
        self.artifacts[0]['ok'] = False
        ev = self.events(); ev[1] = result('0', json.dumps({'path': '/tmp/config.json', 'verification': 'syntax', 'ok': False}), True)
        self.assertEqual([], self.errors(ev))


class ArtifactCheckerTest(unittest.TestCase):
    def evidence(self, body, ext, level, expected=None, keys=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'artifact' + ext)
            with open(path, 'w') as stream: stream.write(body)
            return verify_artifact(path, level, expected, keys)
    def verify(self, body, ext, level, expected=None, keys=None):
        return self.evidence(body, ext, level, expected, keys)['ok']
    def test_legitimate_markdown_fence(self):
        self.assertTrue(self.verify('# Notes\n\n```python\nprint(1)\n```\n', '.md', 'minimal'))
    def test_markdown_output_wrapper_fails(self):
        self.assertFalse(self.verify('```markdown\n# Notes\n```', '.md', 'minimal'))
    def test_empty_and_gross_line_mismatch_fail(self):
        self.assertFalse(self.verify('', '.md', 'minimal'))
        self.assertFalse(self.verify('one', '.md', 'minimal', 30))
    def test_yaml_fenced_output_fails(self):
        self.assertFalse(self.verify('```yaml\nx: 1\n```', '.yaml', 'minimal'))
    def test_parse_is_not_requirements(self):
        self.assertTrue(self.verify('{"unrelated":1}', '.json', 'syntax'))
        self.assertFalse(self.verify('{"unrelated":', '.json', 'syntax'))

    good = '{"host":"example.internal","required_key":"rk-1"}'
    def test_requirements_passes_only_when_acceptance_keys_hold(self):
        self.assertTrue(self.verify(self.good, '.json', 'requirements', keys=['required_key']))
        self.assertTrue(self.verify(self.good, '.json', 'requirements', keys=['required_key=rk-1']))
    def test_requirements_rejects_missing_key_wrong_value_and_bad_shape(self):
        missing = '{"host":"example.internal"}'
        self.assertFalse(self.verify(missing, '.json', 'requirements', keys=['required_key']))
        self.assertFalse(self.verify(self.good, '.json', 'requirements', keys=['required_key=rk-2']))
        self.assertFalse(self.verify('[1,2]', '.json', 'requirements', keys=['required_key']))
        self.assertFalse(self.verify('{"required_key":', '.json', 'requirements', keys=['required_key']))
    def test_requirements_without_acceptance_keys_is_not_a_requirements_pass(self):
        self.assertFalse(self.verify(self.good, '.json', 'requirements'))
    def test_requirements_diagnostic_never_carries_the_body(self):
        ev = self.evidence('{"host":"secret-host-value"}', '.json', 'requirements',
                           keys=['required_key'])
        self.assertFalse(ev['ok'])
        self.assertNotIn('secret-host-value', ev['diagnostic'])
        self.assertIn('required_key', ev['diagnostic'])


if __name__ == '__main__':
    unittest.main()
