#!/usr/bin/env python3
"""Offline counterexamples for the g review; emits observations, edits only /tmp.
Run with python3 -B <script> [repository-or-snapshot-root].
"""
import json,pathlib,sys,tempfile
root = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(pathlib.Path(root)/'evals/compare'))
import judge

def assistant(mid,blocks):
 return {'type':'assistant','parent_tool_use_id':None,'message':{'id':mid,'content':blocks}}
def tool(uid,content):
 return {'type':'tool_use','id':uid,'name':'Agent','input':{'prompt':content}}
def result(usage):
 return {'type':'result','is_error':False,'result':'ok','usage':usage}
with tempfile.TemporaryDirectory(prefix='ts-g-probes-') as t:
 p=pathlib.Path(t)
 # G1: separate real calls, not retransmitted events.
 evs=[assistant('m',[tool('a1','same task')]),assistant('m',[tool('a2','same task')])]
 tr=judge.Transcript(evs)
 print('G1_distinct_tools',json.dumps({'tools':len(tr.tool_uses),'actual':tr.parent_added_text(),'expected':'{"prompt":same task}\n{"prompt":same task}'}))
 # G2: absent fields must not become measured zeros.
 for usages in [[{}],[{},{}],[{'input_tokens':3,'output_tokens':2},{'input_tokens':5,'output_tokens':1}]]:
  evs=[{'type':'system','subtype':'init','plugins':[]}]+[result(u) for u in usages]
  log=p/'usage.jsonl';log.write_text('\n'.join(json.dumps(e) for e in evs))
  spec={'id':'g2-missing','require_parent_tokens':['direct'],'expect':{'direct':{'plugin':False}}}
  v,ok=judge.judge(str(log),spec,{'mode':'direct'})
  print('G2_missing',json.dumps({'usages':usages,'metrics':v['metrics']['parent_input_tokens'],'output':v['metrics']['parent_output_tokens'],'verdict':v['verdict'],'parent_tokens':v['checks'].get('parent_tokens')}))
 # G4: one readable fixture must not excuse the missing source.
 a=p/'a.txt';b=p/'b.txt';a.write_text('small harmless content\n');body='Y'*3000
 for label, paths,exists in [('all_missing',[str(b)],False),('partial_missing',[str(a),str(b)],False),('all_readable',[str(a),str(b)],True)]:
  if exists:b.write_text(body)
  evs=[{'type':'system','subtype':'init','plugins':[{'name':'token-shunt'}]},
    assistant('m',[{'type':'tool_use','id':'a1','name':'Agent','input':{'subagent_type':'token-shunt:bulk-reader','prompt':' '.join(paths)}}]),
    {'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'a1','content':body}]}},
    result({'input_tokens':10,'output_tokens':5,'cache_read_input_tokens':0,'cache_creation_input_tokens':0})]
  log=p/'child.jsonl';log.write_text('\n'.join(json.dumps(e) for e in evs))
  spec={'id':'g4-partial','fixtures':paths,'fixtures_abs':paths,'expect':{'delegate':{'agent_type':'token-shunt:bulk-reader','child_no_body':True,'child_msg_max':4000}}}
  v,ok=judge.judge(str(log),spec,{'mode':'delegate'})
  print('G4_'+label,json.dumps({'verdict':v['verdict'],'child_no_body':v['checks'].get('child_no_body'),'reasons':v['reasons']}))
