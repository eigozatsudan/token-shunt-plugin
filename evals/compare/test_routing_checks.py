import unittest
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
        events.append({'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':aid,'content':'partial: missing evidence','resolvedModel':'claude-'+model}]}})
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

    def test_duplicate_and_outside_invocation_reads(self):
        self.assertTrue(self.check([('haiku',['/a.py','/a.py'],'',{})]))
        tr=transcript([('haiku',['/a.py'],'',{})]); tr.tool_uses[-1]['input']['file_path']='/other.py'
        self.assertTrue(check_reader_reads(tr,{'child_reads_once':['/a.py']},tr.agent_uses()))



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
        if is_error: result['is_error']=True
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
        return check_reader_reads(tr,{'child_reads_once':['/a.py']},tr.agent_uses())

    def test_rejected_whole_read_then_partition_is_allowed(self):
        self.assertEqual([], self.check([(None,None,True),(1,200,False),(201,200,False),(401,119,False)]))

    def test_overlapping_ranges_still_fail(self):
        self.assertTrue(self.check([(None,None,True),(175,344,False),(400,119,False)]))
        self.assertTrue(self.check([(1,200,False),(200,10,False)]))

    def test_open_ended_range_overlaps_anything_after_it(self):
        self.assertTrue(self.check([(175,None,False),(400,10,False)]))
        self.assertEqual([], self.check([(1,100,False),(101,None,False)]))

    def test_only_failed_reads_is_not_coverage(self):
        self.assertTrue(self.check([(None,None,True)]))

    def test_read_budget_is_bounded(self):
        self.assertEqual([], self.check([(None,None,True)]+[(1+100*i,100,False) for i in range(5)]))
        self.assertTrue(self.check([(None,None,True)]+[(1+100*i,100,False) for i in range(6)]))


if __name__=='__main__':
    unittest.main()
