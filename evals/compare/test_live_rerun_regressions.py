"""Controls for the 2026-09-14 live rerun's evaluator false positives."""
import json
import unittest
from unittest.mock import patch

from judge import Transcript, foreign_hooks, ts_deny_payload
from routing_checks import check_reader_reads, reader_attempt_metrics, reader_contract_denial
from test_routing_checks import split_read_transcript
import test_unreadable_and_model


class HookIsolationTests(unittest.TestCase):
    def test_post_read_hooks_only_in_delegate_and_with_owned_output(self):
        # PostToolUse:Bash and PreToolUse:Grep became ours when
        # check-grep-bounds was registered on them
        # (reviews/grep-hook-implementation-2026-09-15.md).
        for name in ('PostToolUse:Read', 'PostToolUseFailure:Read',
                     'PostToolUse:Bash', 'PreToolUse:Grep',
                     '/plugin/hooks/check-reader-contract'):
            for payload in ('', 'token-shunt: diagnostic'):
                tr = Transcript([{'type': 'system', 'subtype': 'hook_response',
                                  'hook_name': name, 'stdout': payload}])
                self.assertEqual([], foreign_hooks(tr))
                self.assertTrue(foreign_hooks(tr, plugin_loaded=False))
        for name, payload in (('PostToolUse:Edit', ''),
                              ('PreToolUse:Write', ''),
                              ('PostToolUse:Read', 'foreign plugin output')):
            tr = Transcript([{'type': 'system', 'subtype': 'hook_response',
                              'hook_name': name, 'stdout': payload}])
            self.assertTrue(foreign_hooks(tr))

    def test_post_hook_is_not_pre_execution_denial_evidence(self):
        for name in ('PostToolUse:Read', 'PostToolUseFailure:Read'):
            event = {'type': 'system', 'subtype': 'hook_response', 'hook_name': name,
                     'stdout': json.dumps({'hookSpecificOutput': {
                         'permissionDecision': 'deny',
                         'permissionDecisionReason': 'token-shunt: /token-shunt:bulk-reader'}})}
            self.assertIsNone(ts_deny_payload(event))


class ReaderDenialTests(unittest.TestCase):
    def denied(self, tr, index, reason):
        result = tr.result_of('a0r' + str(index))
        result.update(is_error=True, text='token-shunt: ' + reason)

    def check(self, tr):
        with patch('routing_checks._line_count', return_value=519):
            return check_reader_reads(tr, {'child_reads_once': ['/a.py']}, tr.agent_uses())

    def test_live_jump_and_wrong_half_do_not_advance_cursor(self):
        tr = split_read_transcript([(1,350,False), (351,169,True),
                                    (400,119,True), (351,50,True), (351,84,False)])
        tr.result_of('a0r0')['text'] = '\n'.join(f'{i}\tsource' for i in range(1,351))
        self.denied(tr, 2, 'Read must start at offset=351 with a positive limit.')
        self.denied(tr, 3, 'Retry at offset=351 with limit=84 (floor half).')
        self.assertEqual([], self.check(tr))
        record = reader_attempt_metrics(tr, tr.agent_uses())[0]
        self.assertEqual((5, 5, 2), (record['attempts'], record['budget_consumed'],
                                    len(record['blocked_attempts'])))
        # Less than the floor half is legal: it can only read fewer lines.
        tr.tool_uses[-1]['input']['limit'] = 50
        self.assertEqual([], self.check(tr))
        # More than it is still a wrong half, even after an earlier denial.
        tr.tool_uses[-1]['input']['limit'] = 100
        self.assertTrue(self.check(tr))

    def test_both_retry_denial_wordings_are_recognized(self):
        # Transcripts saved before the limit became an upper bound carry the
        # older sentence; re-judging them must still see a contract denial.
        for reason in ('Retry at offset=351 with limit=84 (floor half).',
                       'Retry at offset=351 with limit=84 (floor half) or less.'):
            tr = split_read_transcript([(351, 84, True)])
            self.denied(tr, 0, reason)
            self.assertIsNotNone(reader_contract_denial(tr, tr.tool_uses[-1]))

    def test_budget_denials_and_outside_paths_are_not_execution(self):
        tr = split_read_transcript([(1,None,False)] + [(1,1,True)] * 6)
        for i in range(1,6):
            self.denied(tr, i, 'No further Read is supported for this path; report its unread range partial.')
        self.denied(tr, 6, 'Read budget exhausted; stop partial with stop_reason: budget_exhausted.')
        tr.tool_uses[-1]['input']['file_path'] = '/outside.py'
        self.assertEqual([], self.check(tr))
        self.assertEqual(6, reader_attempt_metrics(tr, tr.agent_uses())[0]['budget_consumed'])
        tr.result_of('a0r6').update(is_error=False, text='source')
        self.assertTrue(self.check(tr))

    SCOPE_DENIAL = ('Read only the paths this invocation was given: /a.py. '
                    'This path came from another invocation; report partial '
                    'and let the caller ask for it in a new one.')

    def test_a_scope_denial_is_a_contract_denial(self):
        # The judge knew every other refusal this hook issues but not this one,
        # so a Read the hook stopped counted as a Read that happened
        # (reviews/scope-control-2026-09-16.md section 5).
        tr = split_read_transcript([(1, 1, True)])
        self.denied(tr, 0, self.SCOPE_DENIAL)
        self.assertIsNotNone(reader_contract_denial(tr, tr.tool_uses[-1]))

    def test_a_scope_denied_path_is_not_an_extra_read(self):
        tr = split_read_transcript([(1, None, False), (1, 1, True)])
        self.denied(tr, 1, self.SCOPE_DENIAL)
        tr.tool_uses[-1]['input']['file_path'] = '/outside.py'
        self.assertEqual([], self.check(tr))

    def test_a_scope_denied_attempt_is_still_visible_as_blocked(self):
        # Not failing the run must not make the attempt disappear: it is the
        # numerator of every measurement of this hook.
        tr = split_read_transcript([(1, None, False), (1, 1, True)])
        self.denied(tr, 1, self.SCOPE_DENIAL)
        tr.tool_uses[-1]['input']['file_path'] = '/outside.py'
        record = reader_attempt_metrics(tr, tr.agent_uses())[0]
        self.assertEqual(2, record['attempts'])
        self.assertEqual(1, len(record['blocked_attempts']))
        self.assertIn('Read only the paths this invocation was given',
                      record['blocked_attempts'][0]['reason'])

    def test_an_out_of_scope_read_that_returned_content_still_fails(self):
        # The control arm's reads went through; those must stay failures.
        tr = split_read_transcript([(1, None, False), (1, 1, False)])
        tr.tool_uses[-1]['input']['file_path'] = '/outside.py'
        tr.result_of('a0r1').update(is_error=False, text='1\tsource')
        self.assertTrue(any(e[0] == 'child_extra_read' for e in self.check(tr)))

    def test_another_hooks_refusal_of_that_path_is_not_this_one(self):
        tr = split_read_transcript([(1, None, False), (1, 1, True)])
        self.denied(tr, 1, 'Read only the paths this invocation was given.')
        tr.tool_uses[-1]['input']['file_path'] = '/outside.py'
        self.assertIsNone(reader_contract_denial(tr, tr.tool_uses[-1]))

    def test_denial_requires_exact_error_identity_and_order(self):
        tr = split_read_transcript([(1,1,True)])
        self.denied(tr, 0, 'Read requires an absolute file_path.')
        call = tr.tool_uses[-1]
        result = tr.result_of(call['id'])
        self.assertIsNotNone(reader_contract_denial(tr, call))
        original = dict(result)
        for change in ({'is_error': False}, {'parent_tool_use_id': 'other'},
                       {'position': (-1,-1)}, {'text': 'token-shunt: unknown error'},
                       {'text': original['text'] + '\n1\tpayload'}):
            result.update(change)
            self.assertIsNone(reader_contract_denial(tr, call))
            result.update(original)
        self.assertTrue(self.check(tr))  # A denial alone supplies no coverage.

    def test_denied_attempts_still_consume_the_six_attempt_budget(self):
        tr = split_read_transcript([(2,1,True)] * 6 + [(1,None,False)])
        for i in range(6):
            self.denied(tr, i, 'Read must start at offset=1 with a positive limit.')
        errors = self.check(tr)
        self.assertEqual(1, len(errors))
        self.assertIn('stay within 6 Reads', errors[0][1])


class AbsentConfirmedTests(unittest.TestCase):
    def test_none_is_not_a_fact_but_suffix_claims_remain_rejected(self):
        check = test_unreadable_and_model.UnreadableTests().check
        base = ('unconfirmed: /a.py — TOKEN; unread line 1\n'
                'status: partial\nstop_reason: unreadable_line')
        for label in ('confirmed:', 'confirmed: none',
                      'confirmed: none — unable to retrieve payload_sha value.'):
            report = label + '\n' + base
            self.assertTrue(check([(1,1,True)], final=report, child=report), label)
        for label in ('confirmed: none — TOKEN is abc', 'confirmed: /a.py — TOKEN: abc',
                      'confirmed: none\nTOKEN is abc',
                      'confirmed: none — unable to retrieve payload_sha value. TOKEN=abc'):
            report = label + '\n' + base
            self.assertFalse(check([(1,1,True)], final=report), label)
            self.assertFalse(check([(1,1,True)], child=report), label)


if __name__ == '__main__':
    unittest.main()
