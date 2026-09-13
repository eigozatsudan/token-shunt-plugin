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


def check_reader_reads(tr, exp, agents):
    """Each carrier reads its own explicit paths once; retries may reread them."""
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
        if not expected or len(declared) > 3 or len(reads) > 3:
            errors.append(('child_reads_once', 'Agent %s must carry/read 1–3 explicit paths' % agent['id']))
        if any(c['name'] != 'Read' for c in children):
            errors.append(('child_extra_read', 'reader used a tool other than Read'))
        for c in reads:
            path = c['input'].get('file_path', c['input'].get('path'))
            if path not in expected:
                errors.append(('child_extra_read', 'Read outside this invocation: %s' % path))
        for path in expected:
            matches = [c for c in reads if c['input'].get('file_path', c['input'].get('path')) == path]
            if len(matches) != 1:
                errors.append(('child_reads_once', '%s must be read once per invocation' % path))
            elif not (r := tr.result_of(matches[0]['id'])) or r['is_error']:
                errors.append(('child_reads_once', 'Read did not succeed: %s' % path))
            else:
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
        for block in event.get('message', {}).get('content', []) or []:
            if isinstance(block, dict) and block.get('type') == 'tool_use':
                positions[block.get('id')] = index
            elif isinstance(block, dict) and block.get('type') == 'tool_result':
                results[block.get('tool_use_id')] = index
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
            result = tr.result_of(previous['id'])
            if not result or results.get(previous['id'], float('inf')) >= positions.get(agent['id'], -1):
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
