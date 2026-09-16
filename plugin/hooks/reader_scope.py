"""The set of paths one bulk-reader invocation was asked to read.

`check-reader-contract` can count paths but not recognize them, so a second
invocation that re-reads a path from the first passes its gate (section 4 of
reviews/a-suite-failures-9346d19-2026-09-16.md). The declared set is not on
the hook's stdin, but the stdin names the session and the agent, and the
launch prompt is the first user message of that agent's own transcript.

Nothing known means nothing denied: an unreadable transcript, a prompt with
no absolute path, or a named file that does not exist yields an empty scope,
and an empty scope refuses nothing.
"""
import json
import os


MAX_LINES = 64          # The launch prompt is the first user row of the file.
MAX_BYTES = 1 << 18
_TRAILING = '.,;:!?)]}>"\'*'


def scope_file(event):
    """The transcript of the agent this event belongs to, or None."""
    path, agent = event.get('transcript_path'), event.get('agent_id')
    if not (isinstance(path, str) and path and isinstance(agent, str) and agent):
        return None
    name = 'agent-%s.jsonl' % agent
    if os.path.basename(path) == name:
        return path if os.path.isfile(path) else None
    base = path[:-len('.jsonl')] if path.endswith('.jsonl') else path
    child = os.path.join(base, 'subagents', name)
    return child if os.path.isfile(child) else None


def _text(row):
    message = row.get('message')
    if not isinstance(message, dict) or message.get('role') not in (None, 'user'):
        return None
    content = message.get('content')
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(b.get('text', '') for b in content
                         if isinstance(b, dict) and isinstance(b.get('text'), str))
    return None


def launch_prompt(event):
    """The text of the first user message in the agent's transcript."""
    path = scope_file(event)
    if not path:
        return None
    try:
        with open(path, encoding='utf-8', errors='replace') as source:
            for _ in range(MAX_LINES):
                line = source.readline(MAX_BYTES)
                if not line:
                    return None
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict) or row.get('type') != 'user':
                    continue
                return _text(row)
    except OSError:
        return None
    return None


def declared_paths(event):
    """Existing absolute paths named in the launch prompt, resolved."""
    text = launch_prompt(event)
    if not text:
        return set()
    found = set()
    for token in text.split():
        start = token.find('/')
        if start < 0:
            continue
        candidate = token[start:].strip(_TRAILING).rstrip('`')
        # A path that does not exist cannot be what is being read, and keeping
        # it in the scope would not change any decision.
        if candidate and os.path.isfile(candidate):
            found.add(os.path.realpath(candidate))
    return found


def scope_reason(scope, path):
    """Why `path` is outside `scope`, or None when it is allowed."""
    if not scope:
        return None
    if os.path.realpath(path) in scope:
        return None
    return ('Read only the paths this invocation was given: %s. This path came '
            'from another invocation; report partial and let the caller ask for '
            'it in a new one.' % ', '.join(sorted(scope)))


def out_of_scope(event, path):
    return scope_reason(declared_paths(event), path)
