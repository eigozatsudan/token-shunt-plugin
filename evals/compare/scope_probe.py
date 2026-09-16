#!/usr/bin/env python3
"""Did a bulk-reader invocation read outside the paths it was given?

Stage 0 of reviews/scope-prevention-design-2026-09-16.md. Not part of the
release gate.

One invocation is one unit: a run of `reader-batch-ambiguous` launches
several, and the failure section 4 of the a-suite review recorded belongs
to the second one.

Two decisions shape this instrument.

The declared set is extracted here, not by `plugin/hooks/reader_scope.py`.
That module is what the measurement judges, so scoring with it would make
the product right by construction. Its reading is reported beside the
probe's as `declared_product`, and a disagreement is an item of its own.

A Read that was attempted and refused still counts as an attempt. The
control arm has no scope refusals at all, so counting only the Reads that
returned content would compare two different quantities.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'plugin', 'hooks'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reader_scope                        # noqa: E402

# The refusal this measurement is about, matched by its text rather than by
# the hook name, so a renamed matcher does not silently stop counting.
SCOPE_DENY = 'Read only the paths this invocation was given'
WORKER = 'token-shunt:bulk-reader'
_TRAILING = '.,;:!?)]}>"\'*`'
_LEADING = '([{<"\'*`'


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


def _text(row):
    content = (row.get('message') or {}).get('content')
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ''
    return '\n'.join(b.get('text', '') for b in content
                     if isinstance(b, dict) and isinstance(b.get('text'), str))


def declared_paths(prompt):
    """Absolute paths named in the launch prompt, as text.

    Existence is deliberately not required: the eval deletes its fixture
    tree between modes, and a path that has since vanished was still
    declared. The product drops those, which is the disagreement the
    measurement records rather than resolves.

    A token counts only if it *begins* with a slash once surrounding
    punctuation is off. The first version took every token from its first
    slash onward, which turned the prompt's own prose -- "the exact
    definition/value of TOKEN" -- into a declared path named "/value".
    Stage 1 filled 11 invocations of 15 with that artifact.
    """
    found = []
    for token in (prompt or '').split():
        candidate = token.lstrip(_LEADING).rstrip(_TRAILING)
        if len(candidate) < 2 or not candidate.startswith('/'):
            continue
        # Resolved the same way the Reads below are, so a disagreement
        # is about which paths are in the set, never about spelling.
        resolved = os.path.realpath(candidate)
        if resolved not in found:
            found.append(resolved)
    return found


def _errored(block):
    """Did this tool result come back as a refusal or failure?

    A Read the three-path cap refused is not a scope refusal, but it did
    not read anything either: counting it as a successful read would credit
    the control arm with reads that never happened.
    """
    if block.get('is_error'):
        return True
    return 'token-shunt:' in _content(block)


def _content(block):
    body = block.get('content')
    if isinstance(body, str):
        return body
    if isinstance(body, list):
        return '\n'.join(b.get('text', '') for b in body
                         if isinstance(b, dict) and isinstance(b.get('text'), str))
    return ''


def score_invocation(transcript, agent_id=None):
    """One worker invocation: what it was given, and what it tried to read."""
    lines = rows(transcript)
    prompt, started_at = '', ''
    for row in lines:
        if row.get('type') == 'user':
            prompt = _text(row)
            started_at = row.get('timestamp') or ''
            break
    declared = declared_paths(prompt)
    product = sorted(reader_scope.declared_paths(
        {'transcript_path': transcript, 'agent_id': agent_id or
         os.path.basename(transcript)[len('agent-'):-len('.jsonl')]}))
    results, reads = {}, []
    for row in lines:
        for block in (row.get('message') or {}).get('content') or []:
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'tool_use' and block.get('name') == 'Read':
                path = (block.get('input') or {}).get('file_path')
                if isinstance(path, str) and path:
                    reads.append((block.get('id'), os.path.realpath(path)))
            elif block.get('type') == 'tool_result':
                results[block.get('tool_use_id')] = (_content(block),
                                                     _errored(block))
    out_of_scope, succeeded, denied, false_refusals, other = [], [], [], [], []
    for call, path in reads:
        got = results.get(call)
        result, errored = got if got else (None, False)
        refused = result is not None and SCOPE_DENY in result
        inside = path in declared
        if not inside and path not in out_of_scope:
            out_of_scope.append(path)
        if refused:
            target = false_refusals if inside else denied
            if path not in target:
                target.append(path)
        elif errored:
            if path not in other:
                other.append(path)
        elif result is not None and path not in succeeded:
            succeeded.append(path)
    return {'agent_id': agent_id, 'transcript': transcript,
            'started_at': started_at,
            'declared': declared, 'declared_product': product,
            # Filled in by score_session, which is where the order of the
            # invocations -- and so what came before this one -- is known.
            'opportunity': None, 'missing_earlier': [],
            # Compared as sets, not against the product's own rule: the
            # vanished-path case is exactly the disagreement A6 records.
            'declared_disagrees': sorted(product) != sorted(declared),
            'read_calls': len(reads), 'out_of_scope': out_of_scope,
            'succeeded': succeeded, 'denied_scope': denied,
            'denied_other': other, 'false_refusals': false_refusals}


def invocations_of(session_path):
    """Every bulk-reader worker transcript under a session, with its id."""
    base = session_path[:-len('.jsonl')] if session_path.endswith('.jsonl') \
        else session_path
    found = []
    for path in sorted(glob.glob(os.path.join(base, 'subagents', 'agent-*.jsonl'))):
        agent = os.path.basename(path)[len('agent-'):-len('.jsonl')]
        meta = os.path.join(os.path.dirname(path), 'agent-%s.meta.json' % agent)
        try:
            with open(meta, encoding='utf-8') as fh:
                kind = json.load(fh).get('agentType')
        except (OSError, ValueError):
            kind = None
        if kind == WORKER:
            found.append((agent, path))
    return found


def score_session(session_path):
    """Every bulk-reader invocation in one session, and the totals.

    `opportunities` is the denominator the prevention rate belongs over: an
    invocation can only re-read what an earlier one touched, and where the
    parent handed the earlier paths over again there is nothing out of
    scope to reach for. Counting those as clean would credit the refusal
    with invocations it never had to refuse.
    """
    scored = [score_invocation(path, agent)
              for agent, path in invocations_of(session_path)]
    # Timestamps order the invocations; the agent id does not. Ties keep
    # the id order so the result is stable.
    scored.sort(key=lambda i: (i['started_at'], i['agent_id'] or ''))
    seen = set()
    for inv in scored:
        inv['missing_earlier'] = sorted(seen - set(inv['declared']))
        inv['opportunity'] = bool(inv['missing_earlier'])
        seen |= set(inv['declared']) | set(inv['succeeded'])
    return {'session': session_path, 'invocations': scored,
            'invocations_total': len(scored),
            'opportunities': sum(1 for i in scored if i['opportunity']),
            'attempted': sum(1 for i in scored if i['out_of_scope']),
            'succeeded': sum(1 for i in scored
                             if set(i['succeeded']) & set(i['out_of_scope'])),
            'denied': sum(1 for i in scored if i['denied_scope']),
            'false_refusals': sum(len(i['false_refusals']) for i in scored),
            'disagreements': sum(1 for i in scored if i['declared_disagrees'])}


def score_dir(run_dir, sessions=None):
    """Every case transcript in a run directory, grouped by `case/mode`."""
    import relapse_probe                    # session_for: same resolution
    transcripts = os.path.join(run_dir, 'transcripts')
    totals = {'runs': 0, 'invocations_total': 0, 'opportunities': 0,
              'attempted': 0,
              'succeeded': 0, 'denied': 0, 'false_refusals': 0,
              'disagreements': 0, 'unmeasured': 0, 'slots': {}}
    if not os.path.isdir(transcripts):
        return totals
    for name in sorted(os.listdir(transcripts)):
        if not name.endswith('.jsonl') or name.endswith('.sendback.jsonl'):
            continue
        stem = name[:-len('.jsonl')]
        if stem.count('.') != 1:
            continue                        # runner start-up probes
        case, mode = stem.split('.')
        path = os.path.join(transcripts, name)
        session = (relapse_probe.session_for(path, sessions)
                   if sessions else relapse_probe.session_for(path))
        totals['runs'] += 1
        if not session:
            totals['unmeasured'] += 1
            continue
        got = score_session(session)
        for key in ('invocations_total', 'opportunities', 'attempted',
                    'succeeded', 'denied',
                    'false_refusals', 'disagreements'):
            totals[key] += got[key]
        totals['slots'].setdefault('%s/%s' % (case, mode), []).append(got)
    return totals


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print('usage: scope_probe.py <run-dir|session.jsonl> [...]',
              file=sys.stderr)
        return 2
    for target in argv:
        # A session file scores on its own: stage 1's run directories were
        # deleted with their worktree, but the sessions they name outlive it.
        got = (score_session(target) if target.endswith('.jsonl')
               else score_dir(target))
        print(json.dumps({target: got}, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
