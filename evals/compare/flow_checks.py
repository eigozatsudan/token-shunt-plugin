"""Ordered edit and parent verification evidence for the comparison judge."""
import ast
import json
import os
import re
import shlex
import sys
import subprocess
import tokenize
import tempfile
from pathlib import Path


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
    # Table rows are complete reports. Keep later explicit declarations too;
    # prose that merely mentions an artifact does not make a fresh claim.
    for name in names:
        rows = []
        for line in final.splitlines():
            cells = line.strip().split('|')
            if len(cells) >= 5 and cells[0] == '' and cells[1].strip().strip('`*') == name:
                rows.append('|' + '|'.join(cells[2:]))
        if rows:
            declarations = []
            for section in sections.get(name, []):
                cleaned = section.replace('`', '').replace('*', '')
                explicit = {field for field in ('verification', 'status')
                            if re.search(r'\b' + field + r'\s*:', cleaned, re.I)}
                if not explicit:
                    continue
                # A status-only or level-only update inherits the table's
                # other field, so contradictions remain visible to validation.
                levels, statuses = report_fields(rows[0])
                for field, values in [('verification', levels), ('status', statuses)]:
                    if field not in explicit:
                        section += '\n' + field + ': ' + '/'.join(sorted(values))
                declarations.append(section)
            sections[name] = rows + declarations
    return sections


def report_fields(section):
    cleaned = section.replace('`', '').replace('*', '')
    # Collect explicitly listed field values, stopping before explanatory
    # prose/parentheses so mentions of other states are not claims of them.
    def listed_values(field, words):
        word = r'(?:' + words + r')\b'
        lists = re.findall(
            r'\b' + field + r'\s*:\s*(' + word
            + r'(?:[ \t]*(?:[/,+&]|\band\b|\bor\b)[ \t]*' + word
            + r'(?=[ \t]*(?:[/,+&;|.(]|\band\b|\bor\b|\b(?:status|verification)\s*:|$|\n)))*)', cleaned, re.I)
        return [value for values in lists for value in re.findall(word, values, re.I)]
    levels = listed_values('verification', 'minimal|syntax|requirements')
    statuses = listed_values('status', 'partial|complete|error|failed')
    if not levels:
        levels = re.findall(r'(?:^|[|+])\s*(minimal|syntax|requirements)\s*(?:\([^|\n]*\)\s*)?(?=[|+]|$)', cleaned.strip(), re.I)
    if not statuses:
        statuses = re.findall(r'(?:^|[|+])\s*(partial|complete|error|failed)\s*(?:\([^|\n]*\)\s*)?(?=[|+]|$)', cleaned.strip(), re.I)
    return {s.lower() for s in levels}, {s.lower() for s in statuses}


def verification_commands(command, cwd):
    """Recognize literal verification batches; never execute shell input.

    Only newline-separated cd, echo labels and checker calls are supported.
    Conditionals, pipelines, expansions and other commands are not evidence.
    """
    if any(c in command for c in ('$','`')):
        return []
    commands = []
    for line in command.splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars=';&|<>()')
        lexer.whitespace_split = True
        lexer.commenters = ''
        try:
            argv = list(lexer)
        except ValueError:
            return []
        if not argv:
            continue
        if any(a and all(c in ';&|<>()' for c in a) for a in argv):
            return []
        if argv[0] == 'cd' and len(argv) == 2 and not commands:
            cwd = os.path.normpath(os.path.join(cwd or '', argv[1]))
            if not os.path.isabs(cwd):
                return []
        elif argv[0] == 'echo' and not any('{' in a or '}' in a for a in argv[1:]):
            continue
        elif len(argv) >= 5 and argv[0] == 'python3' and argv[2] == '--verify':
            if not cwd and not (os.path.isabs(argv[1]) and os.path.isabs(argv[4])):
                return []
            normalized = list(argv)
            for i in (1, 4):
                normalized[i] = os.path.normpath(os.path.join(cwd or '', argv[i]))
            commands.append((normalized, cwd))
        else:
            return []
    return commands


def verification_errors(tr, spec, exp):
    errors = []
    compile_target = exp.get('parent_py_compile')
    if compile_target:
        uses, results, report = timeline(tr)
        found = False
        for u in tr.parent_tool_uses('Bash'):
            try:
                argv = shlex.split(u['input'].get('command', ''))
            except ValueError:
                continue
            if (len(argv) != 4 or argv[0] not in ('python', 'python3')
                    or argv[1:3] != ['-m', 'py_compile']
                    or os.path.normpath(argv[3]) != os.path.normpath(compile_target)):
                continue
            r = tr.result_of(u['id'])
            if (r and not r['is_error'] and u['id'] in uses and u['id'] in results
                    and uses[u['id']] < results[u['id']] < report):
                found = True
        if not found:
            errors.append(('verification_execution', compile_target + ' lacks successful parent py_compile before report'))
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
            commands = verification_commands(u['input'].get('command', ''), spec.get('tool_cwd'))
            if not any(argv == expected_cmd for argv, _ in commands):
                continue
            r = tr.result_of(u['id'])
            if not r or u['id'] not in results or not (uses[u['id']] < results[u['id']] < report):
                continue
            evidence_rows = []
            for line in r['text'].splitlines():
                try:
                    evidence = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(evidence, dict):
                    evidence_rows.append(evidence)
            if len(evidence_rows) != len(commands):
                continue
            # One ordered JSON result per command also proves checks that
            # intentionally failed before the final successful batch command.
            valid = True
            for (argv, cwd), evidence in zip(commands, evidence_rows):
                reported_path = evidence.get('path')
                if (not isinstance(reported_path, str)
                        or not (cwd or os.path.isabs(reported_path))
                        or os.path.normpath(os.path.join(cwd or '', reported_path)) != argv[4]
                        or evidence.get('verification') != argv[3]
                        or not isinstance(evidence.get('ok'), bool)):
                    valid = False
            if not valid or bool(r['is_error']) == evidence_rows[-1]['ok']:
                continue
            if any(argv == expected_cmd and ev['ok'] is ok
                   for (argv, _), ev in zip(commands, evidence_rows)):
                found = True
        if not found:
            errors.append(('verification_execution', path + ' lacks parent verification command/result before report'))
    return errors


def verify_writer_boundary(path, boundary, reference=None):
    """Check syntax/count and exercise the 50-line unittest against its reference."""
    try:
        with tokenize.open(path) as source:
            body = source.read()
        tree = ast.parse(body, filename=path)
        compile(tree, path, 'exec')
        lines = len(body.splitlines())
        if (boundary == 49 and lines != 49) or (boundary == 50 and lines < 50):
            raise ValueError('writer boundary line count not met')
        functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if boundary == 49:
            greet_names = {'greet'}
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    greet_names.update(a.asname or a.name for a in node.names if a.name == 'greet')
            greet_calls = any(isinstance(n, ast.Call) and
                              (isinstance(n.func, ast.Name) and n.func.id in greet_names
                               or isinstance(n.func, ast.Attribute) and n.func.attr in greet_names)
                              for n in ast.walk(tree))
            if not functions or not (greet_calls or any(n.name == 'greet' for n in functions)):
                raise ValueError('missing helpers around greet')
        else:
            reference = reference or str(Path(__file__).parent / 'fixtures/codegen/greeter.py')
            checker = str(Path(__file__).with_name('writer_unittest_check.py'))
            with tempfile.TemporaryDirectory(prefix='writer-boundary-') as evidence_dir:
                for mode in ('baseline', 'mutation'):
                    evidence = Path(evidence_dir) / (mode + '.result')
                    run = subprocess.run([sys.executable, '-B', checker, str(Path(path).resolve()),
                                          str(Path(reference).resolve()), mode, str(evidence)],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         timeout=15)
                    if (run.returncode or not evidence.is_file()
                            or evidence.read_text(encoding='utf-8') != 'writer-boundary-check:passed'):
                        raise ValueError('unittest greet coverage failed: ' + mode)
        return {'path': path, 'ok': True}
    except (OSError, ValueError, SyntaxError, subprocess.TimeoutExpired) as exc:
        return {'path': path, 'ok': False, 'diagnostic': str(exc)}


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
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument('--verify', choices=['minimal', 'syntax', 'requirements'])
    operation.add_argument('--writer-boundary', type=int, choices=[49, 50])
    parser.add_argument('path')
    parser.add_argument('--reference', help='greet implementation for writer boundary unittest')
    parser.add_argument('--expected-lines', type=int)
    parser.add_argument('--require-key', action='append', default=[],
                        help='required key, or key=value, for --verify requirements')
    args = parser.parse_args()
    evidence = (verify_writer_boundary(args.path, args.writer_boundary, args.reference) if args.writer_boundary
                else verify_artifact(args.path, args.verify, args.expected_lines, args.require_key))
    print(json.dumps(evidence))
    sys.exit(0 if evidence['ok'] else 1)
