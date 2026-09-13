"""Ordered edit and parent verification evidence for the comparison judge."""
import json
import os
import re
import shlex
import sys


def timeline(tr):
    uses, results = {}, {}
    reports = []
    for i, event in enumerate(tr.events):
        if event.get('parent_tool_use_id') is not None:
            continue
        for j, block in enumerate(event.get('message', {}).get('content', []) or []):
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'tool_use':
                uses[block.get('id')] = (i, j)
            elif block.get('type') == 'tool_result':
                results[block.get('tool_use_id')] = (i, j)
            elif block.get('type') == 'text' and block.get('text') == tr.final_text():
                reports.append((i, j))
        if event.get('type') == 'result' and event.get('result') == tr.final_text():
            reports.append((i, 0))
    return uses, results, min(reports) if reports else (len(tr.events), 0)


def edit_flow_errors(tr, cfg, spec, targets, full_read):
    path = os.path.normpath(cfg['path'])
    uses, results, _ = timeline(tr)
    mark = cfg.get('original_mark', '')
    def successful(u):
        result = tr.result_of(u['id'])
        return result and not result['is_error'] and u['id'] in results
    greps = []
    for u in tr.parent_tool_uses('Grep'):
        if not successful(u) or not u['input'].get('pattern'):
            continue
        result = tr.result_of(u['id'])['text']
        inp = u['input']
        # A file-scoped content match or an explicit matching path identifies the target.
        exact = os.path.normpath(inp.get('path', '')) == path
        lines = result.strip().splitlines()
        if not lines:
            continue
        hits = []
        for line in lines:
            match = re.match(r'^(\d+):(.*)$', line) if exact else re.match(re.escape(path) + r':(\d+):(.*)$', line)
            if match:
                hits.append(int(match.group(1)))
        if len(hits) == 1:
            greps.append((u, hits[0]))
    reads = [u for u in tr.parent_tool_uses('Read')
             if targets(u, path) and (u['input'].get('offset') or u['input'].get('limit'))
             and not full_read(u, path, spec) and successful(u)
             and (not mark or mark in tr.result_of(u['id'])['text'])
             and not re.search(r'(?im)^\s*(?:PARTIAL|.*\[.*truncated.*\])', tr.result_of(u['id'])['text'])]
    edits = [u for u in tr.parent_tool_uses('Edit') if targets(u, path)]
    if not edits or not any(successful(u) for u in edits):
        return ['no successful parent Edit on ' + path]
    # Every edit attempt must follow completed evidence, including when calls share a message.
    for edit in edits:
        valid = False
        for read in reads:
            if not (uses[read['id']] < results[read['id']] < uses[edit['id']]):
                continue
            old = edit['input'].get('old_string')
            original = re.sub(r'(?m)^\s*\d+[→\t]', '', tr.result_of(read['id'])['text'])
            if not old or old not in original:
                continue
            for grep, line in greps:
                try:
                    offset = int(read['input'].get('offset') or 1)
                    limit = int(read['input'].get('limit') or 0)
                except (TypeError, ValueError):
                    continue
                if limit > 0 and offset <= line < offset + limit and uses[grep['id']] < results[grep['id']] < uses[read['id']]:
                    valid = True
        if not valid:
            return ['Edit lacks completed target-identifying Grep -> original targeted Read evidence on ' + path]
    return []


def artifact_sections(final, names):
    """Scope prose, bullet lists and Markdown tables to the named artifact."""
    pattern = re.compile('|'.join(re.escape(n) for n in sorted(names, key=len, reverse=True)))
    matches = list(pattern.finditer(final))
    sections = {}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(final)
        sections.setdefault(match.group(), []).append(final[match.end():end])
    return sections


def report_fields(section):
    cleaned = section.replace('`', '').replace('*', '')
    levels = re.findall(r'\bverification\s*:\s*(minimal|syntax|requirements)\b', cleaned, re.I)
    statuses = re.findall(r'\bstatus\s*:\s*(partial|complete|error|failed)\b', cleaned, re.I)
    if not levels:
        levels = re.findall(r'(?:^|[|+])\s*(minimal|syntax|requirements)\s*(?=[|+]|$)', cleaned.strip(), re.I)
    if not statuses:
        statuses = re.findall(r'(?:^|[|+])\s*(partial|complete|error|failed)\s*(?=[|+]|$)', cleaned.strip(), re.I)
    return {s.lower() for s in levels}, {s.lower() for s in statuses}


def verification_errors(tr, spec, exp):
    errors = []
    levels = exp.get('verification_level')
    if isinstance(levels, str):
        if levels not in tr.final_text():
            errors.append(('verification_level', 'final lacks level ' + levels))
        return errors
    controls = spec.get('verification_controls') or exp.get('verification_controls') or []
    checks = exp.get('verification_artifacts') or []
    names = set(levels or {}) | {os.path.basename(c.get('path') or c.get('name') or '') for c in controls}
    sections = artifact_sections(tr.final_text(), names) if names else {}
    for name, level in (levels or {}).items():
        fields = [report_fields(s) for s in sections.get(name, [])]
        if not fields or any(ls != {level} or st != {'partial'} for ls, st in fields):
            errors.append(('verification_level', name + ' must report its level and status partial'))
    for control in controls:
        name = os.path.basename(control.get('path') or control.get('name') or '')
        fields = [report_fields(s) for s in sections.get(name, [])]
        allowed = set(control.get('allowed_status', ['partial', 'failed', 'error']))
        if not fields or any(not ls or (control.get('expected_level') and ls != {control['expected_level']}) or not st or ls & set(control.get('forbid_levels', []))
                             or not st <= allowed or st & set(control.get('forbid_status', []))
                             for ls, st in fields):
            errors.append(('verification_control', name + ' missing or invalid scoped verification report'))
    uses, results, report = timeline(tr)
    for check in checks:
        path, level = check['path'], check['level']
        ok = check.get('ok', True)
        found = False
        expected_cmd = ['python3', os.path.normpath(check['checker']), '--verify', level, path]
        if check.get('expected_lines'):
            expected_cmd += ['--expected-lines', str(check['expected_lines'])]
        for key in check.get('require_keys') or []:
            expected_cmd += ['--require-key', key]
        for u in tr.parent_tool_uses('Bash'):
            try:
                argv = shlex.split(u['input'].get('command', ''))
            except ValueError:
                continue
            if len(argv) > 1:
                argv[1] = os.path.normpath(argv[1])
            if argv != expected_cmd:
                continue
            r = tr.result_of(u['id'])
            if not r or u['id'] not in results or not (uses[u['id']] < results[u['id']] < report):
                continue
            if bool(r['is_error']) == ok:
                continue
            for line in r['text'].splitlines():
                try:
                    evidence = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(evidence, dict) and evidence.get('path') == path and evidence.get('verification') == level and evidence.get('ok') is ok:
                    found = True
        if not found:
            errors.append(('verification_execution', path + ' lacks parent verification command/result before report'))
    return errors


def verify_artifact(path, level, expected_lines=None, require_keys=None):
    """No body output; minimal deliberately makes no syntax/completeness promise."""
    try:
        with open(path, encoding='utf-8') as source:
            body = source.read()
        if level == 'syntax':
            json.loads(body)
        elif level == 'requirements':
            # Acceptance conditions: named keys (and optional key=value) must hold.
            if not require_keys:
                raise ValueError('requirements verification needs acceptance keys')
            document = json.loads(body)
            if not isinstance(document, dict):
                raise ValueError('artifact is not a JSON object')
            for requirement in require_keys:
                key, sep, want = requirement.partition('=')
                if key not in document:
                    raise ValueError('missing required key: ' + key)
                if sep and str(document[key]) != want:
                    # Names the requirement, never the artifact body.
                    raise ValueError('required value mismatch for key: ' + key)
        elif level == 'minimal':
            lines = body.strip().splitlines()
            if not lines:
                raise ValueError('empty artifact')
            # Do not reject a legitimate trailing Markdown code block.
            outer = re.match(r'^\s*(```|~~~)(.*)$', lines[0])
            wrapped_markdown = outer and outer.group(2).strip().lower() in {'md', 'markdown'}
            if outer and (not path.lower().endswith('.md') or wrapped_markdown) and re.match(r'^\s*(```|~~~)\s*$', lines[-1]):
                raise ValueError('outer code fence')
            if expected_lines and not expected_lines / 10 <= len(lines) <= expected_lines * 10:
                raise ValueError('line count differs by an order of magnitude')
        else:
            raise ValueError('unsupported verification level')
        return {'path': path, 'verification': level, 'ok': True}
    except (OSError, ValueError) as exc:
        return {'path': path, 'verification': level, 'ok': False, 'diagnostic': str(exc)}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify', required=True, choices=['minimal', 'syntax', 'requirements'])
    parser.add_argument('path')
    parser.add_argument('--expected-lines', type=int)
    parser.add_argument('--require-key', action='append', default=[],
                        help='required key, or key=value, for --verify requirements')
    args = parser.parse_args()
    evidence = verify_artifact(args.path, args.verify, args.expected_lines, args.require_key)
    print(json.dumps(evidence))
    sys.exit(0 if evidence['ok'] else 1)
