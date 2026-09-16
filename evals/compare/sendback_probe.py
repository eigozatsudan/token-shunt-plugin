#!/usr/bin/env python3
"""Score a SENDBACK=on probe against the pre-registered items.

Not part of the release gate. The items and the reading of P1/P2 as
repair-given-a-block are in
`reviews/sendback-fixed-n-probe-design-2026-09-16.md`.
"""
import json
import os
import sys


def parent_progress(rows):
    replies = calls = 0
    for entry in rows or []:
        if entry.get('type') != 'assistant' or entry.get('isSidechain'):
            continue
        replies += 1
        for block in (entry.get('message') or {}).get('content') or []:
            if isinstance(block, dict) and block.get('type') == 'tool_use':
                calls += 1
    return {'assistant_replies': replies, 'tool_calls': calls,
            'transcript_lines': len(rows or [])}


def resumed(baseline, rows):
    now = parent_progress(rows)
    return (now['assistant_replies'] > baseline.get('assistant_replies', 0)
            or now['tool_calls'] > baseline.get('tool_calls', 0))


def _later_ok(records, start, event, check):
    for rec in records[start + 1:]:
        if rec.get('event') != event:
            continue
        if (rec.get('checks') or {}).get(check) == 'ok':
            return True
    return False


def score_run(records, verdict=None, session_rows=None):
    """One run's trial-log records against the pre-registered items.

    `session_rows` are rows of the CLI session file the record names, which
    is what the hook counted its baseline over. The eval transcript is
    stream-json from stdout and holds a different set of rows, so it cannot
    be compared against that baseline. With no session in hand S3 is left
    unmeasured rather than scored 0: "no discard observed" would otherwise
    be a safety claim with nothing behind it.
    """
    verdict = verdict or {}
    s3_unmeasured = 0
    p1_blocked = p1_repaired = 0
    p2_blocked = p2_repaired = 0
    s1 = s2 = s3 = s4 = 0
    any_block = False
    for i, rec in enumerate(records):
        outcome = rec.get('outcome')
        event = rec.get('event')
        checks = rec.get('checks') or {}
        if rec.get('stop_hook_active') and outcome == 'blocked':
            s4 += 1
        if outcome != 'blocked':
            continue
        any_block = True
        if event == 'Stop':
            if checks.get('line_retention') != 'violation':
                s1 += 1
            p1_blocked += 1
            if _later_ok(records, i, 'Stop', 'line_retention'):
                p1_repaired += 1
            baseline = rec.get('baseline')
            if baseline:
                if session_rows is None:
                    s3_unmeasured += 1
                elif not resumed(baseline, session_rows):
                    s3 += 1
        elif event == 'SubagentStop':
            if checks.get('child_items') != 'violation':
                s1 += 1
            p2_blocked += 1
            if _later_ok(records, i, 'SubagentStop', 'child_items'):
                p2_repaired += 1
    if not any_block and verdict.get('verdict') == 'fail':
        s2 = 1
    cost = ((verdict.get('metrics') or {}).get('total_cost_usd'))
    return {
        'p1': {'blocked': p1_blocked, 'repaired': p1_repaired},
        'p2': {'blocked': p2_blocked, 'repaired': p2_repaired},
        's1': s1, 's2': s2, 's3': s3, 's3_unmeasured': s3_unmeasured,
        's4': s4,
        'cost': cost,
    }


def _load_jsonl(path):
    rows = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def score_dir(run_dir):
    """Aggregate every `*.jsonl.sendback.jsonl` next to a transcript."""
    transcripts = os.path.join(run_dir, 'transcripts')
    verdicts = os.path.join(run_dir, 'verdicts')
    totals = {
        'p1': {'blocked': 0, 'repaired': 0},
        'p2': {'blocked': 0, 'repaired': 0},
        's1': 0, 's2': 0, 's3': 0, 's3_unmeasured': 0, 's4': 0,
        'c1': {'costs': [], 'total': 0.0},
        'runs': 0,
    }
    if not os.path.isdir(transcripts):
        return totals
    for name in sorted(os.listdir(transcripts)):
        if not name.endswith('.jsonl.sendback.jsonl'):
            continue
        stem = name[:-len('.jsonl.sendback.jsonl')]
        records = _load_jsonl(os.path.join(transcripts, name))
        verdict_path = os.path.join(verdicts, stem + '.json')
        verdict = {}
        if os.path.isfile(verdict_path):
            with open(verdict_path, encoding='utf-8') as fh:
                verdict = json.load(fh)
        rows = None
        for rec in records:
            session = rec.get('transcript_path')
            if session and os.path.isfile(session):
                rows = _load_jsonl(session)
                break
        got = score_run(records, verdict, rows)
        totals['runs'] += 1
        for key in ('p1', 'p2'):
            totals[key]['blocked'] += got[key]['blocked']
            totals[key]['repaired'] += got[key]['repaired']
        for key in ('s1', 's2', 's3', 's3_unmeasured', 's4'):
            totals[key] += got[key]
        if isinstance(got['cost'], (int, float)):
            totals['c1']['costs'].append(got['cost'])
            totals['c1']['total'] = round(totals['c1']['total'] + got['cost'], 6)
    return totals


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        sys.stderr.write('usage: sendback_probe.py <run-dir>\n')
        return 2
    json.dump(score_dir(argv[0]), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
