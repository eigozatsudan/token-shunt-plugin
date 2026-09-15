import unittest
import tempfile
from pathlib import Path
from judge import Transcript, agent_resolved_models
from routing_checks import check_reader_reads, check_routing, _paths


def transcript(attempts, final='done'):
    events=[]
    for i, (model, paths, suffix, options) in enumerate(attempts):
        aid='a'+str(i)
        inp={'subagent_type':'token-shunt:bulk-reader','model':model,'prompt':' '.join(paths)+' --question "What is TOKEN?" '+suffix}
        inp.update(options)
        events.append({'type':'assistant','message':{'id':aid,'content':[{'type':'tool_use','id':aid,'name':'Agent','input':inp}]}})
        for j,p in enumerate(paths):
            rid=aid+'r'+str(j)
            events.extend([{'type':'assistant','parent_tool_use_id':aid,'message':{'model':'claude-'+model,'content':[{'type':'tool_use','id':rid,'name':'Read','input':{'file_path':p}}]}}, {'type':'user','parent_tool_use_id':aid,'message':{'content':[{'type':'tool_result','tool_use_id':rid,'content':'source'}]}}])
        events.append({'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':aid,'content':'status: partial\nstop_reason: missing evidence','resolvedModel':'claude-'+model}]}})
    events.append({'type':'result','result':final})
    return Transcript(events)


class RoutingTests(unittest.TestCase):
    def check(self, attempts, mode='auto', exp=None, final='done'):
        tr=transcript(attempts,final)
        exp=exp or {'retry_policy':True,'child_reads_once':['/a.py']}
        agents=tr.agent_uses()
        return check_routing(tr,{},exp,mode,agents,agent_resolved_models)+check_reader_reads(tr,exp,agents)

    def test_quoted_paths_and_slash_commands(self):
        self.assertEqual({"/a b.py", "/c.py"}, _paths('/token-shunt:bulk-reader "/a b.py" /c.py.'))

    def test_initial_and_authorized_retry(self):
        self.assertEqual([], self.check([('haiku',['/a.py'],'',{})]))
        self.assertEqual([], self.check([('haiku',['/a.py'],'',{}),('sonnet',['/a.py'],'missing evidence: TOKEN location absent',{})]))

    def test_wrong_initial_models_and_resume(self):
        for model in ['sonnet','opus']:
            self.assertTrue(self.check([(model,['/a.py'],'',{})]))
        self.assertTrue(self.check([('haiku',['/a.py'],'',{'resume':'old'})]))

    def test_retry_reason_path_and_count(self):
        initial=('haiku',['/a.py'],'',{})
        for retry in [('sonnet',['/a.py'],'low confidence',{}),('sonnet',['/b.py'],'missing evidence',{}),('haiku',['/a.py'],'missing evidence',{})]:
            self.assertTrue(self.check([initial,retry]))
        retry=('sonnet',['/a.py'],'missing evidence',{})
        self.assertTrue(self.check([initial,retry,retry]))
        self.assertTrue(self.check([('sonnet',['/a.py'],'',{}),retry],mode='sonnet'))

    def test_retry_requires_prior_result_and_original_question(self):
        attempts=[('haiku',['/a.py'],'',{}),('sonnet',['/a.py'],'missing evidence',{})]
        tr=transcript(attempts)
        agents=tr.agent_uses()
        agents[1]['input']['prompt']='/a.py --question "Unrelated?" missing evidence'
        self.assertTrue(check_routing(tr,{}, {'retry_policy':True},'auto',agents,agent_resolved_models))
        tr=transcript(attempts)
        result=next(e for e in tr.events if e.get('type')=='user' and e.get('parent_tool_use_id') is None)
        tr.events.remove(result)
        tr.events.append(result)
        self.assertTrue(check_routing(tr,{}, {'retry_policy':True},'auto',tr.agent_uses(),agent_resolved_models))

    def test_requested_and_every_resolved_model(self):
        tr=transcript([('haiku',['/a.py'],'',{})]); agents=tr.agent_uses()
        for models in [[],['claude-sonnet'],['claude-haiku','claude-opus'],['fake-haiku']]:
            self.assertTrue(check_routing(tr,{}, {'retry_policy':True},'auto',agents,lambda *_:models))
        agents[0]['input'].pop('model')
        self.assertTrue(check_routing(tr,{}, {'retry_policy':True},'auto',agents,agent_resolved_models))

    def test_boundary_reread_once_per_invocation(self):
        exp={'batch_invocation':[['/a.py','/x.py','/y.py'],['/b.py']], 'child_reads_once':['/a.py','/x.py','/y.py','/b.py'],'ambiguous_batch':True}
        initial=[('haiku',['/a.py','/x.py','/y.py'],'',{}),('haiku',['/b.py'],'',{})]
        final='TOKEN relationship unconfirmed; status: partial'
        self.assertEqual([],self.check(initial,exp=exp,final=final))
        self.assertEqual([],self.check(initial,exp=exp,final='confirmed: alpha.py TOKEN is ALPHA-TOKEN\n'+final))
        boundary=('haiku',['/a.py','/b.py'],'boundary confirmation',{})
        self.assertEqual([],self.check(initial+[boundary],exp=exp,final=final))
        self.assertTrue(self.check(initial+[boundary,boundary],exp=exp,final=final))
        self.assertTrue(self.check(initial,exp=exp,final='confirmed: TOKEN alpha.py refers to beta.py'))
        absence = 'confirmed: /notifiable.rb — No TOKEN definitions, references, or imports found'
        self.assertEqual([], self.check(initial, exp=exp, final=absence + '\n' + final))
        for claim in (absence + '; TOKEN alpha.py refers to beta.py',
                      'confirmed: TOKEN alpha.py refers to beta.py; no imports found',
                      'confirmed: /alpha.py — TOKEN references beta.py'):
            self.assertTrue(self.check(initial, exp=exp, final=claim + '\n' + final), claim)

    def test_duplicate_and_outside_invocation_reads(self):
        self.assertTrue(self.check([('haiku',['/a.py','/a.py'],'',{})]))
        tr=transcript([('haiku',['/a.py'],'',{})]); tr.tool_uses[-1]['input']['file_path']='/other.py'
        self.assertTrue(check_reader_reads(tr,{'child_reads_once':['/a.py']},tr.agent_uses()))

    def test_absence_coverage_note_and_paraphrase_with_routing_enabled(self):
        exp = {'ambiguous_batch': True, 'retry_policy': True,
               'batch_invocation': [['/a'], ['/b']]}
        ending = '\nunconfirmed: TOKEN relationship\nstatus: partial'
        def errors(claim):
            tr = Transcript([{'type': 'result', 'result': claim + ending}])
            return check_routing(tr, {}, exp, 'auto', [], agent_resolved_models)
        for absence in (
                'confirmed: /notifiable.rb — No TOKEN definitions, references, or imports found (entire 7-line file read)',
                'confirmed: /notifiable.rb — no TOKEN reference present in this file'):
            self.assertEqual([], errors(absence))
            for claim in (absence + '; TOKEN refers to beta.py',
                          absence + ' (TOKEN references beta.py)',
                          absence.replace('No TOKEN', 'TOKEN').replace('no TOKEN', 'TOKEN')):
                self.assertIn('batch_evidence', [name for name, _ in errors(claim)], claim)



class AmbiguityResolutionTests(unittest.TestCase):
    """Design section 925 and the case prompt both allow two endings.

    "境界確認で曖昧さを解消するか unconfirmed / partial" -- the judge only
    implemented the second, so an answer that resolved the collision on
    evidence failed. 14 of 16 archived runs of reader-batch-ambiguous fail
    this check, and the ones I read are substantively correct
    (reviews/batch-evidence-defect-2026-09-15.md).
    """

    ALPHA = '/fix/gen/collide/alpha.py'
    BETA = '/fix/gen/collide/beta.py'

    def exp(self, **over):
        exp = {'ambiguous_batch': {'paths': [self.ALPHA, self.BETA]},
               'retry_policy': True,
               'batch_invocation': [[self.ALPHA, '/fix/user.rb'], [self.BETA]]}
        exp.update(over)
        return exp

    def check(self, final, agents=(), exp=None):
        events = [{'type': 'result', 'result': final}]
        tr = Transcript(events)
        return [n for n, _ in check_routing(tr, {}, exp or self.exp(), 'auto',
                                            list(agents), agent_resolved_models)]

    def resolved_answer(self):
        return ('**Answer: No.** They are independent constants.\n'
                'confirmed: %s — TOKEN: string literal, no import or '
                'reference to any module named beta/beta.py\n'
                'confirmed: %s — TOKEN: string literal, no import or '
                'reference to any module named alpha/alpha.py\n'
                'status: complete' % (self.ALPHA, self.BETA))

    def test_an_answer_resolved_on_evidence_no_longer_needs_partial(self):
        self.assertEqual([], self.check(self.resolved_answer()))

    def test_the_unconfirmed_partial_ending_still_passes(self):
        final = ('unconfirmed: TOKEN relationship between alpha and beta\n'
                 'status: partial')
        self.assertEqual([], self.check(final))

    def test_an_answer_that_is_neither_still_fails(self):
        # Silent on both files: no absence evidence and no demotion.
        final = '**Answer: No.** They look unrelated to me.\nstatus: complete'
        self.assertIn('batch_evidence', self.check(final))

    def test_covering_only_one_of_the_two_files_is_not_resolution(self):
        final = ('confirmed: %s — TOKEN: no import or reference to beta\n'
                 'status: complete' % self.ALPHA)
        self.assertIn('batch_evidence', self.check(final))

    def test_a_claimed_relationship_fails_however_it_is_worded(self):
        for claim in ('confirmed: %s — TOKEN refers to the TOKEN in beta.py',
                      'confirmed: %s — TOKEN references beta.py',
                      'confirmed: %s — TOKEN depends on beta.py'):
            with self.subTest(claim=claim):
                final = self.resolved_answer() + '\n' + (claim % self.ALPHA)
                self.assertIn('batch_evidence', self.check(final))

    def test_a_mixed_line_is_not_excused_by_its_negated_half(self):
        # The old comment's warning, kept: "no import, but X refers to Y"
        # carries a positive claim in its second clause.
        final = (self.resolved_answer() + '\nconfirmed: %s — no import, but '
                 'TOKEN refers to beta.TOKEN' % self.ALPHA)
        self.assertIn('batch_evidence', self.check(final))

    def test_negated_wordings_outside_the_old_template_are_absences(self):
        for line in (
                'confirmed: %s — TOKEN: string literal, no import or reference '
                'to any module named beta/beta.py',
                'confirmed: %s — this file does not refer to beta.py at all',
                'confirmed: %s — TOKEN is defined locally, with no reference '
                'to beta'):
            with self.subTest(line=line):
                final = ('%s\nconfirmed: %s — no reference to alpha\n'
                         'status: complete'
                         % (line % self.ALPHA, self.BETA))
                self.assertEqual([], self.check(final))

    def test_a_boundary_confirmation_carrying_both_files_also_resolves(self):
        # The other branch the prompt offers: one fresh Agent with both.
        agent = {'id': 'b1', 'name': 'Agent', 'position': (9, 0),
                 'input': {'subagent_type': 'token-shunt:bulk-reader',
                           'model': 'haiku',
                           'prompt': '%s %s --question "same TOKEN?"'
                                     % (self.ALPHA, self.BETA)}}
        final = '**Answer: No.** Confirmed by the boundary check.\nstatus: complete'
        self.assertNotIn('batch_evidence', self.check(final, agents=[agent]))

    def test_a_bare_true_keeps_the_strict_rule(self):
        # Cases that do not name the colliding paths cannot be resolved by
        # evidence here, so they keep demanding unconfirmed/partial.
        exp = self.exp(ambiguous_batch=True)
        self.assertIn('batch_evidence',
                      self.check(self.resolved_answer(), exp=exp))


def split_read_transcript(reads):
    """One bulk-reader invocation whose child issues `reads`:
    (offset, limit, is_error) tuples against /a.py."""
    aid='a0'
    events=[{'type':'assistant','message':{'id':aid,'content':[{'type':'tool_use','id':aid,'name':'Agent',
        'input':{'subagent_type':'token-shunt:bulk-reader','model':'haiku',
                 'prompt':'/a.py (519 lines) --question "What is TOKEN?"'}}]}}]
    for i,(offset,limit,is_error) in enumerate(reads):
        rid=aid+'r'+str(i)
        inp={'file_path':'/a.py'}
        if offset: inp['offset']=offset
        if limit: inp['limit']=limit
        result={'type':'tool_result','tool_use_id':rid,'content':'source'}
        if is_error:
            result['is_error']=True
            result['content']='File content (47078 tokens) exceeds maximum allowed tokens (25000).'
        events.extend([
            {'type':'assistant','parent_tool_use_id':aid,'message':{'model':'claude-haiku','content':[{'type':'tool_use','id':rid,'name':'Read','input':inp}]}},
            {'type':'user','parent_tool_use_id':aid,'message':{'content':[result]}}])
    events.append({'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':aid,'content':'done'}]}})
    events.append({'type':'result','result':'done'})
    return Transcript(events)


class SplitReadTests(unittest.TestCase):
    """The Read tool refuses whole files in exactly the size class we delegate,
    so the child may partition a path into consecutive non-overlapping ranges."""

    def check(self, reads):
        tr=split_read_transcript(reads)
        # Native Read responses establish their actual endpoint with line labels.
        for i, (offset, limit, is_error) in enumerate(reads):
            if not is_error:
                start = offset or 1
                end = start + limit - 1 if limit else 519
                tr.result_of('a0r' + str(i))['text'] = '\n'.join(
                    '%s\tsource' % n for n in range(start, end + 1))
        return check_reader_reads(tr,{'child_reads_once':['/a.py']},tr.agent_uses())

    def test_rejected_whole_read_then_partition_is_allowed(self):
        self.assertEqual([], self.check([(None,None,True),(1,200,False),(201,200,False),(401,119,False)]))

    def test_overlapping_ranges_still_fail(self):
        self.assertTrue(self.check([(None,None,True),(175,344,False),(400,119,False)]))
        self.assertTrue(self.check([(1,200,False),(200,10,False)]))

    def test_open_ended_range_overlaps_anything_after_it(self):
        self.assertTrue(self.check([(175,None,False),(400,10,False)]))
        self.assertEqual([], self.check([(None,None,True),(1,100,False),(101,None,False)]))

    def test_partition_requires_native_refusal(self):
        self.assertTrue(self.check([(1,100,False),(101,100,False)]))
        self.assertEqual([], self.check([(1,100,True),(1,50,False)]))
        tr = split_read_transcript([(None,None,True),(1,100,False)])
        tr.result_of('a0r0')['text'] = 'Permission denied'
        self.assertTrue(check_reader_reads(tr, {'child_reads_once':['/a.py']}, tr.agent_uses()))

    def test_bounded_refusal_halves_at_the_same_cursor(self):
        self.assertEqual([], self.check([(101,101,True),(101,50,True),(101,25,False)]))
        self.assertEqual([], self.check([(None,None,True),(1,100,False),
                                        (101,101,True),(101,50,False)]))
        for retry in [(102,50,False), (101,100,False), (101,49,False),
                      (101,None,False)]:
            self.assertTrue(self.check([(101,100,True), retry]))

    def test_refused_jump_is_checked_even_when_next_success_is_consecutive(self):
        for refused_start in [1, 400]:
            self.assertTrue(self.check([(None,None,True),(1,100,False),
                                        (refused_start,100,True),(101,50,False)]))
        self.assertTrue(self.check([(None,None,True),(1,100,False),
                                    (400,100,True),(101,100,False)]))

    def test_refusal_at_limit_one_must_stop(self):
        self.assertEqual([], self.check([(None,None,True),(1,100,False),(101,1,True)]))
        self.assertTrue(self.check([(None,None,True),(1,100,False),
                                    (101,1,True),(101,1,False)]))

    def test_partition_is_consecutive_and_in_order(self):
        for ranges in [[(1,10,False),(101,10,False)],
                       [(101,10,False),(1,10,False)], [(2,10,False)]]:
            self.assertTrue(self.check([(None,None,True)] + ranges))

    def test_answer_can_stop_before_eof_and_single_targeted_read_is_allowed(self):
        self.assertEqual([], self.check([(None,None,True),(1,10,False)]))
        self.assertEqual([], self.check([(101,10,False)]))

    def test_only_failed_reads_is_not_coverage(self):
        self.assertTrue(self.check([(None,None,True)]))

    def test_read_budget_is_bounded(self):
        self.assertEqual([], self.check([(None,None,True)]+[(1+100*i,100,False) for i in range(5)]))
        self.assertTrue(self.check([(None,None,True)]+[(1+100*i,100,False) for i in range(6)]))


class SilentTruncationTests(unittest.TestCase):
    def check(self, reads, numbered, exists=True):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'source.py')
            if exists:
                Path(path).write_text('source\n' * 10)
            tr = split_read_transcript(reads)
            tr.agent_uses()[0]['input']['prompt'] = path
            for index, call in enumerate(tr.child_tool_uses('a0')):
                call['input']['file_path'] = path
                if numbered[index] is not None:
                    tr.result_of(call['id'])['text'] = numbered[index]
            return check_reader_reads(tr, {'child_reads_once': [path]}, tr.agent_uses())

    def lines(self, start, end):
        return '\n'.join('%s\tsource' % n for n in range(start, end + 1))

    def test_silent_whole_and_bounded_truncation_continue_at_returned_end(self):
        self.assertEqual([], self.check(
            [(None,None,False),(4,7,False),(7,4,False)],
            [self.lines(1,3), self.lines(4,6), self.lines(7,10)]))

    def test_gap_overlap_and_eof_reread_fail(self):
        for offset in [3, 5, 10]:
            self.assertTrue(self.check([(None,None,False),(offset,1,False)],
                [self.lines(1,3), self.lines(offset,offset)]))
        self.assertTrue(self.check([(None,None,False),(11,1,False)],
            [self.lines(1,10), self.lines(11,11)]))

    def test_silent_truncation_then_refusal_keeps_the_returned_cursor(self):
        self.assertEqual([], self.check(
            [(None,None,False),(4,6,True),(4,3,False)],
            [self.lines(1,3), None, self.lines(4,6)]))
        self.assertTrue(self.check(
            [(None,None,False),(7,6,True),(4,3,False)],
            [self.lines(1,3), None, self.lines(4,6)]))

    def test_unknown_or_malformed_line_evidence_does_not_authorize_continuation(self):
        for text in ['source', '1\tsource\n3\tsource', '2\tsource',
                     '1\tsource\n1\tsource']:
            self.assertTrue(self.check([(None,None,False),(4,7,False)],
                [text, self.lines(4,10)]))
        self.assertTrue(self.check([(None,None,False),(4,7,False)],
            [self.lines(1,3), self.lines(4,10)], exists=False))

    def test_refusal_does_not_authorize_cursor_from_requested_limit(self):
        for text in ['source', '1\tsource\n3\tsource', '2\tsource',
                     '1\tsource\n1\tsource']:
            with self.subTest(text=text):
                self.assertTrue(self.check(
                    [(None, None, True), (1, 3, False), (4, 7, False)],
                    [None, text, self.lines(4, 10)]))
                # A worker may stop after obtaining enough information.
                self.assertEqual([], self.check(
                    [(None, None, True), (1, 3, False)], [None, text]))
        self.assertEqual([], self.check(
            [(None, None, True), (1, 5, False), (4, 7, False)],
            [None, self.lines(1, 3), self.lines(4, 10)]))

    def test_silent_continuation_preserves_six_read_budget(self):
        for count in [6, 7]:
            errors = self.check([(None,None,False)] + [(n,1,False) for n in range(2,count+1)],
                                [self.lines(n,n) for n in range(1,count+1)])
            self.assertEqual(bool(errors), count > 6)


if __name__=='__main__':
    unittest.main()
