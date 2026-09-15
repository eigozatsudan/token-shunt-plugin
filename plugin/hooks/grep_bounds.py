"""Hold a content Grep on an over-budget file to the §26.5 form.

Two rules the evaluation could only judge after the fact
(`evals/compare/flow_checks.py:position_grep_errors`), moved in front of
the call:

  metadata first   a file past the small-task budget may be content
                   searched only after its size is known to the caller
  bounded output   that search returns `files_with_matches`, or
                   `head_limit` 1-20 with no context window (-A/-B/-C, context)

Only a single existing file is judged. A directory, a bare cwd search and
a `glob` set do not resolve to one size here, and enumerating them at
PreToolUse would cost more than the rule is worth; they pass untouched,
which leaves that part of §26.5 unenforced rather than guessed at
(reviews/enforcement-design-2026-09-15.md §1.2).

"Known size" is session state, not a property of the file, so it is
recorded when the caller is actually told: a `stat`/`wc -c` it ran, or a
Read deny whose contract named the path with its byte count. A successful
Read does not count -- receiving a body is not judging metadata. State
lost to a compact or a new session reads as unmeasured: the caller pays
one round trip rather than the rule quietly lapsing (§3.3).

Relative paths mean whatever they meant to the caller, so the entry point
moves to the event's `cwd` first and everything here is absolute. Judging
the hook process's own directory instead would let a same-named file that
happens to be small pass a search on the big one.
"""
import os
import re
import shlex

BUDGET = 16384
HEAD_LIMIT_MAX = 20
DENY_CAP = 6
# Every spelling of a context window the Grep schema accepts. `context`
# is that schema's name for rg's -C; naming only the dashed flags left the
# window that the tool actually documents unbounded.
CONTEXT_FLAGS = ('-A', '-B', '-C', 'context')
# Metadata commands whose operands are files the caller has just measured.
_STAT_FLAG = re.compile(r'^-[A-Za-z]+$|^--[A-Za-z-]+(=.*)?$')
# Flags whose value is the next word, not a file: stat's format strings.
# `wc -c` is the byte count itself, so this is keyed by command.
_TAKES_VALUE = {'stat': ('-c', '--format', '--printf'), 'wc': ()}
# A size the caller was never shown is not a measurement. `stat` prints one
# by default, but a format string prints exactly what it names, so the
# format has to name the size; `%%` is a literal percent, not a directive.
_SIZE_DIRECTIVE = re.compile(r'%[-#0 +\']*[0-9]*s')
_STAT_FORMAT = ('-c', '--format', '--printf')
_UNSAFE = set('$`|;&<>()#\n\\*?[]{}!~')
# The writer has Read, Write, Grep, Glob and no Bash, and check-file-size
# exempts its Reads, so neither way of learning a size is open to it. It is
# still held to the bound, but never sent down a route it does not have.
CODE_WRITER = 'token-shunt:code-writer'


def new_state():
    return {'measured': {}, 'denials': 0}


def _key(st):
    return '%d:%d' % (st.st_dev, st.st_ino)


def target_file(inp, isfile=os.path.isfile):
    """The one file this Grep searches, or None if it is not one file."""
    if inp.get('glob'):
        return None
    path = inp.get('path')
    if not isinstance(path, str) or not path:
        return None
    # Absolute from here on: the caller's relative path is resolved against
    # the session cwd the entry point already moved to, and the state key,
    # the deny text and the `wc -c` it suggests must all name that file.
    path = os.path.abspath(path)
    return path if isfile(path) else None


def record(state, path, source, stat=os.stat):
    """Note that the caller has been told this file's size."""
    try:
        st = stat(path)
    except OSError:
        return False
    state.setdefault('measured', {})[_key(st)] = {
        'path': os.path.abspath(path), 'size': st.st_size,
        'mtime_ns': st.st_mtime_ns, 'source': source}
    return True


def is_measured(state, path, stat=os.stat):
    """Is the record still about the file that is there now?

    Size and mtime are compared as well as the inode: an inode that has
    been reused names a different file, and a file that changed after the
    measurement has a size the caller was never told.
    """
    try:
        st = stat(path)
    except OSError:
        return False
    got = (state.get('measured') or {}).get(_key(st))
    return bool(got and got.get('size') == st.st_size
                and got.get('mtime_ns') == st.st_mtime_ns)


def _stat_shows_size(rest):
    """Does this `stat` print the byte count of its operands?

    Bare `stat` does. A format string prints only what it names, so it
    must contain a `%s` directive -- `stat -c %n` names the path alone.
    `-f` describes the filesystem rather than the file and never does.
    """
    formats = []
    take = False
    for word in rest:
        if take:
            formats.append(word)
            take = False
            continue
        if word in ('-f', '--file-system'):
            return False
        if word in _STAT_FORMAT:
            take = True
        elif any(word.startswith(f + '=') for f in _STAT_FORMAT):
            formats.append(word.split('=', 1)[1])
    return all(_SIZE_DIRECTIVE.search(f.replace('%%', '')) for f in formats)


def metadata_paths(command):
    """File operands of a bare `stat`/`wc -c`, or [] for anything else.

    Deliberately narrow: anything a shell could expand, chain or redirect
    is not read at all. Missing a measurement costs one round trip;
    recording one that never happened would license an unbounded search.
    """
    if not isinstance(command, str) or not command.strip():
        return []
    if _UNSAFE & set(command):
        return []
    try:
        words = shlex.split(command)
    except ValueError:
        return []
    if not words:
        return []
    base = os.path.basename(words[0])
    if base not in ('stat', 'wc'):
        return []
    rest = words[1:]
    if base == 'wc' and not any(w in ('-c', '--bytes') for w in rest):
        return []
    if base == 'stat' and not _stat_shows_size(rest):
        return []
    paths = []
    skip = False
    for word in rest:
        if skip:
            skip = False
            continue
        if word == '--':
            continue
        if _STAT_FLAG.match(word):
            skip = word in _TAKES_VALUE[base]
            continue
        paths.append(word)
    return paths


def _form_error(inp):
    limit = inp.get('head_limit')
    context = 0
    for flag in CONTEXT_FLAGS:
        value = inp.get(flag)
        if isinstance(value, int) and not isinstance(value, bool):
            context = max(context, value)
    if limit is None:
        return ('this content search has no bound. Use '
                'output_mode="files_with_matches", or head_limit 1-%d'
                % HEAD_LIMIT_MAX)
    if isinstance(limit, bool) or not isinstance(limit, int) \
            or not 1 <= limit <= HEAD_LIMIT_MAX:
        return ('head_limit=%r is not a bound a reader can act on. Use a '
                'whole number 1-%d' % (limit, HEAD_LIMIT_MAX))
    if context:
        # A context window multiplies the returned lines, so head_limit
        # no longer bounds the output.
        return ('head_limit with a %d-line context window does not bound '
                'the returned lines. Drop -A/-B/-C and context' % context)
    return None


def decide(event, state, stat=os.stat, isfile=os.path.isfile):
    """The deny reason for this Grep, or None to let it through."""
    if event.get('tool_name') != 'Grep':
        return None
    inp = event.get('tool_input')
    if not isinstance(inp, dict):
        return None
    if str(inp.get('output_mode') or '') != 'content':
        return None                       # files_with_matches is the bound
    path = target_file(inp, isfile)
    if path is None:
        return None
    try:
        size = stat(path).st_size
    except OSError:
        return None                       # Grep will fail on its own terms
    if size <= BUDGET:
        return None                       # the small-task edit path (§11.6)
    writer = event.get('agent_type') == CODE_WRITER
    if state.get('denials', 0) >= DENY_CAP:
        if writer:
            return ('this search has been refused %d times. Stop searching '
                    '%s: use output_mode="files_with_matches", or Read the '
                    'range you need, and report what you could not confirm.'
                    % (DENY_CAP, path))
        return ('this search has been refused %d times. Stop searching %s '
                'and report partial, or delegate it to '
                '/token-shunt:bulk-reader.' % (DENY_CAP, path))
    if not is_measured(state, path, stat):
        if writer:
            return ('%s is over the %d B budget and its size is not known '
                    'here. Use output_mode="files_with_matches" to locate '
                    'it, or Read the range you need.' % (path, BUDGET))
        return ('%s is over the %d B budget and its size has not been '
                'checked in this session. Run `wc -c %s` (or a Read that '
                'the size hook refuses) first, then search it.'
                % (path, BUDGET, path))
    form = _form_error(inp)
    if form:
        return '%s (%d B, over budget): %s' % (path, size, form)
    return None
