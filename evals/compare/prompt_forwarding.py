#!/usr/bin/env python3
"""Count how often a parent pastes the deny contract into a worker prompt.

The deny template is addressed to the caller. A parent that copies it into
the Agent prompt hands the worker "do not read these paths yourself", and
the worker then reports nothing -- a failure no Stop hook can repair,
because the worker was told to hold still (three launches in the saved
corpus; reviews/sendback-worker-repair-2026-09-15.md section 6.1).

Two template changes were meant to reduce it, so the rate is reported per
era rather than as one number. Run it over ordinary saved sessions; it
starts no model and costs nothing.

    python3 evals/compare/prompt_forwarding.py [--json]
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..', 'plugin', 'hooks'))
import sendback_session as se                            # noqa: E402

WORKER_AGENT = 'token-shunt:bulk-reader'
# The caller-only imperative at the head of the deny.
DENY_MARK = 'do not read these paths yourself'
# The response contract da6e4d3 stopped the parent from restating.
FORMAT_MARK = 'One bullet per fact'
# The rendered deny, as it appears in the parent's own session rows. Only a
# parent that was served one can forward it, so it is the honest denominator:
# an Agent call the user asked for directly never had the text to copy.
SERVED_MARK = 'Delegate now'

# Commit timestamps of the two changes to plugin/hooks/reader-call-contract.
# A session is attributed by its last write, so a run straddling a commit
# lands in the later era; at these volumes that is noise, not a bias.
ERAS = ((0, 'before da6e4d3'),
        (1789435235, 'da6e4d3 (no format restatement)'),
        (1789476597, 'ea00cd6 (no self-forwarding)'))


def classify_prompt(prompt):
    """What the parent copied into the worker's prompt."""
    text = ' '.join((prompt or '').split())
    if not text:
        return None
    return {'forwards_deny': DENY_MARK in text,
            'restates_format': FORMAT_MARK in text}


def era(ts, eras=ERAS):
    name = eras[0][1]
    for start, label in eras:
        if ts >= start:
            name = label
    return name


def scan(pattern=None):
    pattern = pattern or os.path.expanduser('~/.claude/projects/*/*.jsonl')
    out = {label: {'launches': 0, 'deny_served': 0, 'forwards_deny': 0,
                   'restates_format': 0}
           for _, label in ERAS}
    for path in sorted(glob.glob(pattern)):
        try:
            rows = se.read_jsonl(path)
        except OSError:
            continue
        runs = se.launches(path, agent_type=WORKER_AGENT, rows=rows)
        if not runs:
            continue
        bucket = out[era(os.path.getmtime(path))]
        try:
            with open(path, encoding='utf-8', errors='replace') as fh:
                served = SERVED_MARK in fh.read()
        except OSError:
            served = False
        for run in runs:
            got = classify_prompt((run['launch_input'] or {}).get('prompt'))
            if got is None:
                continue
            bucket['launches'] += 1
            bucket['deny_served'] += served
            for key in ('forwards_deny', 'restates_format'):
                bucket[key] += bool(got[key])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--glob', default=None, help='session glob to scan')
    args = ap.parse_args(argv)
    result = scan(args.glob)
    if args.json:
        json.dump(result, sys.stdout, indent=1)
        sys.stdout.write('\n')
        return 0
    print('%-34s %8s %11s %16s %16s'
          % ('era', 'launches', 'deny served', 'forwards deny', 'restates format'))
    for _, label in ERAS:
        row = result[label]
        n, served = row['launches'], row['deny_served']
        def share(count, total):
            return ('%d (%.1f%%)' % (count, 100.0 * count / total)) if total else '-'
        print('%-34s %8d %11d %16s %16s'
              % (label, n, served, share(row['forwards_deny'], served),
                 share(row['restates_format'], n)))
    print('\n"forwards deny" is a share of the deny-served launches: only a '
          'parent\nthat was handed the template can copy it.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
