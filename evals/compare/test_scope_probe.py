"""The scope instrument, on synthetic worker transcripts.

Stage 0 of reviews/scope-prevention-design-2026-09-16.md. Two requirements
shape it. The declared set is extracted by the probe itself, because
`reader_scope` is what the measurement is judging (section 4). And a Read
that was attempted and denied still counts as an attempt: the control arm
has no denials at all, so counting only what succeeded would compare two
different things.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scope_probe as sp

AGENT = 'a1b2c3'
DENY = ('token-shunt: Read only the paths this invocation was given: '
        '/x/beta.py. This path came from another invocation; report partial '
        'and let the caller ask for it in a new one.')


def tool_use(path, tid):
    return {'type': 'assistant', 'message': {'content': [
        {'type': 'tool_use', 'id': tid, 'name': 'Read',
         'input': {'file_path': path, 'offset': 1, 'limit': 100}}]}}


def tool_result(tid, content='   1\tx = 1', is_error=False):
    return {'type': 'user', 'message': {'content': [
        {'type': 'tool_result', 'tool_use_id': tid, 'content': content,
         'is_error': is_error}]}}


class ProbeFixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.alpha = os.path.join(self.dir, 'alpha.py')
        self.beta = os.path.join(self.dir, 'beta.py')
        for path in (self.alpha, self.beta):
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write('TOKEN = 1\n')
        self.session = os.path.join(self.dir, 'sess.jsonl')
        with open(self.session, 'w', encoding='utf-8') as fh:
            fh.write(json.dumps({'type': 'user'}) + '\n')
        self.subagents = os.path.join(self.dir, 'sess', 'subagents')
        os.makedirs(self.subagents)

    def worker(self, prompt, *rows, agent=AGENT, kind='token-shunt:bulk-reader',
               stamp='2026-09-16T10:00:00Z'):
        path = os.path.join(self.subagents, 'agent-%s.jsonl' % agent)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(json.dumps({'type': 'user', 'timestamp': stamp, 'message': {
                'role': 'user', 'content': prompt}}) + '\n')
            for row in rows:
                fh.write(json.dumps(row) + '\n')
        with open(os.path.join(self.subagents, 'agent-%s.meta.json' % agent),
                  'w', encoding='utf-8') as fh:
            json.dump({'agentType': kind}, fh)
        return path


class DeclaredTests(ProbeFixture):
    def test_the_prompt_paths_are_the_declared_set(self):
        path = self.worker('Read %s and %s.' % (self.beta, self.alpha))
        got = sp.score_invocation(path)
        self.assertEqual({self.alpha, self.beta}, set(got['declared']))

    def test_a_path_that_no_longer_exists_is_still_declared(self):
        # The eval deletes its fixture tree after the run. The product's own
        # extraction drops a vanished path; the probe keeps it, so that
        # difference shows up as a disagreement rather than as a violation.
        os.remove(self.beta)
        path = self.worker('Read %s and %s.' % (self.beta, self.alpha))
        self.assertIn(self.beta, sp.score_invocation(path)['declared'])

    def test_the_product_reading_is_reported_beside_it(self):
        os.remove(self.beta)
        path = self.worker('Read %s and %s.' % (self.beta, self.alpha))
        got = sp.score_invocation(path)
        self.assertEqual([self.alpha], got['declared_product'])
        self.assertTrue(got['declared_disagrees'])

    def test_agreement_is_the_ordinary_case(self):
        path = self.worker('Read %s and %s.' % (self.beta, self.alpha))
        self.assertFalse(sp.score_invocation(path)['declared_disagrees'])


class ProseTests(ProbeFixture):
    """Stage 1 found the extraction reading prose as paths (design section 8.3)."""

    def test_a_slash_inside_a_word_is_not_a_path(self):
        # The real launch prompt says "the exact definition/value of TOKEN",
        # which the first version sliced into "/value" and called declared.
        path = self.worker('Report the definition/value of TOKEN and the '
                           'source paths/symbols that connect it.\n\n'
                           'Paths:\n%s (40 bytes)\n' % self.beta)
        self.assertEqual([self.beta], sp.score_invocation(path)['declared'])

    def test_a_path_in_brackets_is_still_a_path(self):
        path = self.worker('Compare (%s) with `%s`.' % (self.beta, self.alpha))
        self.assertEqual({self.alpha, self.beta},
                         set(sp.score_invocation(path)['declared']))

    def test_a_bare_word_with_no_slash_is_not_a_path(self):
        path = self.worker('Read beta.py only.')
        self.assertEqual([], sp.score_invocation(path)['declared'])


class OpportunityTests(ProbeFixture):
    """A re-read is only possible where an earlier path was left out."""

    def test_the_first_invocation_is_never_an_opportunity(self):
        self.worker('Read %s.' % self.alpha, agent='w1')
        got = sp.score_session(self.session)
        self.assertFalse(got['invocations'][0]['opportunity'])
        self.assertEqual(0, got['opportunities'])

    def test_a_later_invocation_that_drops_an_earlier_path_is_one(self):
        self.worker('Read %s.' % self.alpha, agent='w1')
        self.worker('Read %s.' % self.beta, agent='w2')
        got = sp.score_session(self.session)
        self.assertEqual([False, True],
                         [i['opportunity'] for i in got['invocations']])
        self.assertEqual(1, got['opportunities'])

    def test_a_later_invocation_that_keeps_them_all_is_not_one(self):
        # The parent handed the earlier path over again, so nothing the
        # worker could read here would be out of scope.
        self.worker('Read %s.' % self.alpha, agent='w1')
        self.worker('Read %s and %s.' % (self.alpha, self.beta), agent='w2')
        got = sp.score_session(self.session)
        self.assertEqual(0, got['opportunities'])

    def test_order_comes_from_the_timestamps_not_the_agent_id(self):
        self.worker('Read %s.' % self.beta, agent='zzz', stamp='2026-09-16T10:00:00Z')
        self.worker('Read %s.' % self.alpha, agent='aaa', stamp='2026-09-16T09:00:00Z')
        got = sp.score_session(self.session)
        self.assertEqual(['aaa', 'zzz'], [i['agent_id'] for i in got['invocations']])

    def test_the_attempt_is_counted_against_the_opportunities(self):
        self.worker('Read %s.' % self.alpha, agent='w1')
        self.worker('Read %s.' % self.beta, tool_use(self.alpha, 't1'),
                    tool_result('t1'), agent='w2')
        got = sp.score_session(self.session)
        self.assertEqual(1, got['opportunities'])
        self.assertEqual(1, got['attempted'])
        self.assertEqual(1, got['succeeded'])


class AttemptTests(ProbeFixture):
    def test_a_read_outside_the_declared_set_is_an_attempt(self):
        path = self.worker('Read %s.' % self.beta,
                           tool_use(self.alpha, 't1'), tool_result('t1'))
        got = sp.score_invocation(path)
        self.assertEqual([self.alpha], got['out_of_scope'])
        self.assertEqual([self.alpha], got['succeeded'])
        self.assertEqual([], got['denied_scope'])

    def test_a_denied_attempt_still_counts_as_an_attempt(self):
        # The control arm produces no denials at all; counting only what
        # succeeded would compare two different quantities.
        path = self.worker('Read %s.' % self.beta,
                           tool_use(self.alpha, 't1'),
                           tool_result('t1', DENY, is_error=True))
        got = sp.score_invocation(path)
        self.assertEqual([self.alpha], got['out_of_scope'])
        self.assertEqual([], got['succeeded'])
        self.assertEqual([self.alpha], got['denied_scope'])

    def test_a_declared_path_is_not_out_of_scope(self):
        path = self.worker('Read %s.' % self.beta,
                           tool_use(self.beta, 't1'), tool_result('t1'))
        got = sp.score_invocation(path)
        self.assertEqual([], got['out_of_scope'])
        self.assertEqual([self.beta], got['succeeded'])

    def test_a_declared_path_denied_for_scope_is_a_false_refusal(self):
        # A4: expected zero, and the item is worthless if it cannot be seen.
        path = self.worker('Read %s.' % self.beta,
                           tool_use(self.beta, 't1'),
                           tool_result('t1', DENY, is_error=True))
        got = sp.score_invocation(path)
        self.assertEqual([self.beta], got['false_refusals'])

    def test_another_hooks_denial_is_not_a_scope_denial(self):
        path = self.worker('Read %s.' % self.beta,
                           tool_use(self.alpha, 't1'),
                           tool_result('t1', 'token-shunt: At most three '
                                       'paths per invocation.', is_error=True))
        got = sp.score_invocation(path)
        self.assertEqual([self.alpha], got['out_of_scope'])
        self.assertEqual([], got['denied_scope'])
        self.assertEqual([], got['succeeded'])

    def test_a_read_with_no_result_is_neither_denied_nor_succeeded(self):
        path = self.worker('Read %s.' % self.beta, tool_use(self.alpha, 't1'))
        got = sp.score_invocation(path)
        self.assertEqual([self.alpha], got['out_of_scope'])
        self.assertEqual([], got['succeeded'])
        self.assertEqual([], got['denied_scope'])

    def test_a_path_is_counted_once_however_often_it_is_tried(self):
        path = self.worker('Read %s.' % self.beta,
                           tool_use(self.alpha, 't1'),
                           tool_result('t1', DENY, is_error=True),
                           tool_use(self.alpha, 't2'),
                           tool_result('t2', DENY, is_error=True))
        got = sp.score_invocation(path)
        self.assertEqual([self.alpha], got['out_of_scope'])
        self.assertEqual(2, got['read_calls'])


class SessionTests(ProbeFixture):
    def test_only_bulk_reader_invocations_are_scored(self):
        self.worker('Read %s.' % self.beta, agent='w1')
        self.worker('Write something.', agent='w2',
                    kind='token-shunt:code-writer')
        got = sp.score_session(self.session)
        self.assertEqual(['w1'], [i['agent_id'] for i in got['invocations']])

    def test_a_session_with_no_subagents_scores_nothing(self):
        got = sp.score_session(os.path.join(self.dir, 'other.jsonl'))
        self.assertEqual([], got['invocations'])

    def test_the_totals_count_invocations_not_runs(self):
        self.worker('Read %s.' % self.beta, tool_use(self.alpha, 't1'),
                    tool_result('t1'), agent='w1')
        self.worker('Read %s.' % self.beta, tool_use(self.beta, 't2'),
                    tool_result('t2'), agent='w2')
        got = sp.score_session(self.session)
        self.assertEqual(2, got['invocations_total'])
        self.assertEqual(1, got['attempted'])
        self.assertEqual(1, got['succeeded'])
        self.assertEqual(0, got['denied'])
        self.assertEqual(0, got['false_refusals'])


if __name__ == '__main__':
    unittest.main()
