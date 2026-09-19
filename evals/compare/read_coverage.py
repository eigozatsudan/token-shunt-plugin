#!/usr/bin/env python3
"""What fraction of a file the parent recovered, read by read.

Design: docs/superpowers/specs/2026-09-19-targeted-read-coverage-design.md

Lock B never denies a targeted Read, and 18 of the 21 archived parent corpus
Reads were targeted. This says how much of each file those reads added up
to. It parses no transcript: the denominator (totalLines) is in the hook
event and nowhere else, so the input is the hook's own log.

It reports what the parent did. High coverage is not a verdict, and there
is no threshold here, because no measurement supports one yet.

Not part of the release gate. Bills nothing.
"""
import csv
import json
import sys

COLUMNS = ('session_id', 'parent', 'agent_id', 'agent_type', 'file_path',
           'reads', 'covered', 'total', 'coverage', 'overlap', 'segments',
           'bytes', 'total_changed', 'impossible')


def load(path):
    """The coverage lines of one hook log, in order.

    The log is shared with every other hook, and a run killed mid-write
    leaves a partial last line; neither is a reason to produce no number.
    """
    found = []
    with open(path, encoding='utf-8', errors='replace') as source:
        for entry in source:
            try:
                row = json.loads(entry)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get('hook') == 'record-coverage':
                found.append(row)
    return found


def _parent(row):
    """Whether the parent issued this read, not a worker sharing the session.

    Both fields, because `intake_ledger.py:134` uses both: a worker whose
    event carries only `agent_type` would otherwise be filed as the parent,
    and a worker reads whole files by design.
    """
    return not (row.get('agent_id') or row.get('agent_type'))


def sessions(records):
    """Every session id in the log, sorted.

    One conversation should be one id across its follow-up turns. Two means
    `--resume` started a new session, and the coverage of one conversation
    has been split in two.
    """
    return sorted({r.get('session_id') for r in records if r.get('session_id')})


def rows(records):
    """One row per (session, reader, file): the union of the lines taken."""
    groups = {}
    for row in records:
        key = (row.get('session_id'), _parent(row), row.get('agent_id'),
               row.get('agent_type'), row.get('file_path'))
        groups.setdefault(key, []).append(row)
    out = []
    for (session, parent, agent, agent_type, path), taken in groups.items():
        spans = [(r['start'], r['start'] + r['lines'] - 1) for r in taken
                 if type(r.get('start')) is int and type(r.get('lines')) is int
                 and r['lines'] > 0]
        totals = [r['total'] for r in taken if type(r.get('total')) is int]
        merged = _merge(spans)
        covered = sum(end - start + 1 for start, end in merged)
        changed = len(set(totals)) > 1
        total = totals[-1] if totals else None
        # A read past the end of the file means the event was wrong, not
        # that the parent recovered 140% of it.
        impossible = bool(total) and covered > total
        out.append({
            'session_id': session, 'parent': parent, 'agent_id': agent,
            'agent_type': agent_type, 'file_path': path,
            'reads': len(taken), 'covered': covered, 'total': total,
            'coverage': None if changed or impossible or not total
                        else covered / total,
            'overlap': sum(end - start + 1 for start, end in spans) - covered,
            'segments': len(merged),
            'bytes': sum(r.get('bytes') or 0 for r in taken),
            'total_changed': changed, 'impossible': impossible})
    return sorted(out, key=lambda r: (r['session_id'] or '', not r['parent'],
                                      r['agent_id'] or '',
                                      r['agent_type'] or '', r['file_path']))


def _merge(spans):
    """Disjoint closed intervals covering the same lines, low to high.

    Adjacent spans join: reading 1-10 then 11-20 is one recovery of 20
    lines, not two of ten.
    """
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [tuple(span) for span in merged]


def rollup(counted):
    """The rate across the files that have one.

    A file whose size changed mid-session has no defensible denominator, so
    it is left out here rather than averaged in silently. `excluded` is
    reported because that exclusion is not random: it drops the files an
    edit touched, which leaves a population of files that were only read.
    """
    usable = [r for r in counted if r['coverage'] is not None]
    covered = sum(r['covered'] for r in usable)
    total = sum(r['total'] for r in usable)
    return {'files': len(usable), 'reads': sum(r['reads'] for r in usable),
            'covered': covered, 'total': total,
            'coverage': (covered / total) if total else None,
            'excluded': len(counted) - len(usable)}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print('usage: read_coverage.py <hooklog> [...]', file=sys.stderr)
        return 2
    records = []
    for path in argv:
        records.extend(load(path))
    counted = rows(records)
    writer = csv.DictWriter(sys.stdout, fieldnames=COLUMNS)
    writer.writeheader()
    for row in counted:
        writer.writerow(row)
    summary = rollup(counted)
    print('# files=%(files)d reads=%(reads)d covered=%(covered)d '
          'total=%(total)d excluded=%(excluded)d' % summary, file=sys.stderr)
    print('# coverage=%s' % ('-' if summary['coverage'] is None
                             else '%.4f' % summary['coverage']), file=sys.stderr)
    # This number is not a ranking. A parent that took 30% in slices
    # polluted itself; a parent that took 30% because Grep answered the
    # question did not. They print the same.
    print('# coverage is what the parent did, not how well it did it:'
          ' a low rate is neither good nor bad', file=sys.stderr)
    found = sessions(records)
    if len(found) > 1:
        print('# WARNING: %d session ids in this log (%s): one conversation'
              ' split across sessions reads as a lower rate'
              % (len(found), ','.join(found)), file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
