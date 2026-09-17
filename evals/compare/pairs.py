#!/usr/bin/env python3
"""One row per direct/auto pair, small enough to keep in the repository.

A review records what a measurement concluded. It does not record the
numbers a later question would need. On 2026-09-17 the worktrees holding
88 pairs of Redmine transcripts were deleted after their analysis, and no
pair can be re-examined now (reviews/redmine-dose-2026-09-17.md,
reviews/redmine-effect2-2026-09-17.md). The transcripts were 94 MB; these
rows are a few kilobytes. Run this before the run directories go, and
commit the CSV beside the review:

    python3 evals/compare/pairs.py -o reviews/data/<name>.csv \\
        /path/to/evals/compare/tmp/runs

The columns are what every paired measurement so far has needed: the
parent's own corpus intake in each arm, each arm's cost, whether the
answer was right, and whether the verdict passed. Anything case-specific
belongs in the review, not here.

`--root-base` scores run directories that were moved after the run. The
transcripts hold absolute paths from where the run happened, so matching
against the new location returns zero bytes for every arm -- which is
also what a correct auto arm returns, so the mistake reads as a finding
(that review, section 9).

Not part of the release gate.
"""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from parent_bytes import parent_read_bytes
from spend import transcript_cost

USAGE = 2
MODES = ('direct', 'auto')
COLUMNS = ['run', 'case', 'direct_read_bytes', 'auto_read_bytes',
           'direct_cost_usd', 'auto_cost_usd',
           'direct_accuracy_any', 'auto_accuracy_any',
           'direct_pass', 'auto_pass', 'auto_reasons']


def flag(value):
    """'1' / '0' for a check, '' when the run recorded no opinion.

    An absent check and a failed one are different facts. Writing the
    first as a zero would make it indistinguishable from the second in a
    file whose whole purpose is to be read later.
    """
    return '' if value is None else ('1' if value else '0')


def pair_rows(runs_root, root_base=None, warn=None):
    """Every case in `runs_root` that has both arms, as CSV-ready dicts."""
    rows = []
    for name in sorted(os.listdir(runs_root)):
        run = os.path.join(runs_root, name)
        summary_path = os.path.join(run, 'summary.json')
        if not os.path.isfile(summary_path):
            continue
        try:
            with open(summary_path, encoding='utf-8') as source:
                summary = json.load(source)
        except (OSError, ValueError) as exc:
            if warn:
                warn('%s: unreadable summary.json (%s)' % (name, exc))
            continue
        # Where the corpus was when the run happened, which is what the
        # transcripts name.
        root = os.path.join(root_base or runs_root, name, 'work', 'fixtures')
        for case, body in sorted((summary.get('cases') or {}).items()):
            modes = body.get('modes') or {}
            if not all(mode in modes for mode in MODES):
                continue
            row, complete = {'run': name, 'case': case}, True
            for mode in MODES:
                transcript = os.path.join(run, 'transcripts',
                                          '%s.%s.jsonl' % (case, mode))
                if not os.path.isfile(transcript):
                    if warn:
                        warn('%s/%s: no %s transcript' % (name, case, mode))
                    complete = False
                    break
                checks = modes[mode].get('checks') or {}
                reasons = modes[mode].get('reasons') or []
                row['%s_read_bytes' % mode] = parent_read_bytes(transcript, root)
                row['%s_cost_usd' % mode] = '%.4f' % (transcript_cost(transcript) or 0.0)
                row['%s_accuracy_any' % mode] = flag(checks.get('accuracy_any'))
                row['%s_pass' % mode] = flag(not reasons)
                if mode == 'auto':
                    row['auto_reasons'] = '; '.join(str(r) for r in reasons)
            if complete:
                rows.append(row)
    return rows


def write(rows, stream):
    writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root_base, out = None, None
    while argv and argv[0] in ('--root-base', '-o'):
        if len(argv) < 2:
            print('usage: pairs.py [--root-base DIR] [-o FILE] <runs-dir> [...]',
                  file=sys.stderr)
            return USAGE
        if argv[0] == '--root-base':
            root_base = argv[1]
        else:
            out = argv[1]
        argv = argv[2:]
    if not argv:
        print('usage: pairs.py [--root-base DIR] [-o FILE] <runs-dir> [...]',
              file=sys.stderr)
        return USAGE
    for root in argv:
        if not os.path.isdir(root):
            print('not a directory: %s' % root, file=sys.stderr)
            return USAGE
    warn = lambda text: print('skipped %s' % text, file=sys.stderr)
    rows = []
    for root in argv:
        rows.extend(pair_rows(root, root_base, warn))
    if out:
        with open(out, 'w', encoding='utf-8', newline='') as stream:
            write(rows, stream)
        print('%d pairs -> %s' % (len(rows), out), file=sys.stderr)
    else:
        write(rows, sys.stdout)
    return 0


if __name__ == '__main__':
    sys.exit(main())
