#!/usr/bin/env python3
"""What fraction of a file the parent recovered, read by read.

Design: docs/superpowers/specs/2026-09-19-targeted-read-coverage-design.md

Lock B never denies a targeted Read, and 18 of the 21 archived parent corpus
Reads were targeted. This says how much of each file those reads added up
to. The input is the hook's own log, because the hook is the observation
point on a live run.

It parses no transcript, but the denominator is not exclusive to the hook:
a transcript's `tool_use_result.file` carries the same `startLine` /
`numLines` / `totalLines`, so an archived run can be replayed through this
same aggregator at no cost. `reviews/data/read-coverage-archive-2026-09-20.py`
does that and reproduces this module's own CSV exactly on the three live
runs. An earlier version of this docstring said the denominator was in the
hook event "and nowhere else"; that was wrong, and it is why the archive
went unmeasured for a day.

It reports what the parent did. High coverage is not a verdict, and there
is no threshold here, because no measurement supports one yet.

Not part of the release gate. Bills nothing.
"""
import csv
import json
import os
import re
import sys

COLUMNS = ('run', 'conversation', 'source', 'sources', 'session_id', 'parent',
           'agent_id', 'agent_type', 'file_path', 'reads', 'covered', 'total',
           'coverage', 'overlap', 'segments', 'bytes', 'full_file_reads',
           'total_changed', 'impossible')

# `run_followups` writes `$first.turn<N>.jsonl` beside the first turn's
# transcript, and `_claude_call` appends `.hooklog` to whichever it was
# handed. Stripping the suffix leaves `<case>.<mode>.jsonl`, which names one
# conversation across all of its turns.
TURN = re.compile(r'\.turn\d+\.jsonl$')


def load(path):
    """The coverage lines of one hook log, in order, tagged with its name.

    The log is shared with every other hook, and a run killed mid-write
    leaves a partial last line; neither is a reason to produce no number.

    The basename rides along because the salvage in section 9 globs every
    run, mode and case into one CSV, and the run directories are deleted
    right afterwards: `<case>.<mode>.jsonl[.turnN.jsonl].hooklog` is the
    only surviving record of which arm and which case a row came from.

    The conversation and the run come with it, because one conversation
    writes one hooklog per turn and one case may appear in several runs:
    the basename alone can neither join the turns nor keep the runs apart.
    """
    name = os.path.basename(path)
    where = _run(path)
    found = []
    with open(path, encoding='utf-8', errors='replace') as source:
        for entry in source:
            try:
                row = json.loads(entry)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get('hook') == 'record-coverage':
                found.append(dict(row, source=name, run=where,
                                  conversation=_conversation(name)))
    return found


def _conversation(name):
    """The one conversation a hooklog belongs to, from its basename.

    `deep-read.plugin.jsonl.hooklog` and
    `deep-read.plugin.jsonl.turn2.jsonl.hooklog` are turn 1 and turn 2 of
    one conversation, so both answer `deep-read.plugin.jsonl`. A name that
    fits neither shape is its own conversation, whole: guessing at an
    unknown layout would merge rows that have nothing to do with each other.
    """
    stem = name[:-len('.hooklog')] if name.endswith('.hooklog') else name
    stem = TURN.sub('', stem)
    return stem or name


def _run(path):
    """The `run.*` component of an input path, or '' if it has none.

    Section 9 salvages with `.../run.*/transcripts/*.hooklog`, so one CSV
    can hold several runs of the same case under the same basename. Without
    this they would union into one row and read as one parent's recovery.
    """
    for part in os.path.normpath(path).split(os.sep):
        if part.startswith('run.'):
            return part
    return ''


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
    """One row per (run, conversation, session, reader, file).

    The key holds the conversation, never the raw hooklog name: run.sh
    exports `TOKEN_SHUNT_HOOK_LOG=$out.hooklog` per CLI invocation and
    `run_followups` gives every follow-up turn its own `$first.turnN.jsonl`,
    so one conversation writes several logs under one session id. Keying on
    the basename splits a parent that took lines 1-30 in turn 1 and 31-60 in
    turn 2 into two rows of 0.30 and hides the 0.60 it actually recovered --
    and sequential recovery across turns is what this instrument is for.

    `source` stays reported, as every log that fed the row, sorted and
    `;`-joined, with `sources` counting them: one name would be a silent
    choice among several.
    """
    groups = {}
    for row in records:
        key = (row.get('run'), row.get('conversation'), row.get('session_id'),
               _parent(row), row.get('agent_id'), row.get('agent_type'),
               row.get('file_path'))
        groups.setdefault(key, []).append(row)
    out = []
    for key, taken in groups.items():
        where, talk, session, parent, agent, agent_type, path = key
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
        names = sorted({r.get('source') for r in taken if r.get('source')})
        out.append({
            'run': where or '', 'conversation': talk,
            'source': ';'.join(names), 'sources': len(names),
            'session_id': session, 'parent': parent, 'agent_id': agent,
            'agent_type': agent_type, 'file_path': path,
            'reads': len(taken), 'covered': covered, 'total': total,
            'coverage': None if changed or impossible or not total
                        else covered / total,
            'overlap': sum(end - start + 1 for start, end in spans) - covered,
            'segments': len(merged),
            'bytes': sum(r.get('bytes') or 0 for r in taken),
            # A whole-file Read cut short by the line cap
            # (CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS) is recorded in the
            # same shape as a deliberate slice. This count is the only tell,
            # and the motive for the instrument was that 18 of 21 parent
            # reads were targeted. It is a count, never a threshold.
            'full_file_reads': sum(1 for r in taken if r.get('offset') is None
                                   and r.get('limit') is None),
            'total_changed': changed, 'impossible': impossible})
    return sorted(out, key=lambda r: (r['run'], r['conversation'] or '',
                                      r['session_id'] or '', not r['parent'],
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


def rollup(counted, parent=True):
    """The rate across one reader's files that have one.

    Parent and worker are rolled up apart and never summed. A worker reads
    whole files by design, so its rows sit at 1.0 and a mixed rate always
    reads high (section 6). The headline number is the parent's.

    A file whose size changed mid-session has no defensible denominator, so
    it is left out here rather than averaged in silently. The exclusion is
    not random -- it drops the files an edit touched, leaving a population
    of files that were only read -- so each reason is counted separately;
    one folded number could not say which bias it carried.

    Every field describes the same population: the usable rows only.
    """
    mine = [r for r in counted if bool(r['parent']) is parent]
    usable = [r for r in mine if r['coverage'] is not None]
    covered = sum(r['covered'] for r in usable)
    total = sum(r['total'] for r in usable)
    left_out = [r for r in mine if r['coverage'] is None]
    return {'files': len(usable), 'reads': sum(r['reads'] for r in usable),
            'covered': covered, 'total': total,
            'coverage': (covered / total) if total else None,
            # The same coverage can hide ten times the pollution: lines
            # 1-50 read ten times move overlap and bytes, not the rate.
            'overlap': sum(r['overlap'] for r in usable),
            'bytes': sum(r['bytes'] for r in usable),
            'full_file_reads': sum(r['full_file_reads'] for r in usable),
            'excluded': len(left_out),
            'excluded_changed': sum(1 for r in left_out if r['total_changed']),
            'excluded_impossible': sum(1 for r in left_out if r['impossible']),
            'excluded_no_total': sum(1 for r in left_out if not r['total_changed']
                                     and not r['impossible'])}


def _summary(label, roll):
    """One `#` line for one reader's rollup."""
    return ('# %s files=%d reads=%d covered=%d total=%d overlap=%d bytes=%d'
            ' full_file_reads=%d excluded=%d (changed=%d impossible=%d'
            ' no_total=%d) coverage=%s'
            % (label, roll['files'], roll['reads'], roll['covered'],
               roll['total'], roll['overlap'], roll['bytes'],
               roll['full_file_reads'], roll['excluded'],
               roll['excluded_changed'], roll['excluded_impossible'],
               roll['excluded_no_total'],
               '-' if roll['coverage'] is None else '%.4f' % roll['coverage']))


# This number is not a ranking. A parent that took 30% in slices polluted
# itself; a parent that took 30% because Grep answered the question did
# not. They print the same.
CAVEAT = ('# coverage is what the parent did, not how well it did it: a low'
          ' rate is neither good nor bad, and this is not a ranking')


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print('usage: read_coverage.py <hooklog> [...]', file=sys.stderr)
        return 2
    # Every input is opened before one byte reaches stdout. The salvage in
    # section 9 redirects with `>`, so the shell has already created the
    # CSV: dying mid-write would commit a file that looks like "no data"
    # exactly as the run directories are deleted.
    loaded, unreadable = [], []
    for path in argv:
        try:
            loaded.append((path, load(path)))
        except OSError as problem:
            unreadable.append('%s: %s' % (path, problem.strerror or problem))
    if unreadable:
        print('ERROR: %d of %d inputs could not be read; wrote nothing'
              % (len(unreadable), len(argv)), file=sys.stderr)
        for problem in unreadable:
            print('  ' + problem, file=sys.stderr)
        return 1
    records = [row for _, rows_of in loaded for row in rows_of]
    counted = rows(records)
    parent = rollup(counted, parent=True)
    worker = rollup(counted, parent=False)
    # The CSV is what gets committed; stderr is not. The caveat and the
    # rollup ride in the file itself. Nothing machine-reads these CSVs.
    header = ([] if counted else ['# NO COVERAGE ROWS'])
    header += [_summary('parent', parent), _summary('worker', worker), CAVEAT]
    for note in header:
        print(note)
    writer = csv.DictWriter(sys.stdout, fieldnames=COLUMNS)
    writer.writeheader()
    for row in counted:
        writer.writerow(row)
    for note in header:
        print(note, file=sys.stderr)
    # One `(run, conversation)` is one conversation, so two session ids
    # inside one is the `--resume` split of section 8.7. Counting per input
    # file would miss it (the split lands in two turn logs); counting across
    # the whole input would fire on every multi-case, multi-run invocation
    # and mean nothing.
    talks = {}
    for row in records:
        talks.setdefault((row.get('run'), row.get('conversation')),
                         []).append(row)
    for (where, talk), mine in sorted(talks.items()):
        found = sessions(mine)
        if len(found) > 1:
            print('# WARNING: %d session ids in %s (%s): one conversation'
                  ' split across sessions reads as a lower rate'
                  % (len(found), os.path.join(where or '', talk or ''),
                     ','.join(found)), file=sys.stderr)
    if counted and not any(row['parent'] for row in counted):
        print('# WARNING: no parent rows at all: if the parent test stopped'
              ' matching, what remains is worker rows, which sit near 1.0',
              file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
