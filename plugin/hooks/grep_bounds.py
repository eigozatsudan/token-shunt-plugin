"""Hold a content Grep on an over-budget file to the §26.5 form.

Two rules moved in front of the call:

  metadata first   a file past the small-task budget may be content
                   searched only after its size is known to the caller
  bounded output   that search returns `files_with_matches`, or
                   `head_limit` 1-20 with no context window (-A/-B/-C, context)

Only the second has a counterpart in the harness
(`evals/compare/flow_checks.py:position_grep_errors`, and only for cases
that declare `edit_flow`). Metadata-first is judged here and nowhere
else, so a run made without the plugin is not measured against it.

Only a single existing file is judged. A directory and a bare cwd search
do not resolve to one size here, and enumerating them at
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
# A size the caller was never shown is not a measurement. `stat` prints one
# by default, but a format string prints exactly what it names, so the
# format has to name the size; `%%` is a literal percent, not a directive.
_SIZE_DIRECTIVE = re.compile(r'%[-#0 +\']*[0-9]*s')
_STAT_FORMAT = ('-c', '--format', '--printf')
# `stat -c%s` and `stat -Lc%s`: GNU takes the format attached to the flag.
_STAT_ATTACHED = re.compile(r'^-L?c(.+)$')
_UNSAFE = set('$`|;&<>()#\n\\*?[]{}!~')
# The writer has Read, Write, Grep, Glob and no Bash, and check-file-size
# exempts its Reads, so neither way of learning a size is open to it. It is
# still held to the bound, but never sent down a route it does not have.
CODE_WRITER = 'token-shunt:code-writer'


def new_state():
    return {'measured': {}, 'denials': {}}


def _denials(state):
    """The per-path refusal counts, keyed like `measured`.

    A scope-wide integer is what older sessions hold. It cannot say which
    path earned it, so it is not carried: capping a path that was never
    refused is the defect this replaced
    (reviews/deny-cap-evidence-2026-09-16.md section 4).
    """
    counts = state.get('denials')
    return counts if isinstance(counts, dict) else {}


def note_denial(event, state, stat=os.stat, isfile=os.path.isfile):
    """Count one refusal against the path the message named."""
    key = denial_key(event, stat, isfile)
    if key is None:
        return
    counts = _denials(state)
    counts[key] = counts.get(key, 0) + 1
    state['denials'] = counts


def denial_key(event, stat=os.stat, isfile=os.path.isfile):
    """File identity of the Grep target, or None when there is not one."""
    inp = event.get('tool_input')
    if not isinstance(inp, dict):
        return None
    path = target_file(inp, isfile)
    if path is None:
        return None
    try:
        return _key(stat(path))
    except OSError:
        return None


def _key(st):
    return '%d:%d' % (st.st_dev, st.st_ino)


def target_file(inp, isfile=os.path.isfile):
    """The one file this Grep searches, or None if it is not one file.

    A `glob` beside a `path` that names one file does not make the size
    uncertain: the glob can only decide whether that one file is searched.
    Treating any glob as out of scope put the escape from this rule one
    extra key away from the call that had just been refused.
    """
    path = inp.get('path')
    if not isinstance(path, str) or not path:
        return None
    # Absolute from here on: the caller's relative path is resolved against
    # the session cwd the entry point already moved to, and the state key,
    # the deny text and the `wc -c` it suggests must all name that file.
    path = os.path.abspath(path)
    return path if isfile(path) else None


def follows_links(command):
    """Did this metadata command report the target of a symlink?

    `wc -c` reads through the link; `stat` describes the link itself
    unless asked not to. Recording the target from a bare `stat` marked a
    large file measured on the strength of the link's own tiny size.
    """
    if not isinstance(command, str):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    if not words or os.path.basename(words[0]) != 'stat':
        return True                       # `wc -c` follows
    return any(w in ('-L', '--dereference') for w in words[1:])


def record(state, path, source, stat=os.stat, follow=True):
    """Note that the caller has been told this file's size."""
    if not follow and os.path.islink(path):
        return False
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


def _stat_operands(rest):
    """Files a `stat` showed a size for, or None if we cannot tell.

    Bare `stat` prints one. A format string prints exactly what it names,
    so it has to name the size, in whichever spelling GNU accepts:
    `-c %s`, `-c%s`, `-Lc%s`, `--format=%s`, `--printf=%s`. Any other
    option -- `-f` for the filesystem, `-t` for the terse line, anything
    unknown -- reads as "we do not know what this printed", and nothing
    is recorded. A missed record costs the caller one `wc -c`; a wrong
    one licenses an unbounded search.
    """
    paths, formats = [], []
    take = operands_only = False
    for word in rest:
        if take:
            formats.append(word)
            take = False
        elif operands_only or not word.startswith('-') or word == '-':
            paths.append(word)
        elif word == '--':
            operands_only = True
        elif word in ('-L', '--dereference'):
            continue
        elif word in _STAT_FORMAT:
            take = True
        elif any(word.startswith(f + '=') for f in _STAT_FORMAT):
            formats.append(word.split('=', 1)[1])
        else:
            attached = _STAT_ATTACHED.match(word)
            if not attached:
                return None
            formats.append(attached.group(1))
    if take:
        return None
    if not all(_SIZE_DIRECTIVE.search(f.replace('%%', '')) for f in formats):
        return None
    return paths


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
    if base == 'stat':
        return _stat_operands(rest) or []
    if not any(w in ('-c', '--bytes') for w in rest):
        return []
    # `wc` prints the byte count whenever -c is given, whatever else it
    # was asked for, so its other options only have to be skipped.
    paths = []
    for word in rest:
        if not _STAT_FLAG.match(word) and word != '--':
            paths.append(word)
    return paths


def _form_error(inp):
    limit = inp.get('head_limit')
    context = 0
    for flag in CONTEXT_FLAGS:
        value = inp.get(flag)
        if value is None:
            continue
        if isinstance(value, int) and not isinstance(value, bool):
            context = max(context, value)
        else:
            # Anything else is a window we cannot size. head_limit already
            # refuses a value it cannot act on; reading `-C: "50"` as no
            # window at all was the one reading that leaves output
            # unbounded, so the window fails closed too.
            context = max(context, 1)
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

    def capped():
        """Whether this path has exhausted its refusals.

        Asked only once the search has already been refused on its own
        terms. The cap is there to stop hammering, and a measured,
        bounded search is not hammering: refusing it would leave
        delegating or giving up as the only way out
        (reviews/deny-cap-evidence-2026-09-16.md section 4, item 2).
        """
        try:
            return _denials(state).get(_key(stat(path)), 0) >= DENY_CAP
        except OSError:
            return False

    def cap_reason():
        if writer:
            return ('this search has been refused %d times. Stop searching '
                    '%s: use output_mode="files_with_matches", or Read the '
                    'range you need, and report what you could not confirm.'
                    % (DENY_CAP, path))
        return ('this search has been refused %d times. Stop searching %s '
                'and report partial, or delegate it to '
                '/token-shunt:bulk-reader.' % (DENY_CAP, path))

    if not is_measured(state, path, stat):
        if capped():
            return cap_reason()
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
        if capped():
            return cap_reason()
        return '%s (%d B, over budget): %s' % (path, size, form)
    return None
