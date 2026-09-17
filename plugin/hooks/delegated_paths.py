"""Lock A: a path handed to a worker stops being the parent's to Read.

Design: reviews/delegated-read-lock-design-2026-09-17.md section 2.

`check-file-size` passes a targeted Read on purpose -- the step 4 edit
contract needs one -- so the skill was the only thing asking the parent not
to read what it had delegated, and with the wording pinned 13 of 60 delegate
arms still did (reviews/parent-no-read-rate-2026-09-17.md).

Two halves. The launch records the absolute paths it handed over, keyed by
session. The parent's later Read of one of them is denied; the worker's is
not, because the worker shares the session and denying it would deny the
delegation itself.

Nothing known means nothing denied, the rule `reader_scope` already follows:
an unwritable or unparsable state, a prompt with no path, a path that does
not exist -- each yields an empty set, and an empty set refuses nothing. A
lock that fails closed would break every Read in the session over a
tempfile.

This prevents; it does not judge. Whether the answer came from the worker is
`parent_no_read`'s question, in the eval.
"""
import errno
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

WORKERS = ('token-shunt:bulk-reader', 'token-shunt:code-writer')
TOOLS = ('Agent', 'Task')

# `reader_scope.declared_paths` scans a launch prompt the same way, but from
# the worker's transcript and for a different decision. Sharing one helper
# would mean editing that module for this one; the ten lines are copied
# deliberately, and the trailing set is kept identical on purpose.
_TRAILING = '.,;:!?)]}>"\'*'

DENY = ('%s is already with a worker. That worker read it; its report is '
        'the answer. If you need more from this file, start a new worker '
        'call with the same path -- do not read it here to check, to '
        'finish, or because it is small enough to pass.')


def paths_in(text):
    """Existing absolute paths named in a launch prompt, resolved."""
    if not isinstance(text, str):
        return set()
    found = set()
    for token in text.split():
        start = token.find('/')
        if start < 0:
            continue
        candidate = token[start:].strip(_TRAILING).rstrip('`')
        if candidate and os.path.isfile(candidate):
            found.add(os.path.realpath(candidate))
    return found


def launched(response):
    """Did this call actually start a worker? Same reading as worker_launch."""
    if isinstance(response, dict):
        return not response.get('error')
    if isinstance(response, str):
        return 'error' not in response.lower()
    return True


def state_root(root=None):
    return Path(root) if root else (
        Path(tempfile.gettempdir()) / ('token-shunt-delegated-%s' % os.getuid()))


def state_file(session, root=None):
    """Where this session's locked paths live, or None if unusable."""
    if not isinstance(session, str) or not session:
        return None
    base = state_root(root)
    try:
        base.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = base.lstat()
        if base.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            return None
    except OSError:
        return None
    return base / (hashlib.sha256(session.encode()).hexdigest() + '.json')


def locked(session, root=None):
    """The paths this session has delegated. Unreadable state is empty."""
    source = state_file(session, root)
    if not source:
        return set()
    try:
        with open(source, encoding='utf-8') as fh:
            stored = json.load(fh)
    except (OSError, ValueError):
        return set()
    if not isinstance(stored, list):
        return set()
    return {p for p in stored if isinstance(p, str)}


def record(event, root=None):
    """Lock the paths a successful worker launch carried. Returns the set."""
    if not isinstance(event, dict) or event.get('tool_name') not in TOOLS:
        return set()
    inp = event.get('tool_input')
    if not isinstance(inp, dict) or inp.get('subagent_type') not in WORKERS:
        return set()
    if not launched(event.get('tool_response')):
        return set()
    paths = paths_in(inp.get('prompt'))
    if not paths:
        return set()
    source = state_file(event.get('session_id'), root)
    if not source:
        return set()
    merged = locked(event.get('session_id'), root) | paths
    try:
        fd = os.open(source, os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                     | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return set()
        return set()
    try:
        with os.fdopen(fd, 'w') as fh:
            json.dump(sorted(merged), fh)
    except OSError:
        return set()
    return paths


def deny_reason(event, root=None):
    """Why this Read is refused, or None when it is allowed."""
    if not isinstance(event, dict) or event.get('tool_name') != 'Read':
        return None
    # The worker shares the session. Its Read is the delegation working.
    if event.get('agent_id'):
        return None
    inp = event.get('tool_input')
    if not isinstance(inp, dict):
        return None
    target = inp.get('file_path')
    if not isinstance(target, str) or not target:
        return None
    try:
        resolved = os.path.realpath(target)
    except OSError:
        return None
    if resolved not in locked(event.get('session_id'), root):
        return None
    return DENY % target


def _load(raw):
    try:
        event = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return event if isinstance(event, dict) else None


def launch_main(raw, root=None):
    """PostToolUse on Agent|Task: record, say nothing."""
    event = _load(raw)
    if event is not None:
        try:
            record(event, root)
        except Exception:
            pass                   # a lock that cannot be written denies nothing
    return ''


def read_main(raw, root=None):
    """PreToolUse on Read: deny a delegated path, else say nothing."""
    event = _load(raw)
    if event is None:
        return ''
    try:
        reason = deny_reason(event, root)
    except Exception:
        return ''
    if not reason:
        return ''
    return json.dumps({'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': 'token-shunt: ' + reason}})


def main(which, stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    out = (read_main if which == 'read' else launch_main)(stdin.read())
    if out:
        stdout.write(out)
    return 0
