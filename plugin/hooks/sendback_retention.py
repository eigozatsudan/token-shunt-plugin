"""Three independent checks on how a parent's final answer treats the
`confirmed:` lines its workers returned.

They are deliberately separate, because they answer different questions and
have different recovery steps:

  child_items      did we get the worker's output at all, and did it carry
                   items a parent could copy?   (recovery: re-delegate)
  file_coverage    does the final answer cite every source file the worker
                   cited?                       (recovery: send back)
  line_retention   is every worker `confirmed:` line still there, verbatim?
                   (recovery: send back)

`file_coverage` is a weaker question than `line_retention` and never
replaces it: two facts drawn from one file are two items but one file, so
dropping one of them leaves coverage intact. The product contract is
verbatim retention of every line; coverage exists to catch the coarse
failure early and to say something useful when line matching is not
possible.

Every check can return UNDETERMINED. A missing worker transcript and a
source file that no longer exists are not parent violations, and must not
be reported as one.
"""
import html
import os
import re

OK = 'ok'
VIOLATION = 'violation'
UNDETERMINED = 'undetermined'

# A citation is the first absolute path in the item's head (before the em
# dash that separates path from fact).
_ABS = re.compile(r"(?<![\w./-])(/[^\s`\"'<>]+)")
# `/tmp/.../app/models/user.rb` and `/tmp/…/user.rb` name no single file.
_ELIDED = re.compile(r'/\.\.\.(?:/|$)|…')

CONFIRMED = 'confirmed:'
UNCONFIRMED = 'unconfirmed:'


def normalize(line):
    """Compare on the text's meaning, not on how a channel encoded it.

    The parent reads the worker through a task notification, which
    XML-escapes the body (`<` becomes `&lt;`). A parent that copied that
    form faithfully must not be reported as having altered the line.
    """
    return ' '.join(html.unescape(line).split())


def _collect(text, prefix, reject=None):
    out = []
    for raw in (text or '').splitlines():
        line = raw.strip()
        while line[:1] in ('-', '*', '+'):
            line = line[1:].strip()
        low = line.lower()
        if low.startswith(prefix) and not (reject and low.startswith(reject)):
            out.append(line)
    return out


def unconfirmed_lines(text):
    """`unconfirmed:` lines, same shape as confirmed_lines."""
    return _collect(text, UNCONFIRMED)


def confirmed_lines(text):
    """`confirmed:` lines, list-marker and whitespace stripped.

    `unconfirmed:` lines are not collected: demotion is what the skill
    prescribes when a path is missing, so counting them as retention
    targets would make the correct recovery look like a violation.
    """
    return _collect(text, CONFIRMED, reject=UNCONFIRMED)


def citation(line):
    """The absolute path a `confirmed:` item cites, or None."""
    head = re.split(r'\s+[—–]\s+| - ', line, maxsplit=1)[0]
    m = _ABS.search(head)
    if not m:
        return None
    return m.group(1).rstrip('.,;:)')


def classify_path(path, exists=os.path.exists):
    """OK / VIOLATION (elided or not absolute) / UNDETERMINED (gone).

    A path that does not resolve is not evidence that the parent dropped
    anything: the file may have been moved or deleted since the worker read
    it. Elision is different -- the parent wrote a path that names no file,
    and that is visible without touching the filesystem.
    """
    if not path or not path.startswith('/'):
        return VIOLATION
    if _ELIDED.search(path):
        return VIOLATION
    return OK if exists(path) else UNDETERMINED


def check_child_items(child_texts, exists=os.path.exists):
    """Did the workers hand the parent anything it could retain?"""
    if child_texts is None:
        return {'status': UNDETERMINED, 'reason': 'worker output unavailable',
                'items': [], 'usable': [], 'unusable': []}
    lines = []
    for t in child_texts:
        lines.extend(confirmed_lines(t))
    usable, unusable, unknown = [], [], []
    for line in lines:
        verdict = classify_path(citation(line), exists)
        (usable if verdict == OK else
         unknown if verdict == UNDETERMINED else unusable).append(line)
    if not lines:
        return {'status': VIOLATION, 'reason': 'worker returned no confirmed item',
                'items': [], 'usable': [], 'unusable': []}
    if usable:
        return {'status': OK, 'reason': '', 'items': lines,
                'usable': usable, 'unusable': unusable}
    if unknown:
        return {'status': UNDETERMINED,
                'reason': 'every worker citation names a file that no longer exists',
                'items': lines, 'usable': [], 'unusable': unusable}
    return {'status': VIOLATION,
            'reason': 'no worker item carries a usable absolute path',
            'items': lines, 'usable': [], 'unusable': unusable}


def check_file_coverage(child_texts, final, exists=os.path.exists):
    """Does the final answer cite every file the workers cited?"""
    child = check_child_items(child_texts, exists)
    if child['status'] == UNDETERMINED:
        return {'status': UNDETERMINED, 'reason': child['reason'],
                'missing': [], 'expected': [], 'cited': []}
    want = {citation(l) for l in child['usable']}
    got = {citation(l) for l in confirmed_lines(final)
           if classify_path(citation(l), exists) == OK}
    missing = sorted(want - got)
    if not want:
        # Nothing to cover. Whether that is the parent's fault is
        # check_child_items' question, not this one.
        return {'status': UNDETERMINED, 'reason': 'no worker file to cover',
                'missing': [], 'expected': [], 'cited': sorted(got)}
    return {'status': VIOLATION if missing else OK,
            'reason': 'final answer cites none of: %s' % ', '.join(missing)
                      if missing else '',
            'missing': missing, 'expected': sorted(want), 'cited': sorted(got)}


def check_line_retention(child_texts, final, exists=os.path.exists):
    """Is every worker `confirmed:` line still present, verbatim?

    Four outcomes per line: kept verbatim, demoted (the same item survives
    under `unconfirmed:`), altered (the cited path survives in some final
    item, the text does not), or dropped.

    Demotion is the contract's own recovery for a line WITHOUT a usable
    absolute path, so it is only a violation here: these targets all carry
    one, and demoting them discards evidence the worker actually produced.
    Lines whose path is unusable never become targets, which is what keeps
    the permitted demotion from being reported.

    Identical lines collapse, which the contract allows. Matching is done on
    the normalized form, so the notification's XML escaping is not mistaken
    for the parent rewriting the line.
    """
    child = check_child_items(child_texts, exists)
    if child['status'] == UNDETERMINED:
        return {'status': UNDETERMINED, 'reason': child['reason'],
                'kept': [], 'demoted': [], 'altered': [], 'dropped': []}
    targets = list(dict.fromkeys(child['usable']))
    if not targets:
        return {'status': UNDETERMINED, 'reason': 'no worker line to retain',
                'kept': [], 'demoted': [], 'altered': [], 'dropped': []}
    # Match verbatim first and consume what matched, so a second fact drawn
    # from an already-cited file is reported as dropped rather than as a
    # rewrite of the line that did survive.
    pool = [(normalize(l), l) for l in confirmed_lines(final)]
    demoted_pool = [(normalize(l[len(UNCONFIRMED):].strip()), l)
                    for l in unconfirmed_lines(final)]
    kept, demoted, altered, dropped, leftover = [], [], [], [], []

    def take(seq, pred):
        for i, entry in enumerate(seq):
            if pred(entry):
                return seq.pop(i)
        return None

    for line in targets:
        norm = normalize(line)
        if take(pool, lambda e, n=norm: e[0] == n):
            kept.append(line)
        else:
            leftover.append(line)
    for line in leftover:
        body = normalize(line[len(CONFIRMED):].strip())
        # A parent that rewrote `confirmed:` as `unconfirmed:` kept the text
        # but discarded its standing; that is a retention violation, and a
        # different one from dropping the line outright.
        # The body must match, not merely the path: a parent may legitimately
        # mark a DIFFERENT fact from the same file unconfirmed, and pairing on
        # the path alone would read that as a demotion of this line.
        if take(demoted_pool, lambda e, b=body: e[0] == b):
            demoted.append(line)
            continue
        if take(pool, lambda e, c=citation(line): citation(e[1]) == c):
            altered.append(line)
        else:
            dropped.append(line)
    lost = len(demoted) + len(altered) + len(dropped)
    return {'status': OK if not lost else VIOLATION,
            'reason': '' if not lost else
                      '%d demoted, %d altered, %d dropped'
                      % (len(demoted), len(altered), len(dropped)),
            'kept': kept, 'demoted': demoted, 'altered': altered,
            'dropped': dropped}


def run_all(child_texts, final, exists=os.path.exists):
    return {'child_items': check_child_items(child_texts, exists),
            'file_coverage': check_file_coverage(child_texts, final, exists),
            'line_retention': check_line_retention(child_texts, final, exists)}
