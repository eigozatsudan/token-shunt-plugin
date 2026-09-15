import copy
import json
import os
import tempfile
import unittest

from flow_checks import (edit_flow_errors, verification_errors,
                         verify_artifact, report_fields,
                         position_grep_errors)
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
    def test_grep_context_lines_are_not_matches(self):
        # rg -C prints context with a '-' separator; only ':' lines are matches,
        # so a single real match stays unique (§11.6 "short unique pattern").
        ev = self.events()
        ev[0]['message']['content'][0]['input']['-C'] = 2
        ev[1] = result('g', "3-pad\n4-def render_header():\n5:HDR_MODE = 'off'\n6-    return HDR_MODE\n7-pad")
        self.assertEqual([], self.errors(ev))
    def test_grep_several_real_matches_in_one_function_is_ambiguous(self):
        # Live 2026-09-14 shape: 'def render_header|HDR_MODE' matched three
        # adjacent real lines. Adjacency does not make the pattern unique.
        ev = self.events()
        ev[0]['message']['content'][0]['input']['pattern'] = 'def render_header|HDR_MODE'
        ev[1] = result('g', "4:def render_header():\n5:HDR_MODE = 'off'\n6:    return HDR_MODE")
        ev[2]['message']['content'][0]['input'].update(offset=3, limit=6)
        ev[3] = result('r', "3→pad\n4→def render_header():\n5→HDR_MODE = 'off'\n6→    return HDR_MODE")
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
    def test_table_explanations_and_later_prose_mentions(self):
        self.report = ('| config.json | syntax | partial (JSON valid; requirements unverified) |\n'
                       '| fence.md | minimal | **partial** (content unverified) |\n'
                       'Notes: config.json is valid JSON; fence.md uses minimal checks.')
        self.assertEqual([], self.errors(self.events()))
        self.report = self.report.replace('partial (JSON', 'complete (JSON')
        self.assertTrue(self.errors(self.events()))
    def test_table_does_not_hide_later_explicit_redeclarations(self):
        original = self.report
        for claim in ('config.json verification: requirements status: complete',
                      'config.json status: complete',
                      'config.json verification: requirements',
                      'fence.md verification: requirements status: complete',
                      'fence.md status: complete',
                      'fence.md verification: requirements'):
            with self.subTest(claim=claim):
                self.report = original + '\n' + claim
                self.assertTrue(self.errors(self.events()))
        for claim in ('config.json status: partial',
                      'config.json verification: syntax',
                      'fence.md verification: minimal status: partial',
                      'Notes: config.json is valid JSON; fence.md remains unverified.'):
            with self.subTest(claim=claim):
                self.report = original + '\n' + claim
                self.assertEqual([], self.errors(self.events()))

    def test_table_status_must_be_a_complete_word(self):
        for status in ('partially', 'not partial', 'partial_failure'):
            self.report = '| config.json | syntax | ' + status + ' |\n| fence.md | minimal | partial |'
            self.assertTrue(self.errors(self.events()))
    def batch_events(self):
        command = ('cd /tmp\necho "--- config ---"\n'
                   'python3 /eval/flow_checks.py --verify syntax config.json\n'
                   'python3 /eval/flow_checks.py --verify minimal fence.md')
        output = '\n'.join(json.dumps({'path': os.path.basename(a['path']), 'verification': a['level'], 'ok': True})
                           for a in self.artifacts)
        return [call('batch', 'Bash', {'command': command}), result('batch', output),
                {'type': 'result', 'result': self.report}]
    def test_literal_batch_resolves_paths_and_individual_results(self):
        self.assertEqual([], self.errors(self.batch_events()))
        self.artifacts[0]['ok'] = False
        ev = self.batch_events()
        block = ev[1]['message']['content'][0]
        block['content'] = block['content'].replace('"ok": true', '"ok": false', 1)
        self.assertEqual([], self.errors(ev))
    def test_batch_allows_echo_exit_status(self):
        ev = self.batch_events()
        inp = ev[0]['message']['content'][0]['input']
        inp['command'] = inp['command'].replace(
            'config.json\n', 'config.json\necho "exit: $?"\n')
        inp['command'] += '\necho "exit: $?"'
        self.assertEqual([], self.errors(ev))

    def test_cd_and_checker_with_and_separator(self):
        ev = self.batch_events()
        inp = ev[0]['message']['content'][0]['input']
        inp['command'] = inp['command'].replace('cd /tmp\necho "--- config ---"\n',
                                                'cd /tmp && ')
        self.assertEqual([], self.errors(ev))
        for prefix in ('false && ', 'cd /missing || ', 'echo cd /tmp && ',
                       'cd "$DIR" && ', 'cd /tmp; '):
            broken = copy.deepcopy(ev)
            broken[0]['message']['content'][0]['input']['command'] = inp['command'].replace('cd /tmp && ', prefix)
            self.assertTrue(self.errors(broken), prefix)

    def test_terminal_exit_echo_preserves_checker_success_and_failure(self):
        for use_cd in (False, True):
            for ok in (False, True):
                with self.subTest(cd=use_cd, ok=ok):
                    ev = self.events()
                    self.artifacts[-1]['ok'] = ok
                    for i in range(len(self.artifacts)):
                        inp = ev[2 * i]['message']['content'][0]['input']
                        if use_cd:
                            inp['command'] = inp['command'].replace(
                                'python3 /eval/flow_checks.py', 'cd /eval && python3 flow_checks.py')
                        inp['command'] += '; echo "EXIT:$?"'
                        block = ev[2 * i + 1]['message']['content'][0]
                        evidence = json.loads(block['content'])
                        evidence['ok'] = self.artifacts[i].get('ok', True)
                        block['content'] = json.dumps(evidence) + '\nEXIT:' + ('0' if evidence['ok'] else '1')
                    self.assertEqual([], self.errors(ev))
                    for bad_output in ('EXIT:0', json.dumps(evidence),
                                       json.dumps(evidence) + '\nEXIT:' + ('1' if ok else '0')):
                        broken = copy.deepcopy(ev)
                        broken[-2]['message']['content'][0]['content'] = bad_output
                        self.assertTrue(self.errors(broken), bad_output)
                    for suffix in ('; echo "EXIT:0"', '; echo "EXIT:$(true)"',
                                   '; echo "EXIT:$?"; true', ' || echo "EXIT:$?"'):
                        broken = copy.deepcopy(ev)
                        inp = broken[-3]['message']['content'][0]['input']
                        inp['command'] = inp['command'].replace('; echo "EXIT:$?"', suffix)
                        self.assertTrue(self.errors(broken), suffix)

    def test_exit_echo_uses_native_stdout_before_cwd_reset_diagnostic(self):
        ev = self.events()
        self.artifacts[-1]['ok'] = False
        for i in range(len(self.artifacts)):
            inp = ev[2 * i]['message']['content'][0]['input']
            inp['command'] = inp['command'].replace(
                'python3 /eval/flow_checks.py', 'cd /eval && python3 flow_checks.py') + '; echo "EXIT:$?"'
            reply = ev[2 * i + 1]
            block = reply['message']['content'][0]
            evidence = json.loads(block['content'])
            evidence['ok'] = self.artifacts[i].get('ok', True)
            stdout = json.dumps(evidence) + '\nEXIT:' + ('0' if evidence['ok'] else '1')
            stderr = '\nShell cwd was reset to /tmp/work/cwd'
            reply['tool_use_result'] = {'stdout': stdout, 'stderr': stderr}
            block['content'] = stdout + stderr
        self.assertEqual([], self.errors(ev))
        # A rendered label or diagnostic must not replace missing native stdout.
        ev[-2]['tool_use_result']['stdout'] = ''
        self.assertTrue(self.errors(ev))
    def test_batch_still_rejects_other_expansions(self):
        for label in ('echo "$VALUE"', 'echo "$(true)"', 'echo "`true`"',
                      'echo "${value:=changed}"', 'echo "$((1 + 1))"',
                      'echo "$?" > /tmp/result', 'echo "$?"; false',
                      'python3 /eval/flow_checks.py --verify syntax "$?"'):
            ev = self.batch_events()
            ev[0]['message']['content'][0]['input']['command'] += '\n' + label
            self.assertTrue(self.errors(ev), label)
    def test_batch_rejects_unexecuted_or_unmatched_evidence(self):
        for variant in ('echo', 'conditional', 'missing', 'reordered', 'wrong_path', 'late'):
            ev = self.batch_events()
            inp = ev[0]['message']['content'][0]['input']
            block = ev[1]['message']['content'][0]
            if variant == 'echo': inp['command'] = inp['command'].replace('python3', 'echo python3')
            if variant == 'conditional': inp['command'] = 'false && ' + inp['command']
            if variant == 'missing': block['content'] = block['content'].splitlines()[0]
            if variant == 'reordered': block['content'] = '\n'.join(reversed(block['content'].splitlines()))
            if variant == 'wrong_path': block['content'] = block['content'].replace('config.json', 'other.json')
            if variant == 'late': ev = [ev[0], ev[2], ev[1]]
            self.assertTrue(self.errors(ev), variant)
    def test_explicit_fields_allow_explanation_of_unchecked_requirements(self):
        ev = self.events()
        ev[-1]['result'] = 'config.json verification: syntax status: partial; requirements remain unverified.\nfence.md verification: minimal status: partial'
        self.assertEqual([], self.errors(ev))
    def test_prose_control_rejects_every_forbidden_listed_status(self):
        spec = {'verification_controls': [{
            'name': 'control_trunc.json', 'expected_level': 'syntax',
            'allowed_status': ['failed', 'error'], 'forbid_status': ['partial', 'complete']}]}
        for statuses in ('failed/error, partial', 'failed, complete',
                         'failed and partial', 'error or complete',
                         'failed / ERROR / partial (unverified)'):
            with self.subTest(statuses=statuses):
                report = 'control_trunc.json\nverification: syntax\nstatus: ' + statuses
                errors = verification_errors(Transcript([{'type': 'result', 'result': report}]), spec, {})
                self.assertTrue(errors)
                self.assertEqual(errors[0][0], 'verification_control')
        self.assertEqual(report_fields('verification: syntax\nstatus: failed/error, partial'),
                         ({'syntax'}, {'failed', 'error', 'partial'}))
    def test_prose_status_explanations_are_not_additional_claims(self):
        for value in ('failed/error', 'failed (partial output was rejected)',
                      'failed; partial recovery remains unverified',
                      'failed, partial recovery remains unverified',
                      'failed. A partial artifact is retained.'):
            with self.subTest(value=value):
                statuses = report_fields('verification: syntax\nstatus: ' + value)[1]
                self.assertEqual(statuses, {'failed', 'error'} if value == 'failed/error' else {'failed'})
    def test_prose_level_lists_preserve_every_claim_but_not_explanations(self):
        for value in ('syntax/requirements', 'syntax, requirements', 'syntax and requirements'):
            with self.subTest(value=value):
                self.assertEqual(report_fields('verification: ' + value)[0], {'syntax', 'requirements'})
                self.report = ('config.json verification: ' + value + ' status: partial\n'
                               'fence.md verification: minimal status: partial')
                self.assertTrue(self.errors(self.events()))
        for value in ('syntax (requirements remain unchecked)',
                      'syntax; requirements remain unchecked',
                      'syntax, requirements remain unchecked'):
            self.assertEqual(report_fields('verification: ' + value)[0], {'syntax'})
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


class PositionGrepTest(unittest.TestCase):
    """The post-hoc half of the Grep bound.

    It grades runs the hook never saw -- `direct` mode loads no plugin --
    so anything the hook refuses has to be an error here too, or the two
    halves disagree about what conforms.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.big = os.path.join(self.dir, 'big.txt')
        with open(self.big, 'w') as fh:
            fh.write('x' * 36000)

    def errors(self, **inp):
        body = {'path': self.big, 'output_mode': 'content'}
        body.update(inp)
        tr = Transcript([call('g', 'Grep', body), result('g', 'a match')])
        return position_grep_errors(tr, self.big)

    def test_a_bounded_search_with_no_window_conforms(self):
        self.assertEqual(self.errors(head_limit=5), (True, []))

    def test_every_spelling_of_the_window_is_an_error(self):
        for key in ('-A', '-B', '-C', 'context'):
            with self.subTest(key=key):
                judged, errors = self.errors(head_limit=5, **{key: 3})
                self.assertTrue(judged)
                self.assertEqual(len(errors), 1, errors)
                self.assertIn('context window', errors[0])

    def test_a_window_that_is_not_a_number_is_reported_not_raised(self):
        # A malformed tool input has to become a reasoned failure; a
        # traceback here abandons the whole case.
        judged, errors = self.errors(head_limit=5, **{'-A': 'two'})
        self.assertTrue(judged)
        self.assertEqual(len(errors), 1, errors)

