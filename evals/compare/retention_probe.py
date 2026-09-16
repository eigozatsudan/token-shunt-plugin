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
import glob
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
# Where the CLI keeps the session files. The eval transcript is stream-json
# from stdout and carries no attachments, so delivery is not observable in
# it at all (reviews/launch-reminder-effect-2026-09-16.md section 1.1).
SESSIONS = os.path.expanduser('~/.claude/projects')
ATTACHMENT = 'hook_additional_context'


def _worker_texts(tr):
    out = []
    for use in tr.agent_uses():
        if use['parent_tool_use_id'] is not None:
            continue
        reply = tr.child_return_of(use)
        if reply and reply.get('text'):
            out.append(reply['text'])
    return out


def _answered(tr):
    """Did the hook return the reminder? Visible in the hook_response."""
    for e in tr.hook_events:
        payload = '%s%s' % (e.get('output') or '', e.get('stdout') or '')
        if REMINDER in payload:
            return True
    return False


def _delivered(tr, sessions=SESSIONS):
    """Did the reminder reach the parent's context? True / False / None.

    A separate claim from the hook answering, and one the eval transcript
    cannot settle: the CLI turns `additionalContext` into an attachment,
    and attachments are written to the session file, not to stdout. None
    means the session could not be read -- a run whose session was cleaned
    up must not be counted as "not delivered".
    """
    session_id = (tr.init or {}).get('session_id')
    if not session_id:
        return None
    paths = sorted(glob.glob(os.path.join(str(sessions), '*',
                                          session_id + '.jsonl')))
    if not paths:
        return None
    for path in paths:
        try:
            with open(path, encoding='utf-8') as fh:
                for line in fh:
                    if REMINDER in line and ATTACHMENT in line:
                        return True
        except OSError:
            return None
    return False


SHAPES = ('absolute', 'mixed', 'relative', 'undetermined', 'no items')


def report_shape(text):
    """How one worker report spells the paths on its confirmed lines.

    `absolute` every usable, `relative` none usable, `mixed` both -- the
    shape section 11.1 turns on, because today only `relative` is sent
    back and `mixed` passes with its relative lines demoted. A path to a
    file that is gone is `undetermined`: the run's temp tree is deleted
    afterwards, and reading that as a contract violation would invent a
    base rate out of housekeeping.
    """
    usable = unusable = unknown = 0
    for line in rc.confirmed_lines(text):
        verdict = rc.classify_path(rc.citation(line))
        if verdict == rc.OK:
            usable += 1
        elif verdict == rc.UNDETERMINED:
            unknown += 1
        else:
            unusable += 1
    if not (usable or unusable or unknown):
        shape = 'no items'
    elif usable and unusable:
        shape = 'mixed'
    elif unusable:
        shape = 'relative'
    elif usable:
        shape = 'absolute'
    else:
        shape = 'undetermined'
    return {'usable': usable, 'unusable': unusable, 'unknown': unknown,
            'shape': shape}


def score_transcript(path, sessions=SESSIONS):
    tr = judge.Transcript(judge.load_events(path))
    texts = _worker_texts(tr)
    check = rc.check_line_retention(texts or None, tr.final_text())
    answered, delivered = _answered(tr), _delivered(tr, sessions)
    lost = sorted({rc.citation(l) for l in
                   check.get('altered', []) + check.get('dropped', [])
                   + check.get('demoted', [])} - {None})
    return {'status': check['status'], 'reason': check.get('reason', ''),
            'lost': lost,
            'reports': [report_shape(t) for t in texts],
            'abbreviated': check['status'] == rc.VIOLATION,
            'kept': len(check.get('kept', [])),
            'reminder_hook': answered,
            'reminder_delivered': delivered}


def score_dir(run_dir, sessions=SESSIONS):
    """Every transcript in a run directory, grouped by `case/mode`."""
    transcripts = os.path.join(run_dir, 'transcripts')
    verdicts = os.path.join(run_dir, 'verdicts')
    totals = {'runs': 0, 'measured': 0, 'abbreviated': 0, 'undetermined': 0,
              'reminder_hook': 0, 'reminder_delivered': 0,
              'reminder_unmeasured': 0,
              'reports': 0, 'shapes': {name: 0 for name in SHAPES},
              'cost': 0.0, 'slots': {}}
    if not os.path.isdir(transcripts):
        return totals
    for name in sorted(os.listdir(transcripts)):
        if not name.endswith('.jsonl') or name.endswith('.sendback.jsonl'):
            continue
        stem = name[:-len('.jsonl')]
        case, _, mode = stem.rpartition('.')
        # `_probe_iso` and `_probe_load` are the runner's own start-up
        # checks and carry no `case.mode` name. They are not cases, and
        # counting them inflated `runs` and `undetermined`
        # (reviews/launch-reminder-effect-2026-09-16.md section 5).
        if not case or not mode:
            continue
        got = score_transcript(os.path.join(transcripts, name), sessions)
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
        for report in got['reports']:
            totals['reports'] += 1
            totals['shapes'][report['shape']] += 1
        if got['reminder_delivered'] is None:
            totals['reminder_unmeasured'] += 1
        elif got['reminder_delivered']:
            totals['reminder_delivered'] += 1
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
