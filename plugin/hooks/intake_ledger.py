"""Lock B: a session's cumulative intake limits what the parent may Read.

Design: docs/superpowers/specs/2026-09-19-cumulative-intake-design.md.
The hole is design 26.2 in its multi-turn form: every single Read passes the
per-call threshold and the conversation still ends up holding the corpus.
Measured, 1 of 14 auto conversations took 32,098 bytes across turns 2-4
while the other 13 stayed at or below 8,670
(reviews/multiturn-context-2026-09-18.md section 4-2).

Two halves, like Lock A. PostToolUse adds the bytes a successful parent read
returned. PreToolUse denies the next full-file read when the already
accumulated total is over budget -- it never measures what is about to be
read, because PreToolUse has no `tool_response` and a `st_size` guess would
overcharge every targeted Read. One overshoot is cheaper than one estimate.

Charging is wider than denying (spec 3.3): a targeted Read is charged and
never denied, because two release-gate eval cases reach their Edit through a
targeted Read of the original.

A broken ledger is an empty one, the rule Lock A already follows: unreadable
state, no session, an unwritable directory -- each reads as zero, and zero
denies nothing. This holds the parent's intake down; it has no licence to
break the session.
"""
import errno
import json
import os
from pathlib import Path
import sys
import tempfile

import delegated_paths

BUDGET_BYTES = 16384
BUDGET_ENV = 'TOKEN_SHUNT_SESSION_BUDGET_BYTES'

# The same set check-file-size passes on sight (design 9): what the ledger
# will not charge must not be what it denies over.
BINARY = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.ico', '.tif',
          '.tiff', '.avif', '.heic', '.heif', '.pdf', '.ipynb')

# Marks are spent by the PostToolUse half; a Bash call that never comes back
# would otherwise keep its mark for the rest of the session.
PENDING_MAX = 32

DENY = ('This session has already taken %s bytes of file bodies into the '
        'parent context (budget %s). Reading more here defeats the '
        'delegation this plugin exists for. Hand this path to '
        '/token-shunt:bulk-reader and use its report. The budget does not '
        'reset; delegating is the way forward, not a way to clear it.')

EMPTY = {'bytes': 0, 'reads': 0, 'pending': []}


def state_root(root=None):
    return Path(root) if root else (
        Path(tempfile.gettempdir()) / ('token-shunt-intake-%s' % os.getuid()))


def state_file(session, root=None):
    """Where this session's ledger lives, or None if unusable."""
    return delegated_paths.state_file(session, state_root(root))


def budget(env=None):
    """Bytes a session may take before full reads are refused. 0 disables."""
    raw = (os.environ if env is None else env).get(BUDGET_ENV)
    if raw is None:
        return BUDGET_BYTES
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return BUDGET_BYTES
    return BUDGET_BYTES if value < 0 else value


def ledger(session, root=None):
    """This session's running total. Anything unreadable reads as empty."""
    source = state_file(session, root)
    if not source:
        return dict(EMPTY)
    try:
        with open(source, encoding='utf-8') as fh:
            stored = json.load(fh)
    except (OSError, ValueError):
        return dict(EMPTY)
    if not isinstance(stored, dict):
        return dict(EMPTY)
    taken, reads = stored.get('bytes'), stored.get('reads')
    if not isinstance(taken, int) or isinstance(taken, bool) or taken < 0:
        return dict(EMPTY)
    if not isinstance(reads, int) or isinstance(reads, bool) or reads < 0:
        reads = 0
    pending = [p for p in stored.get('pending', []) if isinstance(p, str)]
    return {'bytes': taken, 'reads': reads, 'pending': pending}


def _write(session, state, root=None):
    """Store the ledger. A ledger that cannot be written charges nothing."""
    target = state_file(session, root)
    if not target:
        return False
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                     | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return False
        return False
    try:
        with os.fdopen(fd, 'w') as fh:
            json.dump(state, fh)
    except OSError:
        return False
    return True


def _parents_own(event):
    """The parent issued this, not a worker sharing the session."""
    return not (event.get('agent_id') or event.get('agent_type'))


def _target(event):
    inp = event.get('tool_input')
    if not isinstance(inp, dict):
        return None
    path = inp.get('file_path')
    return path if isinstance(path, str) and path else None


def _countable(path):
    return not str(path).lower().endswith(BINARY)


def _text(value):
    return value if isinstance(value, str) else ''


def _read_bytes(response, path):
    """UTF-8 bytes a Read put in the parent. An errored read put none."""
    if not isinstance(response, dict) or not _countable(path):
        return 0
    if response.get('is_error') or response.get('error'):
        return 0
    body = response.get('file')
    if isinstance(body, dict):
        return len(_text(body.get('content')).encode('utf-8'))
    return len(_text(response.get('content')).encode('utf-8'))


def _bash_bytes(response):
    if not isinstance(response, dict):
        return 0
    if response.get('is_error') or response.get('error'):
        return 0
    return len(_text(response.get('stdout')).encode('utf-8'))


def charge(event, root=None):
    """Add what a finished parent read returned. Returns the bytes added."""
    if not isinstance(event, dict) or not _parents_own(event):
        return 0
    if event.get('hook_event_name') == 'PostToolUseFailure':
        return 0
    session = event.get('session_id')
    if not isinstance(session, str) or not session:
        return 0
    state = ledger(session, root)
    tool, taken = event.get('tool_name'), 0
    if tool == 'Read':
        path = _target(event)
        if not path:
            return 0
        taken = _read_bytes(event.get('tool_response'), path)
    elif tool == 'Bash':
        # Only the calls check-bash-read recognised as readers are charged.
        # Re-deriving that classification here would mean a second copy of a
        # list whose own comment calls a missing entry a hole.
        call = event.get('tool_use_id')
        if not isinstance(call, str) or call not in state['pending']:
            return 0
        state['pending'] = [p for p in state['pending'] if p != call]
        taken = _bash_bytes(event.get('tool_response'))
    else:
        return 0
    state['bytes'] += taken
    state['reads'] += 1 if taken else 0
    if not _write(session, state, root):
        return 0
    return taken


def mark_reader(event, root=None):
    """Note that this Bash call is a reader, so its output gets charged."""
    if not isinstance(event, dict) or not _parents_own(event):
        return False
    session, call = event.get('session_id'), event.get('tool_use_id')
    if not isinstance(session, str) or not session:
        return False
    if not isinstance(call, str) or not call:
        return False
    state = ledger(session, root)
    if call in state['pending']:
        return True
    state['pending'] = (state['pending'] + [call])[-PENDING_MAX:]
    return _write(session, state, root)


def _over(session, root):
    """Bytes already taken when that is over budget, else None."""
    cap = budget()
    if cap <= 0:
        return None
    taken = ledger(session, root)['bytes']
    return taken if taken > cap else None


def _reason(taken):
    return DENY % (format(taken, ',d'), format(budget(), ',d'))


def deny_reason(event, root=None):
    """Why this Read is refused, or None when it is allowed."""
    if not isinstance(event, dict) or event.get('tool_name') != 'Read':
        return None
    if not _parents_own(event):
        return None
    session = event.get('session_id')
    if not isinstance(session, str) or not session:
        return None
    path = _target(event)
    if not path or not _countable(path):
        return None
    inp = event['tool_input']
    # A targeted Read is charged but never denied: the step 4 edit contract
    # needs one, and denying it would fail release-gate cases from inside.
    if isinstance(inp.get('offset'), int) and isinstance(inp.get('limit'), int):
        return None
    taken = _over(session, root)
    return None if taken is None else _reason(taken)


def bash_deny_reason(event, root=None):
    """Refuse a known reader over budget; otherwise mark it for charging."""
    if not isinstance(event, dict) or event.get('tool_name') != 'Bash':
        return None
    if not _parents_own(event):
        return None
    session = event.get('session_id')
    if not isinstance(session, str) or not session:
        return None
    taken = _over(session, root)
    if taken is not None:
        return _reason(taken)
    mark_reader(event, root)
    return None


def read_main(raw, root=None):
    """PreToolUse on Read: deny an over-budget full read, else say nothing."""
    return _decide(delegated_paths._load(raw), deny_reason, root)


def bash_main(raw, root=None):
    """PreToolUse on a known reader Bash call, from check-bash-read."""
    return _decide(delegated_paths._load(raw), bash_deny_reason, root)


def _decide(event, judge, root):
    if event is None:
        return ''
    try:
        reason = judge(event, root)
    except Exception:
        return ''              # a ledger that cannot be read denies nothing
    if not reason:
        return ''
    return json.dumps({'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': 'token-shunt: ' + reason}})


def record_main(raw, root=None):
    """PostToolUse on Read / Bash: charge, say nothing."""
    event = delegated_paths._load(raw)
    if event is not None:
        try:
            charge(event, root)
        except Exception:
            pass            # a ledger that cannot be written denies nothing
    return ''


def main(which, stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    handler = {'read': read_main, 'bash': bash_main}.get(which, record_main)
    out = handler(stdin.read())
    if out:
        stdout.write(out)
    return 0
