"""Per-invocation routing contracts for the comparison evaluator (§26.1/26.3)."""
import re


def _prompt(agent):
    return str(agent.get('input', {}).get('prompt', ''))


def _paths(prompt):
    # Preserve quoted paths with spaces; slash commands are not file paths.
    quoted = re.findall(r"[\"'](/[^\"']+)[\"']", prompt)
    remainder = re.sub(r"[\"'](/[^\"']+)[\"']", '', prompt)
    bare = re.findall(r'(?<![\w:])/(?:[^\s\"\'<>;,()]+)', remainder)
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
# contract is "each region once", not "each path once". maxTurns is 6.
MAX_CHILD_READS = 6


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
        reads = [c for c in children if c['name'] == 'Read']
        if not expected or len(declared) > 3 or len(reads) > MAX_CHILD_READS:
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


def check_routing(tr, spec, exp, mode, agents, resolved_models):
    errors = []
    for agent in tr.agent_uses():
        if agent.get('input', {}).get('resume'):
            errors.append(('retry_policy', 'Agent resume is forbidden'))
    configured = spec.get('expected_resolved_model') or exp.get('expected_resolved_model')
    enabled = bool(configured or exp.get('retry_policy') or exp.get('batch_invocation'))
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
    if exp.get('ambiguous_batch'):
        final = tr.final_text()
        # This fixture deliberately has no reference connecting the colliding TOKENs.
        # Even a boundary reread cannot invent a relationship.
        if not re.search(r'\bunconfirmed\b', final, re.I) or not re.search(r'\bpartial\b', final, re.I):
            errors.append(('batch_evidence', 'ambiguous TOKEN relationship must remain unconfirmed and partial'))
        if any(re.search(r'(?<!un)\bconfirmed\s*[:：]', line, re.I) and re.search(r'refers? to|references?|depends? on|relationship|関係|参照|依存', line, re.I) and 'TOKEN' in line for line in final.splitlines()):
            errors.append(('batch_evidence', 'unsupported confirmed relationship for colliding symbols'))
    return errors
