"""Per-invocation routing contracts for the comparison evaluator (§26.1/26.3)."""
import re
import shlex
from report_text import plain_report


def metadata_only_bash(command):
    """Prove two bounded shell idioms emit metadata, never source text.

    This is deliberately not a shell interpreter. Unknown syntax falls back to
    the ordinary recovery check; substitutions and redirections are excluded.
    """
    if any(marker in command for marker in ('`', '$(', '${', '\n', '<', '>')):
        return False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';|&()')
        lexer.whitespace_split = True
        lexer.commenters = ''
        words = list(lexer)
    except ValueError:
        return False

    def literal_path(word):
        return (word.startswith('/') and not any(c in word for c in '$*?[]\\'))

    # A range scan whose sole stdout consumer is wc -c/-l emits only a count.
    # No tee, alternate branch, extra command, or stderr redirection is allowed.
    if (len(words) == 7 and words[:2] == ['sed', '-n']
            and re.fullmatch(r'[1-9][0-9]*,[1-9][0-9]*p', words[2])
            and literal_path(words[3]) and words[4:6] == ['|', 'wc']
            and words[6] in ('-c', '-l')):
        return True

    # The size-probe loop used by the reader skill. Resolve only this explicit
    # loop variable, never arbitrary shell assignments or interpreter programs.
    if len(words) < 10 or words[:3] != ['for', 'f', 'in']:
        return False
    try:
        split = words.index(';', 3)
    except ValueError:
        return False
    if (split == 3 or not all(literal_path(p) for p in words[3:split])
            or words[split + 1:split + 2] != ['do'] or words[-2:] != [';', 'done']):
        return False
    statements = []
    current = []
    for word in words[split + 2:-1]:
        if word == ';':
            statements.append(current)
            current = []
        else:
            current.append(word)
    if current or not statements:
        return False
    for statement in statements:
        if statement == ['echo', '$f']:
            continue
        if (len(statement) == 3 and statement[0] == 'wc'
                and statement[1] in ('-c', '-l') and statement[2] == '$f'):
            continue
        if (len(statement) == 3 and statement[0] == 'awk' and statement[2] == '$f'
                and re.fullmatch(r'END\s*\{\s*print\s+NR\s*;?\s*\}', statement[1])):
            continue
        return False
    return True


def _prompt(agent):
    return str(agent.get('input', {}).get('prompt', ''))


def _paths(prompt):
    # Preserve quoted paths with spaces; slash commands are not file paths.
    quoted = re.findall(r"[\"'](/[^\"']+)[\"']", prompt)
    remainder = re.sub(r"[\"'](/[^\"']+)[\"']", '', prompt)
    # A prose suffix such as `after_create`/callback is not a declaration.
    # Keep unknown explicit paths visible so extra-path checks still work.
    bare = re.findall(r'(?:^|(?<=[\s(]))/(?:[^\s\"\'`<>;,()]+)', remainder)
    return {p.rstrip('.:') for p in quoted + bare
            if not p.startswith('/token-shunt:')}



def _question(prompt):
    match = re.search(r'(?:--question|question\s*:|質問\s*[:：])\s*[\"\']([^\"\']+)[\"\']', prompt, re.I)
    return match.group(1) if match else None


def _alias(model, expected):
    return bool(re.fullmatch(r'(?:claude-)?' + re.escape(expected) + r'(?:-[\w.-]+)?', str(model).lower()))


def _read_range(call):
    """(start, end) line range of a Read, 1-based inclusive; end None = EOF."""
    offset = call['input'].get('offset')
    limit = call['input'].get('limit')
    start = int(offset) if offset else 1
    end = start + int(limit) - 1 if limit else None
    return start, end


def _returned_range(result, requested, total_lines):
    """Trust only consecutive native line labels within the requested range."""
    numbers = [int(n) for n in re.findall(r'^\s*(\d+)(?:\t|→)',
                                         result.get('text', ''), re.M)]
    if (not numbers or numbers[0] != requested[0]
            or numbers != list(range(numbers[0], numbers[-1] + 1))
            or (requested[1] is not None and numbers[-1] > requested[1])
            or (total_lines is not None and numbers[-1] > total_lines)):
        return None
    return numbers[0], numbers[-1]


def _line_count(path):
    # Use the actual fixture, never line counts asserted in agent prompts.
    try:
        with open(path, 'rb') as source:
            return sum(1 for _ in source)
    except OSError:
        return None


def _overlaps(a, b):
    (a0, a1), (b0, b1) = a, b
    return (a1 is None or b0 <= a1) and (b1 is None or a0 <= b1)


# The Read tool refuses a whole file over its own token cap, which is exactly
# the size class token-shunt delegates. The child may then cover the file with
# consecutive non-overlapping ranges (plugin/agents/bulk-reader.md). Native
# successful results can also stop before EOF without a truncation notice;
# verified returned line labels authorize continuation in that case. Thus the
# contract is "each region once", not "each path once". maxTurns is 7, reserving a final reporting turn.
MAX_CHILD_READS = 6


def reader_contract_denial(tr, call):
    """Recognize only a matching failed Read carrying a runtime contract reason.

    Matcher-only hook events cannot identify a child call. The paired native
    tool result supplies call identity, invocation identity and ordering.
    """
    result = tr.result_of(call['id'])
    if (call['name'] != 'Read' or not result or not result.get('is_error')
            or result.get('parent_tool_use_id') != call.get('parent_tool_use_id')
            or result.get('position', (-1, -1)) <= call.get('position', (-1, -1))):
        return None
    reason = result.get('text', '').strip()
    patterns = (
        r'Read budget exhausted; stop partial with stop_reason: budget_exhausted\.',
        r'A Read is still pending\. Issue Reads serially; do not read ahead\.',
        r'Read requires an absolute file_path\.',
        r'At most three paths per invocation\.',
        r'No further Read is supported for this path; report its unread range partial\.',
        r'Read must start at offset=\d+ with a positive limit\.',
        r'Retry at offset=\d+ with limit=\d+ \(floor half\)\.',
    )
    return reason if any(re.fullmatch('token-shunt: ' + p, reason) for p in patterns) else None


def reader_attempt_metrics(tr, agents):
    records = []
    for agent in agents:
        if tr.agent_type_of(agent) != 'token-shunt:bulk-reader':
            continue
        reads = [c for c in tr.child_tool_uses(agent['id']) if c['name'] == 'Read']
        blocked = [{'tool_use_id': c['id'], 'reason': reason}
                   for c in reads if (reason := reader_contract_denial(tr, c))]
        records.append({'agent_id': agent['id'], 'attempts': len(reads),
                        'budget_consumed': min(len(reads), MAX_CHILD_READS),
                        'blocked_attempts': blocked})
    return records


def check_reader_reads(tr, exp, agents):
    """Each carrier reads its own explicit paths; no region is read twice."""
    errors = []
    required = set(exp.get('child_reads_once', []))
    allowed = required | set(exp.get('required_paths', [])) | set(exp.get('single_invocation_paths', []))
    for batch in exp.get('batch_invocation', []):
        allowed.update(batch)
    covered = set()
    if not allowed:
        return errors
    for agent in agents:
        if tr.agent_type_of(agent) != 'token-shunt:bulk-reader':
            continue
        declared = _paths(_prompt(agent))
        expected = allowed & declared
        children = tr.child_tool_uses(agent['id'])
        attempts = [c for c in children if c['name'] == 'Read']
        reads = [c for c in attempts if not reader_contract_denial(tr, c)]
        # The hook charges the first six attempts, including its own denials.
        # Later denied requests do not execute and cannot exceed that budget.
        overflow = any(not reader_contract_denial(tr, c)
                       for c in attempts[MAX_CHILD_READS:])
        if not expected or len(declared) > 3 or overflow:
            errors.append(('child_reads_once',
                           'Agent %s must carry 1-3 explicit paths and stay within %d Reads'
                           % (agent['id'], MAX_CHILD_READS)))
        if any(c['name'] != 'Read' for c in children):
            errors.append(('child_extra_read', 'reader used a tool other than Read'))
        for c in reads:
            path = c['input'].get('file_path', c['input'].get('path'))
            if path not in expected:
                errors.append(('child_extra_read', 'Read outside this invocation: %s' % path))
        for path in expected:
            matches = [c for c in reads if c['input'].get('file_path', c['input'].get('path')) == path]
            if not matches:
                errors.append(('child_reads_once', '%s must be read in this invocation' % path))
                continue
            # Native refusal retains the bounded partition fallback. Successful
            # partial results need actual EOF and returned-line evidence.
            got = []
            partition = False
            next_line = 1
            total_lines = _line_count(path)
            incomplete = False
            retry_limit = None
            retry_stopped = False
            for index, c in enumerate(matches):
                result = tr.result_of(c['id'])
                span = _read_range(c)
                # Validate attempted ranges too: a refused jump still violates
                # the cursor contract, and does not authorize filling its gap.
                if partition or incomplete:
                    if span[0] != next_line:
                        errors.append(('child_reads_once',
                                       '%s: partition must continue at line %s, got %s'
                                       % (path, next_line, span)))
                elif index > 0:
                    errors.append(('child_reads_once',
                                   '%s: repeated Read without evidence of an incomplete prior Read' % path))
                if retry_stopped:
                    errors.append(('child_reads_once',
                                   '%s: Read continued after limit=1 refusal' % path))
                if retry_limit is not None:
                    count = span[1] - span[0] + 1 if span[1] is not None else None
                    if count != retry_limit:
                        errors.append(('child_reads_once',
                                       '%s: refused range must retry with limit %s, got %s'
                                       % (path, retry_limit, count)))
                if not result:
                    errors.append(('child_reads_once', 'Read result missing: %s' % path))
                    incomplete = False
                    partition = False
                    continue
                if result['is_error']:
                    if re.search(r'File content .*exceeds maximum allowed tokens',
                                 result.get('text', ''), re.I):
                        if index == 0:
                            next_line = span[0]
                        partition = True
                        count = span[1] - span[0] + 1 if span[1] is not None else None
                        retry_limit = max(1, count // 2) if count is not None else None
                        retry_stopped = count == 1
                    else:
                        incomplete = False
                        partition = False
                    continue
                retry_limit = None
                retry_stopped = False
                returned = _returned_range(result, span, total_lines)
                incomplete = (returned is not None and total_lines is not None
                              and returned[1] < total_lines)
                # A refusal permits partitioning, but only actual returned
                # line labels establish the cursor for another successful read.
                # An unknown endpoint may be enough to answer and stop.
                partition = partition and returned is not None
                actual = returned if returned is not None else span
                next_line = actual[1] + 1 if actual[1] is not None else None
                got.append((c, actual))
            if (not got and retry_stopped
                    and path in exp.get('allow_unreadable_line_partial', [])
                    and total_lines == 1):
                covered.add(path)
                continue
            if not got:
                errors.append(('child_reads_once', 'Read did not succeed: %s' % path))
                continue
            for i, (_, span) in enumerate(got):
                for _, other in got[i + 1:]:
                    if _overlaps(span, other):
                        errors.append(('child_reads_once',
                                       '%s: overlapping reads %s and %s' % (path, span, other)))
                        break
            covered.add(path)
    for path in required - covered:
        errors.append(('child_reads_once', 'no successful carrier Read: %s' % path))
    return errors


def rejected_model_launch(tr, agent):
    """A model hook denial before any worker activity is not an invocation."""
    inp = agent.get('input', {})
    if (tr.agent_type_of(agent) not in
            ('token-shunt:bulk-reader', 'token-shunt:code-writer')
            or inp.get('model') in ('haiku', 'sonnet')):
        return False
    result = tr.result_of(agent['id'])
    if (not result or not result.get('is_error')
            or 'token-shunt: Agent model must be explicitly haiku or sonnet.'
            not in result.get('text', '')
            or result.get('parent_tool_use_id') is not None
            or result.get('position', (-1, -1)) <= agent.get('position', (-1, -1))):
        return False
    if tr.child_tool_uses(agent['id']):
        return False
    return not any(e.get('parent_tool_use_id') == agent['id']
                   for e in tr.events)


# A claim about one symbol standing in for another, in either language.
_RELATION = re.compile(r'refers? to|references?|depends? on|relationship'
                       r'|関係|参照|依存', re.I)
_CONFIRMED = re.compile(r'(?<!un)\bconfirmed\s*[:：]', re.I)
# Clause boundaries: a negation binds to its own clause, not the whole
# line. A comma is not one -- "No TOKEN definitions, references, or
# imports found" is a single negated enumeration, not three claims.
_CLAUSE = re.compile(r'[;；]|\bbut\b|\bhowever\b|\bthough\b|（|\(')
_NEGATED = re.compile(r'\bno\b|\bnot\b|\bnone\b|\bnever\b|\bwithout\b'
                      r'|n[\u2019\']t\b|無|不|ない|ません', re.I)


def positive_relationship(line):
    """Does this confirmed line assert a link, rather than deny one?

    An absence is evidence, not a claim: "no import or reference to beta"
    supports the answer instead of inventing it. A mixed line is judged
    clause by clause, so "no import, but TOKEN refers to beta" still
    fails on its second half.
    """
    if not (_CONFIRMED.search(line) and 'TOKEN' in line):
        return False
    for clause in _CLAUSE.split(line):
        if _RELATION.search(clause) and not _NEGATED.search(clause):
            return True
    return False


def denies_relationship(line):
    """Does this confirmed line state that the link is not there?

    The absence branch needs a denial, in its own clause. "Not a positive
    TOKEN claim" is not the same thing: `positive_relationship` only
    looks at lines that say TOKEN, so a line asserting the link in other
    words satisfied neither test and counted as evidence of absence.
    """
    if not _CONFIRMED.search(line):
        return False
    return any(_RELATION.search(clause) and _NEGATED.search(clause)
               for clause in _CLAUSE.split(line))


def absence_covers_collision(final, colliding):
    """Every colliding file reported, by path, as referring to no other.

    This is the evidence branch of the design's "resolve or demote": the
    files were read and each says the link is not there.
    """
    if len(colliding) < 2:
        return False
    for path in colliding:
        lines = [l for l in final.splitlines()
                 if path in l and _CONFIRMED.search(l)]
        if not any(denies_relationship(l) and not positive_relationship(l)
                   for l in lines):
            return False
    return True


def boundary_confirmation(agents, colliding):
    """One fresh invocation carrying every colliding path together."""
    if len(colliding) < 2:
        return False
    wanted = set(colliding)
    return any(wanted <= set(_paths(_prompt(agent))) for agent in agents)


def check_routing(tr, spec, exp, mode, agents, resolved_models):
    mode = 'auto' if mode == 'delegate' else mode
    errors = []
    for agent in tr.agent_uses():
        if agent.get('input', {}).get('resume'):
            errors.append(('retry_policy', 'Agent resume is forbidden'))
    configured = spec.get('expected_resolved_model') or exp.get('expected_resolved_model')
    enabled = bool(configured or exp.get('retry_policy') or exp.get('batch_invocation')
                   or any(tr.agent_type_of(agent) in
                          {'token-shunt:bulk-reader', 'token-shunt:code-writer'} for agent in agents))
    if not enabled or mode == 'direct':
        return errors
    if len(tr.agent_uses()) > 4:
        errors.append(('retry_policy', 'total Agent budget exceeds four'))
    positions = {}
    results = {}
    for index, event in enumerate(tr.events):
        for block_index, block in enumerate(event.get('message', {}).get('content', []) or []):
            if isinstance(block, dict) and block.get('type') == 'tool_use':
                positions[block.get('id')] = (index, block_index)
            elif isinstance(block, dict) and block.get('type') == 'tool_result':
                results[block.get('tool_use_id')] = (index, block_index)
    seen = {}
    retries = 0
    boundaries = 0
    batches = [set(batch) for batch in exp.get('batch_invocation', [])]
    for agent in agents:
        prompt = _prompt(agent)
        paths = _paths(prompt)
        key = (tr.agent_type_of(agent), frozenset(paths))
        previous = seen.get(key)
        expected = 'haiku' if mode == 'auto' else mode
        if previous:
            retries += 1
            expected = 'sonnet'
            if mode != 'auto' or retries > 1:
                errors.append(('retry_policy', 'only one auto Sonnet retry is permitted'))
            # Require an explicit short diagnosis, not merely an escalation request.
            permitted = re.search(r'missing[_ ](?:required[_ ])?evidence|(?:evidence|根拠).{0,30}(?:missing|不足|欠落)|(?:response[_ ]contract|返答契約).{0,30}(?:violat|違反)|(?:verification|検証).{0,30}(?:fail|失敗)', prompt, re.I)
            forbidden = re.search(r'low confidence|自信度|context.{0,20}(?:limit|exceed)|size.{0,20}(?:limit|exceed)|budget.{0,20}(?:exhaust|limit)|permission denied|authentication|missing dependency|参照不存在|未対応モデル|コンテキスト.{0,10}上限|サイズ.{0,10}上限|予算.{0,10}(?:終了|上限)|認証|権限|未指定.{0,10}依存', prompt, re.I)
            if not permitted or forbidden:
                errors.append(('retry_policy', 'retry lacks a permitted short diagnosis'))
            question = _question(_prompt(previous))
            if question and question not in prompt:
                errors.append(('retry_policy', 'retry omitted the original question'))
            result = tr.child_return_of(previous)
            # Async launch acknowledgements are not completed worker returns.
            # Use the matching parent notification's position for async replies;
            # keep synchronous positions tied to the actual transcript events.
            returned_at = (results.get(previous['id']) if result and 'raw' in result
                           else result.get('position') if result else None)
            if (not result or result.get('parent_tool_use_id') is not None
                    or returned_at is None
                    or not (positions.get(previous['id'], (float('inf'), 0))
                            < returned_at < positions.get(agent['id'], (-1, 0)))):
                errors.append(('retry_policy', 'retry began without a previous worker result'))
        elif mode == 'auto' and agent.get('input', {}).get('model') == 'sonnet':
            errors.append(('retry_policy', 'Sonnet retry changed paths or has no Haiku attempt'))
        if batches and paths not in batches:
            boundaries += 1
            if boundaries > 1 or not paths <= set().union(*batches) or len(paths) > 3 or not any(paths & b for b in batches[:1]) or not any(paths & b for b in batches[1:]):
                errors.append(('batch_boundary', 'invalid or repeated boundary confirmation'))
        requested = agent.get('input', {}).get('model')
        if requested != expected:
            errors.append(('requested_model', '%s requested %r; expected %s' % (agent['id'], requested, expected)))
        models = resolved_models(tr, agent)
        if not models or not all(_alias(model, expected) for model in models):
            errors.append(('resolved_model', '%s resolved %r; expected %s' % (agent['id'], models, expected)))
        seen[key] = agent
    ambiguous = exp.get('ambiguous_batch')
    if ambiguous:
        final = tr.final_text()
        colliding = ambiguous.get('paths') or [] if isinstance(ambiguous, dict) else []
        # Design section 925 and the case prompt both allow two endings:
        # resolve the collision, or report it unconfirmed and partial.
        # Demanding the second unconditionally failed answers that read
        # every file and found no reference either way -- negative evidence
        # is still matching evidence, and the answer is then complete.
        resolved = (boundary_confirmation(agents, colliding)
                    or absence_covers_collision(final, colliding))
        if not resolved and (not re.search(r'\bunconfirmed\b', final, re.I)
                             or not re.search(r'\bpartial\b', final, re.I)):
            errors.append(('batch_evidence', 'ambiguous TOKEN relationship must remain unconfirmed and partial'))
        if any(positive_relationship(line) for line in final.splitlines()):
            errors.append(('batch_evidence', 'unsupported confirmed relationship for colliding symbols'))
    return errors


def unreadable_line_partial(tr, exp, agents):
    """Accept an unsupported input outcome only with native refusal evidence."""
    paths = exp.get('allow_unreadable_line_partial', [])
    if not paths or len(paths) != 1 or len(agents) != 1:
        return False
    agent = agents[0]
    if tr.agent_type_of(agent) != 'token-shunt:bulk-reader':
        return False
    path = paths[0]
    children = tr.child_tool_uses(agent['id'])
    reads = [c for c in children if not reader_contract_denial(tr, c)]
    if (not reads or any(c['name'] != 'Read' for c in children)):
        return False
    for call in reads:
        result = tr.result_of(call['id'])
        if (call['input'].get('file_path', call['input'].get('path')) != path
                or not result or not result['is_error']
                or not re.search(r'File content .*exceeds maximum allowed tokens',
                                 result.get('text', ''), re.I)):
            return False
    if _read_range(reads[-1]) != (1, 1) or _line_count(path) != 1:
        return False
    if check_reader_reads(tr, exp, agents):
        return False
    reply = tr.child_return_of(agent)
    if not reply or reply['is_error']:
        return False
    for text in (reply['text'], tr.final_text()):
        text = plain_report(text)
        if (re.findall(r'(?m)^[ \t]*(?:[-*+][ \t]+)?status:[ \t]*([^\n]*)$', text) != ['partial']
                or re.findall(r'(?m)^[ \t]*(?:[-*+][ \t]+)?stop_reason:[ \t]*([^\n]*)$', text) != ['unreadable_line']
                or not any(line.lstrip('-*+ ').startswith('unconfirmed: ' + path + ' —')
                           for line in text.splitlines())
                or has_confirmed_claim(text)
                or 'unread line 1' not in text):
            return False
    return True


def has_confirmed_claim(text):
    """Empty/explicitly absent facts are not evidence; arbitrary suffixes are."""
    in_confirmed = False
    for line in text.splitlines():
        field = re.match(r'^(confirmed|unconfirmed|inferred|status|stop_reason):[ \t]*(.*)$', line, re.I)
        if field:
            in_confirmed = field[1].lower() == 'confirmed'
            if in_confirmed and not re.fullmatch(
                    r'(?:none\.?|none[ \t]+—[ \t]+unable to retrieve [A-Za-z_]\w* value\.)?',
                    field[2], re.I):
                return True
        elif in_confirmed and line.strip():
            return True
    return False
