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


def confirmed_lines(text):
    """`confirmed:` lines, list-marker and whitespace stripped.

    `unconfirmed:` lines are not collected: demotion is what the skill
    prescribes when a path is missing, so counting them as retention
    targets would make the correct recovery look like a violation.
    """
    out = []
    for raw in (text or '').splitlines():
        line = raw.strip()
        while line[:1] in ('-', '*', '+'):
            line = line[1:].strip()
        low = line.lower()
        if low.startswith(CONFIRMED) and not low.startswith(UNCONFIRMED):
            out.append(line)
    return out


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

    Three outcomes per line: kept verbatim, present but altered (the cited
    path survives in some final item, the text does not), or dropped.
    Identical lines collapse, which the contract allows; a line whose path
    is unusable is not counted against the parent, since the contract tells
    it to demote that line rather than reproduce it.
    """
    child = check_child_items(child_texts, exists)
    if child['status'] == UNDETERMINED:
        return {'status': UNDETERMINED, 'reason': child['reason'],
                'kept': [], 'altered': [], 'dropped': []}
    targets = list(dict.fromkeys(child['usable']))
    if not targets:
        return {'status': UNDETERMINED, 'reason': 'no worker line to retain',
                'kept': [], 'altered': [], 'dropped': []}
    # Match verbatim first and consume what matched, so a second fact drawn
    # from an already-cited file is reported as dropped rather than as a
    # rewrite of the line that did survive.
    pool = list(confirmed_lines(final))
    kept, altered, dropped, leftover = [], [], [], []
    for line in targets:
        if line in pool:
            pool.remove(line)
            kept.append(line)
        else:
            leftover.append(line)
    for line in leftover:
        match = next((f for f in pool if citation(f) == citation(line)), None)
        if match is None:
            dropped.append(line)
        else:
            pool.remove(match)
            altered.append(line)
    return {'status': OK if not (altered or dropped) else VIOLATION,
            'reason': '' if not (altered or dropped) else
                      '%d line(s) altered, %d dropped'
                      % (len(altered), len(dropped)),
            'kept': kept, 'altered': altered, 'dropped': dropped}


def run_all(child_texts, final, exists=os.path.exists):
    return {'child_items': check_child_items(child_texts, exists),
            'file_coverage': check_file_coverage(child_texts, final, exists),
            'line_retention': check_line_retention(child_texts, final, exists)}
