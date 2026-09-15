"""Trial Stop hook: send a parent back when it dropped a worker's lines.

It lives with the plugin so it ships with it, but it is still NOT
registered in `plugin/hooks/hooks.json`. Registration waits on the
remaining conditions in `reviews/sendback-registration-decision-2026-09-15.md`;
until then the plugin behaves exactly as it does today. `check-final-answer`
is the executable a registration would name.

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

import sendback_retention as rc
import sendback_session as se

LOG_ENV = 'SENDBACK_TRIAL_LOG'
SIZE_ENV = 'TOKEN_SHUNT_SESSION_MAX_BYTES'
SWITCH_ENV = 'TOKEN_SHUNT_SENDBACK'
OFF = ('off', '0', 'false', 'no')

# The hook runs at every turn end and a session file only grows. The cap
# bounds the worst case rather than excluding ordinary work: the largest
# session on hand when this was written was 17 MB, which parses once in
# about 0.15 s, so 64 MB is roughly four times the observed ceiling and
# still well under a second. Over it, the parent is left alone.
DEFAULT_MAX_BYTES = 64 * 1024 * 1024

# The oldest CLI whose Stop payload was verified to carry
# `last_assistant_message` (see the registration decision, section 3.3).
# Not a claim about when the field appeared: it is the oldest build that
# could be checked here, and every build from it to 2.1.272 declares the
# field identically.
VERSION_FLOOR = (2, 1, 269)

DISABLED = 'disabled'
TOO_LARGE = 'too_large'
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


def enabled():
    """Whether this turn end is judged at all.

    On by default: that is the product's behaviour. The comparison eval
    turns it off so its baseline keeps measuring the skills rather than
    the send-back (decision section 3.4). The runner sets the variable
    itself after clearing every TOKEN_SHUNT_* name, so a caller's
    environment cannot decide this for it.
    """
    return os.environ.get(SWITCH_ENV, '').strip().lower() not in OFF


def parse_version(text):
    """'2.1.272' -> (2, 1, 272); anything else -> None."""
    if not isinstance(text, str):
        return None
    parts = text.split('.')[:3]
    if len(parts) < 3 or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def cli_version(rows):
    """The CLI that wrote the session, from its own rows.

    The Stop payload carries no version, but every assistant and user row
    records the build that wrote it, and the newest of those is the CLI
    running now. It costs nothing: the rows are already parsed.
    """
    for entry in reversed(rows):
        got = entry.get('version')
        if isinstance(got, str) and got:
            return got
    return None


def max_bytes():
    raw = os.environ.get(SIZE_ENV)
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_BYTES
    return val if val > 0 else DEFAULT_MAX_BYTES


def block_reason(lost):
    # The text names token-shunt: it is what the parent (and anyone reading
    # the transcript) sees, and the eval's isolation check attributes a
    # hook response by its payload, not by the matcher name.
    head = ('token-shunt: your answer dropped lines the reader worker '
            'confirmed. Restate '
            'every line below verbatim, each on its own line, before you '
            'finish:')
    return '\n'.join([head] + list(lost))


def decide(event):
    """The hook's whole decision, as a record. No I/O."""
    rec = {'event': event.get('hook_event_name'),
           'session_id': event.get('session_id'),
           'transcript_path': event.get('transcript_path'),
           'stop_hook_active': bool(event.get('stop_hook_active'))}
    if not enabled():
        # Nothing is read, so a disabled hook costs one process start.
        rec.update(outcome=DISABLED, reason='%s is off' % SWITCH_ENV)
        return rec, {}
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
    cap = max_bytes()
    try:
        # One parse of the session, reused for the final answer, the worker
        # correlation and the resumption baseline.
        rows = se.read_jsonl(path, cap)
        got = se.check_inputs(path, rows=rows, max_bytes=cap)
    except se.TooLarge as exc:
        rec.update(outcome=TOO_LARGE, reason=str(exc), size=exc.size, cap=cap)
        return rec, {}
    final, source = final_from_event(event, rows)
    checks = rc.run_all(got['child_texts'], final)
    rec['checks'] = {k: v['status'] for k, v in checks.items()}
    rec['final_identified'] = final is not None
    rec['final_source'] = source
    version = cli_version(rows)
    parsed = parse_version(version)
    rec['cli_version'] = version
    # Recorded on every invocation, so a build that stops supplying the
    # field is visible in the log instead of quietly blocking nothing.
    rec['below_version_floor'] = bool(parsed and parsed < VERSION_FLOOR)
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
    if source != 'last_assistant_message':
        # The only answer in hand came from the session file, and at hook
        # time the message ending this turn is not in it yet -- what was
        # read is an earlier turn's text. Blocking on it would invent a
        # violation, so a transcript-sourced answer is recorded and left
        # alone. This is also what an older CLI, one that does not supply
        # the field, falls back to (section 3.3).
        rec.update(outcome=NO_BLOCK,
                   reason='retention violation seen, but the answer came '
                          'from the transcript, not from the Stop input '
                          '(cli %s)' % (version or 'unknown'))
        return rec, {}
    lost = lr['demoted'] + lr['altered'] + lr['dropped']
    rec.update(outcome=BLOCKED, reason=lr['reason'], lost_lines=len(lost),
               kept_lines=len(lr['kept']),
               baseline=parent_progress(rows))
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
        return 0
    try:
        rec, out = decide(event)
    except Exception as exc:           # never fail a turn over the trial
        log({'outcome': NO_BLOCK, 'reason': 'hook error: %s' % exc})
        return 0
    log(rec)
    if out:
        json.dump(out, stdout)
    # Nothing to say is said by saying nothing: an empty response keeps the
    # turn end clean for anything reading hook output.
    return 0
