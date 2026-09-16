#!/usr/bin/env python3
"""Did the parent restate the worker's lines and then close without them?

Stage 0 of reviews/relapse-device-design-2026-09-16.md. Not part of the
release gate.

The control arm of that measurement runs a build with no relapse check, so
its trial log records no relapse at all. The instrument therefore reads the
finished CLI session and decides for itself: the parent's last message is
the answer the run ends on, everything it said before that in the turn is
what it had already produced.

The judgement itself is the product's own `check_relapse`, so the
measurement and the hook agree on what a relapse is. The split into
"closing message" and "earlier text" is the probe's own, because the hook
never sees them that way -- at hook time the closing message is not in the
session file yet.

A session whose worker output cannot be read is `unmeasured`, never `ok`:
a run in which nothing could be judged must not be counted as clean.
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
import sendback_session as se             # noqa: E402

SESSIONS = os.path.expanduser('~/.claude/projects')


def rows(path):
    out = []
    try:
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return out


def _texts(row):
    content = (row.get('message') or {}).get('content')
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ''
    return '\n'.join(b.get('text', '') for b in content
                     if isinstance(b, dict) and b.get('type') == 'text'
                     and b.get('text'))


def split_turn(session_rows):
    """(everything said before the closing message, the closing message).

    An eval run is one prompt and one turn, which is what makes taking the
    last assistant message as the closing safe here. A session with several
    user turns would need the turn boundary; this instrument is not used on
    one.
    """
    said = []
    for row in session_rows:
        if row.get('type') != 'assistant' or row.get('isSidechain'):
            continue
        text = _texts(row)
        if text:
            said.append(text)
    if not said:
        return '', None
    return '\n'.join(said[:-1]), said[-1]


def score_session(path, exists=os.path.exists):
    """One finished session: relapse, and whether the run ends with the lines."""
    blank = {'relapse': None, 'status': 'unmeasured', 'reason': '',
             'lost': [], 'final_retained': None}
    session_rows = rows(path)
    if not session_rows:
        return dict(blank, reason='no session rows')
    try:
        got = se.check_inputs(path, rows=session_rows)
    except se.TooLarge as exc:
        return dict(blank, reason=str(exc))
    child = got.get('child_texts')
    earlier, closing = split_turn(session_rows)
    if child is None or closing is None:
        return dict(blank, reason='worker output or final answer unobtainable')
    items = rc.check_child_items(child, exists)
    if items['status'] != rc.OK:
        # No usable worker line, whether because the worker reported none or
        # because its files are gone: there is nothing the parent could have
        # restated and then dropped. Unmeasured, never counted as clean
        # (the same reading retention_probe takes).
        return dict(blank, reason=items['reason'])
    relapse = rc.check_relapse(child, earlier, closing, exists)
    final = rc.check_line_retention(child, closing, exists)
    return {'relapse': relapse['status'] == rc.VIOLATION,
            'status': relapse['status'],
            'reason': relapse['reason'],
            'lost': relapse['lost'],
            'final_retained': final['status'] == rc.OK}


def session_for(transcript, sessions=SESSIONS):
    """The CLI session file an eval transcript names, or None."""
    try:
        tr = judge.Transcript(judge.load_events(transcript))
    except Exception:                      # a probe never fails a run
        return None
    session_id = (tr.init or {}).get('session_id')
    if not session_id:
        return None
    found = sorted(glob.glob(os.path.join(str(sessions), '*',
                                          session_id + '.jsonl')))
    return found[0] if found else None


def relapse_blocks(log_path):
    """Relapse blocks per session id, from the product's trial log.

    Counted rather than merely flagged: the budget says one session can
    never carry two, and an item that cannot show the violation cannot
    check it (E4).
    """
    counts = {}
    for rec in rows(log_path):
        if rec.get('outcome') == 'blocked' and rec.get('relapse'):
            key = rec.get('session_id') or ''
            counts[key] = counts.get(key, 0) + 1
    return counts


def score_dir(run_dir, sessions=SESSIONS):
    """Every case transcript in a run directory, grouped by `case/mode`."""
    transcripts = os.path.join(run_dir, 'transcripts')
    totals = {'runs': 0, 'relapses': 0, 'final_retained': 0,
              'unmeasured': 0, 'relapse_blocks': {}, 'slots': {}}
    if not os.path.isdir(transcripts):
        return totals
    for name in sorted(os.listdir(transcripts)):
        if not name.endswith('.jsonl') or name.endswith('.sendback.jsonl'):
            continue
        stem = name[:-len('.jsonl')]
        if stem.count('.') != 1:
            continue                       # runner start-up probes
        case, mode = stem.split('.')
        path = os.path.join(transcripts, name)
        session = session_for(path, sessions)
        got = (score_session(session) if session else
               {'relapse': None, 'status': 'unmeasured',
                'reason': 'no session file', 'lost': [], 'final_retained': None})
        got['blocks'] = relapse_blocks(path + '.sendback.jsonl')
        for key, value in got['blocks'].items():
            totals['relapse_blocks'][key] = (
                totals['relapse_blocks'].get(key, 0) + value)
        totals['runs'] += 1
        if got['relapse'] is None:
            totals['unmeasured'] += 1
        elif got['relapse']:
            totals['relapses'] += 1
        if got['final_retained']:
            totals['final_retained'] += 1
        totals['slots'].setdefault('%s/%s' % (case, mode), []).append(got)
    return totals


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print('usage: relapse_probe.py <run-dir> [...]', file=sys.stderr)
        return 2
    for run_dir in argv:
        print(json.dumps({run_dir: score_dir(run_dir)}, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
