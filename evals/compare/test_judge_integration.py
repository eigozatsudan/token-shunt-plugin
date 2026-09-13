"""Control transcripts exercise production judge wiring, not only helper functions."""
import json
from pathlib import Path
import tempfile
import unittest
import judge
from test_routing_checks import transcript


def tool(tid, name, inp, result, error=False, extra=None):
    block = {'type': 'tool_result', 'tool_use_id': tid, 'content': result, 'is_error': error}
    if extra:
        block.update(extra)
    return [
        {'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'id': tid, 'name': name, 'input': inp}]}},
        {'type': 'user', 'message': {'content': [block]}}]


def child_read(agent_id, rid, path, body='ok'):
    return [
        {'type': 'assistant', 'parent_tool_use_id': agent_id,
         'message': {'content': [
             {'type': 'tool_use', 'id': rid, 'name': 'Read',
              'input': {'file_path': path}}]}},
        {'type': 'user', 'parent_tool_use_id': agent_id,
         'message': {'content': [
             {'type': 'tool_result', 'tool_use_id': rid, 'content': body}]}}]


class JudgeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def case(self, cid):
        cases = json.loads(Path(judge.__file__).with_name('cases.json').read_text())['cases']
        raw = json.dumps(next(c for c in cases if c['id'] == cid))
        return json.loads(raw.replace('{TMP}', str(self.root)).replace('{FIX}', str(self.root)).replace(
            '{JUDGE_DIR}', str(Path(judge.__file__).parent)))

    def run_judge(self, events, spec, mode='auto'):
        init = {'type': 'system', 'subtype': 'init', 'plugins':
                [] if mode == 'direct' else [{'name': 'token-shunt'}]}
        p = self.root/'transcript.jsonl'
        p.write_text('\n'.join(json.dumps(e) for e in [init] + events))
        return judge.judge(str(p), spec, {'mode': mode})

    def test_actual_edit_case_enforces_order(self):
        spec = self.case('auto-edit-grep-location')
        path = spec['expect']['direct']['edit_flow']['path']
        Path(path).parent.mkdir(parents=True)
        Path(path).write_text('padding\n'*100 + "HDR_MODE = 'off'\n" + 'padding\n'*100)
        grep = tool('g', 'Grep', {'path': path, 'pattern': 'HDR_MODE'}, "101:HDR_MODE = 'off'")
        read = tool('r', 'Read', {'file_path': path, 'offset': 100, 'limit': 3}, "100→padding\n101→HDR_MODE = 'off'\n102→padding")
        edit = tool('e', 'Edit', {'file_path': path, 'old_string': "HDR_MODE = 'off'", 'new_string': 'HDR_MODE=on'}, 'updated')
        final = [{'type': 'result', 'result': 'Updated HDR_MODE=on'}]
        good, ok = self.run_judge(grep + read + edit + final, spec, 'direct')
        self.assertTrue(ok, good['reasons'])
        bad, ok = self.run_judge(edit + grep + read + final, spec, 'direct')
        self.assertFalse(ok)
        self.assertFalse(bad['checks']['edit_flow'])

    WRITER_AGENT = {'subagent_type': 'token-shunt:code-writer', 'model': 'haiku',
                    'prompt': 'generate the requested artifacts'}

    def _writer_status(self, artifact):
        # Acceptance conditions actually checked -> requirements + complete.
        return 'complete' if artifact['level'] == 'requirements' else 'partial'

    def _writer_report(self, artifacts, overrides=None):
        overrides = overrides or {}
        lines = []
        for c in artifacts:
            name = Path(c['path']).name
            level, status = overrides.get(name, (c['level'], self._writer_status(c)))
            lines.append('%s: verification: %s; status: %s' % (name, level, status))
        return '\n'.join(lines)

    def _writer_commands(self, artifacts):
        commands = []
        for i, c in enumerate(artifacts):
            command = 'python3 %s --verify %s %s' % (c['checker'], c['level'], c['path'])
            if c.get('expected_lines'):
                command += ' --expected-lines ' + str(c['expected_lines'])
            for key in c.get('require_keys') or []:
                command += ' --require-key ' + key
            evidence = {'path': c['path'], 'verification': c['level'], 'ok': c.get('ok', True)}
            commands += tool('v' + str(i), 'Bash', {'command': command},
                             json.dumps(evidence), not evidence['ok'])
        return commands

    def test_requirements_positive_and_false_rejection_and_false_completion(self):
        spec = self.case('writer-verification-levels')
        artifacts = spec['expect']['delegate']['verification_artifacts']
        req = [c for c in artifacts if c['level'] == 'requirements']
        self.assertTrue(req, 'case must carry a requirements positive example')
        self.assertTrue(all(c.get('require_keys') for c in req))
        agent = tool('a', 'Agent', self.WRITER_AGENT, 'status: complete')
        commands = self._writer_commands(artifacts)
        name = Path(req[0]['path']).name
        # GREEN: acceptance keys checked -> requirements + complete is accepted.
        good, ok = self.run_judge(
            agent + commands + [{'type': 'result', 'result': self._writer_report(artifacts)}], spec)
        self.assertTrue(ok, good['reasons'])
        # RED (false rejection): the same successful check reported as syntax.
        under = self._writer_report(artifacts, {name: ('syntax', 'partial')})
        bad, ok = self.run_judge(agent + commands + [{'type': 'result', 'result': under}], spec)
        self.assertFalse(ok)
        self.assertFalse(bad['checks']['verification_control'])
        # RED (false completion): requirements claimed without running that check.
        without = self._writer_commands([c for c in artifacts if c['level'] != 'requirements'])
        bad, ok = self.run_judge(
            agent + without + [{'type': 'result', 'result': self._writer_report(artifacts)}], spec)
        self.assertFalse(ok)
        self.assertFalse(bad['checks']['verification_execution'])

    def test_actual_writer_case_requires_parent_execution_and_honest_report(self):
        spec = self.case('writer-verification-levels')
        agent = tool('a', 'Agent', self.WRITER_AGENT, 'status: complete')
        artifacts = spec['expect']['delegate']['verification_artifacts']
        report = self._writer_report(artifacts)
        final = [{'type': 'result', 'result': report}]
        commands = self._writer_commands(artifacts)
        good, ok = self.run_judge(agent + commands + final, spec)
        self.assertTrue(ok, good['reasons'])
        bad, ok = self.run_judge(agent + final, spec)
        self.assertFalse(ok)
        self.assertFalse(bad['checks']['verification_execution'])
        inflated = [{'type': 'result', 'result': report.replace('status: partial', 'status: complete')}]
        bad, ok = self.run_judge(agent + commands + inflated, spec)
        self.assertFalse(ok)
        self.assertFalse(bad['checks']['verification_level'])

    def _ambiguous_fixture(self, spec):
        path = spec['expect']['direct']['fixture_unchanged']['path']
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        body = ['# module header'] + ['PADA%03d = %d' % (i, i) for i in range(9, 60)]
        for cls in ('AlphaView', 'BetaView', 'GammaView'):
            body += ['', 'class %s:' % cls, '    def render_header(self):',
                     "        HDR_MODE = 'off'", '        return HDR_MODE']
        Path(path).write_text('\n'.join(body) + '\n')
        return path

    def test_ambiguous_grep_control_expects_no_edit(self):
        spec = self.case('auto-edit-grep-ambiguous')
        path = self._ambiguous_fixture(spec)
        grep = tool('g', 'Grep', {'path': path, 'pattern': "HDR_MODE = 'off'"},
                    "53:        HDR_MODE = 'off'\n58:        HDR_MODE = 'off'\n63:        HDR_MODE = 'off'")
        report = [{'type': 'result', 'result':
                   'render_header is defined three times with identical bodies; the target is '
                   'ambiguous, so I made no edit. Tell me which class to change.'}]
        good, ok = self.run_judge(grep + report, spec, 'direct')
        self.assertTrue(ok, good['reasons'])
        self.assertTrue(good['checks']['fixture_unchanged'])
        self.assertTrue(good['checks']['agent_zero'])

    def test_ambiguous_grep_control_fails_when_the_parent_edits(self):
        spec = self.case('auto-edit-grep-ambiguous')
        path = self._ambiguous_fixture(spec)
        grep = tool('g', 'Grep', {'path': path, 'pattern': "HDR_MODE = 'off'"},
                    "53:        HDR_MODE = 'off'")
        edit = tool('e', 'Edit', {'file_path': path, 'old_string': "HDR_MODE = 'off'",
                                  'new_string': "HDR_MODE = 'on'"}, 'updated')
        report = [{'type': 'result', 'result': 'Edited the ambiguous marker anyway.'}]
        # The judge must fail on the transcript alone...
        bad, ok = self.run_judge(grep + edit + report, spec, 'direct')
        self.assertFalse(ok)
        self.assertFalse(bad['checks']['no_parent_edit'])
        # ...and on the bytes the edit would leave behind.
        Path(path).write_text(Path(path).read_text().replace("HDR_MODE = 'off'",
                                                             "HDR_MODE = 'on'", 1))
        bad, ok = self.run_judge(grep + report, spec, 'direct')
        self.assertFalse(ok)
        self.assertFalse(bad['checks']['fixture_unchanged'])

    def test_ambiguous_control_is_separate_from_the_correct_edit_case(self):
        cases = json.loads(Path(judge.__file__).with_name('cases.json').read_text())
        ids = [c['id'] for c in cases['cases']]
        self.assertIn('auto-edit-grep-location', ids)
        self.assertIn('auto-edit-grep-ambiguous', ids)
        amb = next(c for c in cases['cases'] if c['id'] == 'auto-edit-grep-ambiguous')
        self.assertEqual(amb['suite'], 'B')
        self.assertEqual(amb['modes'], ['direct', 'haiku', 'sonnet', 'auto'])
        # Cost aggregation covers only the four delta cases (§26.5: outside cost totals).
        self.assertNotIn('auto-edit-grep-ambiguous',
                         ('auto-bulk-facts', 'auto-one-line', 'auto-explicit-multifile',
                          'auto-large-writer'))

    def test_writer_bounds_enforces_sixteen_unique_files(self):
        spec = self.case('writer-bounds')
        self.assertEqual(spec['expect']['delegate']['child_file_budget'], 16)

        def events(n_files):
            agent = tool('a', 'Agent', {
                'subagent_type': 'token-shunt:code-writer', 'model': 'haiku',
                'prompt': 'generate the artifact'}, 'wrote target; 12 lines')
            reads = []
            for i in range(n_files):
                reads += child_read('a', 'r%d' % i, '/repo/file%02d.py' % i)
            return agent[:1] + reads + agent[1:] + [{'type': 'result', 'result': 'done'}]

        good, ok = self.run_judge(events(16), spec)
        self.assertTrue(ok, good['reasons'])
        self.assertTrue(good['checks']['child_file_budget'])
        bad, ok = self.run_judge(events(17), spec)
        self.assertFalse(ok)
        self.assertFalse(bad['checks']['child_file_budget'])
        # The pre-existing 20-call budget is untouched by the file ceiling.
        self.assertTrue(bad['checks']['child_tool_budget'])

    def test_retry_reread_and_resume_through_judge(self):
        spec = {'id': 'retry-control', 'expect': {'delegate': {
            'agent_type': 'token-shunt:bulk-reader', 'retry_policy': True,
            'child_reads_once': ['/a.py'], 'agent_calls_max': 2}},
            'expected_resolved_model': {'auto': 'haiku'}}
        attempts = [('haiku', ['/a.py'], '', {}),
                    ('sonnet', ['/a.py'], 'missing evidence: TOKEN location absent', {})]
        good, ok = self.run_judge(transcript(attempts).events, spec)
        self.assertTrue(ok, good['reasons'])
        resumed = [('haiku', ['/a.py'], '', {'resume': 'previous-agent'})]
        bad, ok = self.run_judge(transcript(resumed).events, spec)
        self.assertFalse(ok)
        self.assertFalse(bad['checks']['retry_policy'])

    def _no_ref_events(self, spec, child_text):
        return tool('a', 'Agent', {
            'subagent_type': 'token-shunt:code-writer', 'model': 'haiku',
            'prompt': spec['prompt_delegate'],
        }, child_text) + [{'type': 'result', 'result': child_text}]

    def test_no_ref_rejects_fenced_generated_code_without_fixture(self):
        spec = self.case('compare-code-writer-no-ref')
        leaked = '```python\n' + '\n'.join('print(%d)' % i for i in range(25)) + '\n```'
        v, ok = self.run_judge(self._no_ref_events(spec, leaked), spec)
        self.assertFalse(ok)
        self.assertFalse(v['checks'].get('child_no_body'))

    def test_no_ref_rejects_twenty_line_body_and_requires_reason_path(self):
        spec = self.case('compare-code-writer-no-ref')
        body = '\n'.join('x = %d' % i for i in range(21))
        v, ok = self.run_judge(self._no_ref_events(spec, body), spec)
        self.assertFalse(ok)
        self.assertFalse(v['checks'].get('child_no_body'))
        silent = 'ok'
        v, ok = self.run_judge(self._no_ref_events(spec, silent), spec)
        self.assertFalse(ok)
        self.assertFalse(v['checks'].get('child_mentions'))
        good = 'reference missing_ref.py is unreadable (ENOENT). status: partial'
        v, ok = self.run_judge(self._no_ref_events(spec, good), spec)
        self.assertTrue(ok, v['reasons'])

    def test_16k_boundary_gold_is_not_size_filename(self):
        for cid, size in (('auto-routing-boundary-16k-minus', '16383'),
                          ('auto-routing-boundary-16k-equal', '16384'),
                          ('auto-routing-boundary-16k-plus', '16385')):
            spec = self.case(cid)
            self.assertTrue(spec.get('gold'))
            for g in spec['gold']:
                self.assertNotIn(size, g, cid)

    def test_16k_plus_parent_full_read_fails_even_with_agent(self):
        spec = self.case('auto-routing-boundary-16k-plus')
        path = spec['expect']['delegate']['parent_no_full_read'][0]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text('marker\n')
        gold = spec['gold'][0]
        child = child_read('a', 'cr', path, gold)
        events = (
            tool('r', 'Read', {'file_path': path}, gold)
            + tool('a', 'Agent', {
                'subagent_type': 'token-shunt:bulk-reader', 'model': 'haiku',
                'prompt': path,
            }, 'confirmed: ' + gold, extra={'resolvedModel': 'claude-haiku'})
            + child
            + [{'type': 'result', 'result': gold}]
        )
        v, ok = self.run_judge(events, spec)
        self.assertFalse(ok)
        self.assertFalse(v['checks'].get('parent_no_full_read'))

    def test_16k_minus_requires_parent_read(self):
        spec = self.case('auto-routing-boundary-16k-minus')
        path = spec['expect']['delegate']['parent_reads'][0]
        gold = spec['gold'][0]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text('marker=' + gold + '\n')
        guessed = [{'type': 'result', 'result': gold}]
        v, ok = self.run_judge(guessed, spec)
        self.assertFalse(ok)
        self.assertFalse(v['checks'].get('parent_reads'))
        events = tool('r', 'Read', {'file_path': path}, 'marker=' + gold) + guessed
        v, ok = self.run_judge(events, spec)
        self.assertTrue(ok, v['reasons'])

    def test_batch_evidence_rejects_padding_quote_under_cap(self):
        spec = self.case('reader-batch-evidence')
        user = Path(judge.__file__).parent / 'fixtures' / 'rails' / 'app' / 'models' / 'user.rb'
        pad_lines = [l for l in user.read_text().splitlines() if '# padding-' in l][:21]
        self.assertEqual(len(pad_lines), 21)
        leak = '\n'.join(pad_lines)
        self.assertLess(len(leak), 4000)
        b0, b1 = spec['expect']['delegate']['batch_invocation']
        def agent(tid, paths, text):
            prompt = ' '.join(paths) + ' --question "concern job mailer"'
            ev = tool(tid, 'Agent', {
                'subagent_type': 'token-shunt:bulk-reader', 'model': 'haiku',
                'prompt': prompt,
            }, text, extra={'resolvedModel': 'claude-haiku'})
            for i, p in enumerate(paths):
                ev += child_read(tid, tid + 'r' + str(i), p, 'body')
            return ev
        confirmed = (
            'confirmed: Notifiable path: user.rb\n'
            'confirmed: WelcomeEmailJob path: welcome_email_job.rb\n'
            'confirmed: UserMailer path: user_mailer.rb'
        )
        final = [{'type': 'result', 'result': confirmed}]
        events = agent('a0', b0, leak) + agent('a1', b1, confirmed) + final
        v, ok = self.run_judge(events, spec)
        self.assertFalse(ok)
        self.assertFalse(v['checks'].get('child_no_body'))


if __name__ == '__main__':
    unittest.main()


def hook_response(name, output=''):
    return {'type': 'system', 'subtype': 'hook_response',
            'hook_name': name, 'hook_event': name.split(':')[0],
            'output': output, 'stdout': '', 'stderr': '', 'exit_code': 0}


TS_DENY = json.dumps({'hookSpecificOutput': {
    'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
    'permissionDecisionReason': 'File exceeds token-shunt thresholds '
                                '(bytes=70000/65536). Use /token-shunt:bulk-reader.'}})
OTHER_DENY = json.dumps({'hookSpecificOutput': {
    'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
    'permissionDecisionReason': 'blocked by some other plugin'}})


class MatcherOnlyHookNameTests(unittest.TestCase):
    """CLI 2.1.x reports only the matcher in hook_name, never the command path.

    Attribution therefore comes from the isolation contract plus the payload
    (design §13). These lock in that a delegate run is not failed for its own
    hooks, while genuinely foreign responses still fail.
    """

    def events(self, names_and_outputs):
        class T:
            hook_events = [hook_response(n, o) for n, o in names_and_outputs]
        return T()

    def test_own_matcher_only_hooks_are_not_foreign_when_plugin_loaded(self):
        tr = self.events([('SessionStart:startup', ''),
                          ('PreToolUse:Read', TS_DENY),
                          ('PreToolUse:Read', ''),
                          ('PreToolUse:Bash', '')])
        self.assertEqual(judge.foreign_hooks(tr, plugin_loaded=True), [])

    def test_same_hooks_are_foreign_in_direct_mode(self):
        tr = self.events([('PreToolUse:Read', '')])
        self.assertEqual(judge.foreign_hooks(tr, plugin_loaded=False), ['PreToolUse:Read'])

    def test_other_event_scopes_are_foreign(self):
        tr = self.events([('PostToolUse:Write', ''), ('UserPromptSubmit', '')])
        self.assertEqual(judge.foreign_hooks(tr, plugin_loaded=True),
                         ['PostToolUse:Write', 'UserPromptSubmit'])

    def test_foreign_deny_on_our_matcher_is_detected(self):
        tr = self.events([('PreToolUse:Read', OTHER_DENY)])
        self.assertEqual(judge.foreign_hooks(tr, plugin_loaded=True),
                         ['PreToolUse:Read(non-token-shunt output)'])

    def test_legacy_command_path_hook_names_still_attributed(self):
        tr = self.events([('PreToolUse:check-file-size', TS_DENY)])
        self.assertEqual(judge.foreign_hooks(tr, plugin_loaded=True), [])

    def test_deny_detected_from_matcher_only_name(self):
        tr = self.events([('PreToolUse:Read', TS_DENY)])
        denies = judge.ts_hook_denies(tr)
        self.assertEqual(len(denies), 1)
        self.assertIn('bulk-reader', denies[0]['reason'])

    def test_foreign_deny_is_not_counted_as_token_shunt_deny(self):
        tr = self.events([('PreToolUse:Read', OTHER_DENY)])
        self.assertEqual(judge.ts_hook_denies(tr), [])
