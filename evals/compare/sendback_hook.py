#!/usr/bin/env python3
"""Trial Stop hook: send a parent back when it dropped a worker's lines.

This is the trial instrument described in
`reviews/sendback-trial-spec-2026-09-15.md`, not a product hook. It is
deliberately NOT registered in `plugin/hooks/hooks.json`: wiring it up is
part of setting up the billable trial, and until then the plugin must
behave exactly as it does today.

It blocks only where the offline checks can actually judge the parent
(spec section 1): worker output obtained, worker items usable, final
answer identified, and a line-retention violation. Anything undetermined,
and any failure on the worker's side, returns success -- sending those
back would break answers that are correct.

Every invocation appends one JSON record to the trial log, including the
counts that section 4.1 uses as evidence of resumption. The record is what
the trial reads afterwards; the hook itself concludes nothing about why a
parent did or did not resume.
"""
import json
import os
import sys

import retention_checks as rc
import session_extract as se

LOG_ENV = 'SENDBACK_TRIAL_LOG'

BLOCKED = 'blocked'
NO_BLOCK = 'no_block'
SUPPRESSED = 'reblock_suppressed'
EARLY = 'early_stop'

# Statuses the CLI reports for work that has not finished. A stop while one
# of these is outstanding is a pause, not the end of the answer.
PENDING = ('running', 'pending', 'in_progress', 'queued', 'backgrounded')


def parent_progress(rows):
    """What counts as the parent having acted, per spec section 4.1.

    Assistant replies and the parent's own tool calls are the evidence of
    a resumption. Transcript line counts are not: a hook record, a task
    notification or a meta update grows the file without the parent having
    said anything, so lines are carried only as auxiliary information.
    """
    replies = calls = 0
    for entry in rows:
        if entry.get('type') != 'assistant' or entry.get('isSidechain'):
            continue
        replies += 1
        for block in (entry.get('message') or {}).get('content') or []:
            if isinstance(block, dict) and block.get('type') == 'tool_use':
                calls += 1
    return {'assistant_replies': replies, 'tool_calls': calls,
            'transcript_lines': len(rows)}


def resumption(baseline, rows):
    """Did the parent respond after the block?

    'resumed' requires a new parent reply or a new parent tool call.
    Otherwise the cause is left open: a transcript does not distinguish a
    discarded block from any other reason the parent stayed silent, so the
    trial records `cause_unknown` rather than naming the discard path.
    """
    now = parent_progress(rows)
    grew = (now['assistant_replies'] > baseline.get('assistant_replies', 0)
            or now['tool_calls'] > baseline.get('tool_calls', 0))
    return {'status': 'resumed' if grew else 'not_resumed',
            'cause': '' if grew else 'cause_unknown',
            'before': baseline, 'after': now,
            # Auxiliary only. Lines can grow without the parent acting.
            'line_growth': now['transcript_lines']
                           - baseline.get('transcript_lines', 0)}


def in_flight_workers(event):
    """Subagent tasks the CLI reports as still outstanding at this stop.

    The Stop hook also fires while a worker is still running -- the parent's
    turn ends and resumes when the report arrives. The lines that worker has
    not delivered yet are not lines the parent dropped, so such a stop is
    recorded apart and never judged.
    """
    out = []
    for task in event.get('background_tasks') or []:
        if not isinstance(task, dict):
            continue
        if task.get('type') != 'subagent':
            continue
        if str(task.get('status', '')).lower() in PENDING:
            out.append({'id': task.get('id'),
                        'agent_type': task.get('agent_type'),
                        'status': task.get('status')})
    return out


def final_from_event(event, rows):
    """The answer this stop is about, preferring what the CLI handed us.

    The Stop input carries `last_assistant_message`, the text of the message
    the turn is ending on, which is why the trial's transcript reading failed:
    at hook time that message is not in the session file yet.

    It is used only when it is the CURRENT turn's text. If the same text
    already appears before the last interruption, it is narration from an
    earlier turn -- the CLI hands over the last assistant message, which need
    not be a turn-ending one when the turn ended on a tool result. Such a
    stop is left unidentified rather than judged against stale text.
    """
    said = event.get('last_assistant_message')
    if isinstance(said, str) and said.strip():
        cut = -1
        for i, entry in enumerate(rows):
            if se._is_interruption(entry):
                cut = i
        earlier = set()
        for entry in rows[:cut + 1]:
            if entry.get('type') != 'assistant' or entry.get('isSidechain'):
                continue
            for block in (entry.get('message') or {}).get('content') or []:
                if isinstance(block, dict) and block.get('type') == 'text' \
                        and block.get('text'):
                    earlier.add(rc.normalize(block['text']))
        if rc.normalize(said) in earlier:
            return None, 'last_assistant_message repeats earlier narration'
        return said, 'last_assistant_message'
    got = se.final_answer_from_rows(rows)
    if got['status'] == 'ok':
        return got['text'], 'transcript'
    return None, 'final answer not identified'


def block_reason(lost):
    head = ('Your answer dropped lines the reader worker confirmed. Restate '
            'every line below verbatim, each on its own line, before you '
            'finish:')
    return '\n'.join([head] + list(lost))


def decide(event):
    """The hook's whole decision, as a record. No I/O."""
    rec = {'event': event.get('hook_event_name'),
           'session_id': event.get('session_id'),
           'transcript_path': event.get('transcript_path'),
           'stop_hook_active': bool(event.get('stop_hook_active'))}
    if event.get('hook_event_name') != 'Stop' or event.get('agent_id'):
        # A SubagentStop (the CLI converts a Stop hook into one for a
        # subagent) is a worker concluding, not the parent's answer. The
        # parent contract must not be applied to it.
        rec.update(outcome=NO_BLOCK, reason='not a parent Stop',
                   agent_id=event.get('agent_id'))
        return rec, {}
    if rec['stop_hook_active']:
        # The documented contract: return success while this is true. That
        # is the hook declining to re-block -- NOT an observation that the
        # CLI hit its cap (spec section 4.4).
        rec.update(outcome=SUPPRESSED, reason='stop_hook_active')
        return rec, {}
    waiting = in_flight_workers(event)
    if waiting:
        # Not a no_block verdict on the parent: there is no finished answer
        # to judge yet, and the missing lines are still in transit.
        rec.update(outcome=EARLY, reason='worker still running',
                   in_flight=waiting)
        return rec, {}
    path = event.get('transcript_path')
    if not path or not os.path.isfile(path):
        rec.update(outcome=NO_BLOCK, reason='no transcript to read')
        return rec, {}
    rows = se.read_jsonl(path)
    final, source = final_from_event(event, rows)
    got = se.check_inputs(path)
    checks = rc.run_all(got['child_texts'], final)
    rec['checks'] = {k: v['status'] for k, v in checks.items()}
    rec['final_identified'] = final is not None
    rec['final_source'] = source
    if got['child_texts'] is None:
        rec.update(outcome=NO_BLOCK, reason='worker output unobtainable')
        return rec, {}
    if final is None:
        rec.update(outcome=NO_BLOCK, reason=source)
        return rec, {}
    if checks['child_items']['status'] != rc.OK:
        rec.update(outcome=NO_BLOCK,
                   reason='worker side: %s' % checks['child_items']['status'])
        return rec, {}
    lr = checks['line_retention']
    if lr['status'] != rc.VIOLATION:
        rec.update(outcome=NO_BLOCK, reason='retention %s' % lr['status'])
        return rec, {}
    lost = lr['demoted'] + lr['altered'] + lr['dropped']
    rec.update(outcome=BLOCKED, reason=lr['reason'], lost_lines=len(lost),
               kept_lines=len(lr['kept']),
               baseline=parent_progress(se.read_jsonl(path)))
    return rec, {'decision': 'block', 'reason': block_reason(lost)}


def log(rec, path=None):
    path = path or os.environ.get(LOG_ENV)
    if not path:
        return
    with open(path, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + '\n')


def main(stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    try:
        event = json.load(stdin)
    except (json.JSONDecodeError, ValueError):
        log({'outcome': NO_BLOCK, 'reason': 'unparsable hook input'})
        json.dump({}, stdout)
        return 0
    try:
        rec, out = decide(event)
    except Exception as exc:           # never fail a turn over the trial
        log({'outcome': NO_BLOCK, 'reason': 'hook error: %s' % exc})
        json.dump({}, stdout)
        return 0
    log(rec)
    json.dump(out, stdout)
    return 0


if __name__ == '__main__':
    sys.exit(main())
