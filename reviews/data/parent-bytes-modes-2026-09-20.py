#!/usr/bin/env python3
"""Classify every archived auto conversation by how the parent's corpus
intake was (or was not) stopped.

Adapter only. The two counts and the root both come from shipped
instruments; nothing here judges:

  * `parent_bytes.parent_read_bytes` does NOT drop `is_error`, so a Read
    the hook denied still contributes -- the deny text itself, which really
    did enter the parent's context.
  * `parent_turn_reads.read_rows` DOES drop `is_error`, so it counts file
    body only.

The difference between them is the signal: body 0 with a non-zero total
means the parent tried and the hook refused. Reading either number alone
cannot tell "never attempted" from "attempted and denied", and those are
opposite statements about whether the product worked
(reviews/subthreshold-unprotected-2026-09-20.md section 3).

`derive_root_of` is used rather than a literal path because it is built
from the conversation's own Read paths, including denied ones -- a run
whose corpus Reads were all denied still names its root.

    python3 reviews/data/parent-bytes-modes-2026-09-20.py <recon-dir> [...]
"""
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..',
                                'evals', 'compare'))
import parent_bytes as pb          # noqa: E402
import parent_turn_reads as ptr    # noqa: E402

COLUMNS = ['block', 'run', 'case', 'total_bytes', 'body_bytes',
           'body_reads', 'mode']


def mode_of(total, body):
    if body > 0:
        return 'unprotected'
    if total > 0:
        return 'denied'
    return 'no_attempt'


def rows_for(directory, block, run):
    out = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith('.auto.jsonl'):
            continue
        case = name[:-len('.auto.jsonl')]
        root = ptr.derive_root_of(directory, case, 'auto')
        path = os.path.join(directory, name)
        total = pb.parent_read_bytes(path, root)
        reads = ptr.read_rows(path, root) if root else []
        body = sum(r['bytes'] for r in reads)
        out.append({'block': block, 'run': run, 'case': case,
                    'total_bytes': total, 'body_bytes': body,
                    'body_reads': len(reads), 'mode': mode_of(total, body)})
    return out


def main(argv):
    if not argv:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    rows = []
    for top in argv:
        for dirpath, _, files in os.walk(top):
            # Two layouts are in the archive: `<run>/transcripts/*.jsonl`
            # and `<run>/*.jsonl` with no subdirectory. Keying on the
            # directory name dropped 78 of 239 conversations silently.
            if not any(f.endswith('.auto.jsonl') for f in files):
                continue
            here = dirpath
            if os.path.basename(here) == 'transcripts':
                here = os.path.dirname(here)
            run = os.path.basename(here)
            block = os.path.relpath(os.path.dirname(here), top).split(os.sep)[0]
            rows.extend(rows_for(dirpath, '-' if block in ('.', run) else block,
                                 run))
    rows.sort(key=lambda r: (r['case'], r['block'], r['run']))
    writer = csv.DictWriter(sys.stdout, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
