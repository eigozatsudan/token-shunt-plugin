"""Deny a parent message that resumes a token-shunt worker.

Design row 906: a worker that cannot meet the answer contract reports
partial, and the parent does not resume it -- it launches again with the
same explicit paths (row 447), inside the shared cap of four Agent calls
(row 908). Every other part of that contract is enforced by a hook; this
one was left to the instructions, and a parent resumed a turn-limited
worker anyway (reviews/a-suite-failures-9346d19-2026-09-16.md section 3).

The deny names the allowed move. A worker stops without a report exactly
when resume looks like the repair, so refusing without saying what to do
instead would strand the parent where it already is.

Nothing known means nothing denied: an unreadable or unparsable session
lets the message through rather than blocking one this cannot show to be
a resume.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sendback_session as se  # noqa: E402

WORKERS = ('token-shunt:bulk-reader', 'token-shunt:code-writer')
TOOL = 'SendMessage'


def worker_ids(path):
    """Agent ids this session launched as token-shunt workers."""
    if not isinstance(path, str) or not os.path.isfile(path):
        return set()
    try:
        runs = se.launches(path)
    except Exception:              # a session this cannot read proves nothing
        return set()
    return {r['agent_id'] for r in runs
            if r.get('agent_type') in WORKERS and r.get('agent_id')}


def decide(event):
    """The deny reason for this message, or None to let it through."""
    if event.get('tool_name') != TOOL:
        return None
    inp = event.get('tool_input')
    if not isinstance(inp, dict):
        return None
    target = inp.get('to')
    if not isinstance(target, str) or not target:
        return None
    if target not in worker_ids(event.get('transcript_path')):
        return None
    return ('%s is a token-shunt worker; a worker is not resumed. Ask again '
            'in a new Agent call with the same explicit paths, which counts '
            'against the shared cap of 4. If the cap is reached, report '
            'partial with the paths you could not confirm.' % target)


def main(stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    try:
        event = json.load(stdin)
    except (json.JSONDecodeError, ValueError):
        return 0                   # never fail a turn over this check
    if not isinstance(event, dict):
        return 0
    try:
        reason = decide(event)
    except Exception:
        return 0
    if reason:
        json.dump({'hookSpecificOutput': {
            'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
            'permissionDecisionReason': 'token-shunt: ' + reason}}, stdout)
    return 0


if __name__ == '__main__':
    sys.exit(main())
