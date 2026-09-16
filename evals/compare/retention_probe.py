#!/usr/bin/env python3
"""Did the parent keep the worker's absolute paths in its final answer?

The pre-registered instrument for the check-worker-launch effect run
(reviews/launch-reminder-effect-design-2026-09-16.md). It is not part of
the release gate.

`gold_confirmed` answers a coarser question: a lost path only shows up
there when a gold item happened to ride on it. This asks the narrow one
over every worker line a run produced, using the product's own retention
check so the measurement and the send-back agree on what "kept" means.

A run that produced no usable worker line is `undetermined`, never `ok`:
counting it as clean would credit the treated arm for runs in which
nothing could have gone wrong.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'plugin', 'hooks'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judge                              # noqa: E402
import sendback_retention as rc           # noqa: E402

# The opening words of the reminder check-worker-launch returns. Matching
# the text, not the hook name, keeps this honest if the matcher changes.
REMINDER = 'this worker returns'


def _worker_texts(tr):
    out = []
    for use in tr.agent_uses():
        if use['parent_tool_use_id'] is not None:
            continue
        reply = tr.child_return_of(use)
        if reply and reply.get('text'):
            out.append(reply['text'])
    return out


def _reminder_seen(tr):
    """(the hook answered, the text reached the parent's context).

    Two separate claims. The hook returning a payload is visible in the
    hook_response event; the CLI turning that payload into a message the
    model reads is what makes the arm treated, and it has to be observed
    on its own.
    """
    answered = delivered = False
    for e in tr.hook_events:
        payload = '%s%s' % (e.get('output') or '', e.get('stdout') or '')
        if REMINDER in payload:
            answered = True
    for e in tr.events:
        if e.get('type') == 'system' and e.get('subtype') in (
                'hook_started', 'hook_response'):
            continue
        if REMINDER in json.dumps(e, ensure_ascii=False):
            delivered = True
    return answered, delivered


def score_transcript(path):
    tr = judge.Transcript(judge.load_events(path))
    texts = _worker_texts(tr)
    check = rc.check_line_retention(texts or None, tr.final_text())
    answered, delivered = _reminder_seen(tr)
    lost = sorted({rc.citation(l) for l in
                   check.get('altered', []) + check.get('dropped', [])
                   + check.get('demoted', [])} - {None})
    return {'status': check['status'], 'reason': check.get('reason', ''),
            'lost': lost,
            'abbreviated': check['status'] == rc.VIOLATION,
            'kept': len(check.get('kept', [])),
            'reminder_hook': answered,
            'reminder_delivered': delivered}


def score_dir(run_dir):
    """Every transcript in a run directory, grouped by `case/mode`."""
    transcripts = os.path.join(run_dir, 'transcripts')
    verdicts = os.path.join(run_dir, 'verdicts')
    totals = {'runs': 0, 'measured': 0, 'abbreviated': 0, 'undetermined': 0,
              'reminder_hook': 0, 'reminder_delivered': 0,
              'cost': 0.0, 'slots': {}}
    if not os.path.isdir(transcripts):
        return totals
    for name in sorted(os.listdir(transcripts)):
        if not name.endswith('.jsonl') or name.endswith('.sendback.jsonl'):
            continue
        stem = name[:-len('.jsonl')]
        case, _, mode = stem.rpartition('.')
        got = score_transcript(os.path.join(transcripts, name))
        verdict_path = os.path.join(verdicts, stem + '.json')
        if os.path.isfile(verdict_path):
            with open(verdict_path, encoding='utf-8') as fh:
                verdict = json.load(fh)
            got['verdict'] = verdict.get('verdict')
            cost = (verdict.get('metrics') or {}).get('total_cost_usd')
            if isinstance(cost, (int, float)):
                totals['cost'] = round(totals['cost'] + cost, 6)
        totals['runs'] += 1
        if got['status'] == rc.UNDETERMINED:
            totals['undetermined'] += 1
        else:
            totals['measured'] += 1
        totals['abbreviated'] += 1 if got['abbreviated'] else 0
        totals['reminder_hook'] += 1 if got['reminder_hook'] else 0
        totals['reminder_delivered'] += 1 if got['reminder_delivered'] else 0
        totals['slots'].setdefault('%s/%s' % (case, mode), []).append(got)
    return totals


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        sys.stderr.write('usage: retention_probe.py <run-dir>...\n')
        return 2
    for run_dir in argv:
        json.dump({run_dir: score_dir(run_dir)}, sys.stdout, indent=2,
                  sort_keys=True)
        sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
