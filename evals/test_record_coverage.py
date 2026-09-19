"""The coverage instrument records; it never decides.

Spec: docs/superpowers/specs/2026-09-19-targeted-read-coverage-design.md

18 of 21 archived parent corpus Reads were targeted (offset+limit), which
Lock B never denies by design. This hook measures that route. It has no
deny path, no state file, and no threshold, and each test below names the
production change that would break it.
"""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

HOOKS = Path(__file__).resolve().parents[1] / 'plugin' / 'hooks'
SOURCE = HOOKS / 'record-coverage'
hook = importlib.util.module_from_spec(
    importlib.util.spec_from_loader(
        'record_coverage',
        importlib.machinery.SourceFileLoader('record_coverage', str(SOURCE))))
# Execute the source directly so loading this extensionless hook cannot
# leave bytecode inside the distributable plugin tree.
exec(compile(SOURCE.read_bytes(), str(SOURCE), 'exec'), hook.__dict__)


def event(path='/corpus/migration.py', start=139, lines=50, total=316,
          content='x' * 2814, offset=139, limit=50, agent_id=None,
          agent_type=None, is_error=False, **extra):
    response = {'type': 'text', 'file': {
        'filePath': path, 'content': content,
        'startLine': start, 'numLines': lines, 'totalLines': total}}
    if is_error:
        response['is_error'] = True
    body = {'hook_event_name': 'PostToolUse', 'tool_name': 'Read',
            'session_id': 's1', 'agent_id': agent_id, 'agent_type': agent_type,
            'tool_input': {'file_path': path},
            'tool_response': response}
    if offset is not None:
        body['tool_input']['offset'] = offset
    if limit is not None:
        body['tool_input']['limit'] = limit
    body.update(extra)
    return body


class RecordTests(unittest.TestCase):
    def test_the_line_range_comes_from_the_tool_response(self):
        # Fails if the hook ever counts lines itself instead of reading
        # startLine/numLines/totalLines back.
        got = hook.record(event())
        self.assertEqual(('record-coverage', 's1', None, None,
                          '/corpus/migration.py'),
                         (got['hook'], got['session_id'], got['agent_id'],
                          got['agent_type'], got['file_path']))
        self.assertEqual((139, 50, 316), (got['start'], got['lines'], got['total']))
        self.assertEqual((139, 50), (got['offset'], got['limit']))
        self.assertEqual(2814, got['bytes'])
        self.assertIs(False, got['is_error'])

    def test_a_worker_read_carries_both_of_the_fields_that_identify_it(self):
        # intake_ledger.py:134 judges a parent by `not (agent_id or
        # agent_type)`. Recording only agent_id files a worker Read whose
        # event carries agent_type alone as if the parent had made it, and
        # worker reads are full-file by design -- they would drag every
        # rate up.
        self.assertEqual(('a7', None),
                         (hook.record(event(agent_id='a7'))['agent_id'],
                          hook.record(event(agent_id='a7'))['agent_type']))
        typed = hook.record(event(agent_type='token-shunt:bulk-reader'))
        self.assertEqual('token-shunt:bulk-reader', typed['agent_type'])

    def test_a_failed_read_keeps_the_row_but_claims_no_lines(self):
        # Fails if the hook drops error rows: the count of attempts would
        # silently fall, which is how a corrected count of 21 in 10 of 14
        # once got published as 26 in 12 of 14.
        got = hook.record(event(is_error=True))
        self.assertEqual((None, None, None, 0),
                         (got['start'], got['lines'], got['total'], got['bytes']))
        self.assertIs(True, got['is_error'])
        self.assertEqual('/corpus/migration.py', got['file_path'])

    def test_a_full_read_records_no_offset_and_no_limit(self):
        # The hook must not decide what counts as "targeted"; it reports the
        # raw input and lets the aggregator define it.
        got = hook.record(event(offset=None, limit=None, start=1, lines=316))
        self.assertEqual((None, None), (got['offset'], got['limit']))
        self.assertEqual((1, 316, 316), (got['start'], got['lines'], got['total']))

    def test_a_non_read_event_records_nothing(self):
        self.assertIsNone(hook.record(dict(event(), tool_name='Bash')))

    def test_a_malformed_response_records_a_row_without_line_numbers(self):
        # Fails if the hook raises on junk: a telemetry crash must not reach
        # the tool call.
        for junk in ('', [], {'file': 'not-an-object'}, {'file': {'startLine': 'x'}}):
            with self.subTest(junk=junk):
                got = hook.record(dict(event(), tool_response=junk))
                self.assertEqual('/corpus/migration.py', got['file_path'])
                self.assertIsNone(got['start'])

    def test_an_event_without_a_path_records_nothing(self):
        self.assertIsNone(hook.record(dict(event(), tool_input={})))
        self.assertIsNone(hook.record(dict(event(), tool_input='junk')))


    def test_a_non_string_agent_id_still_reads_as_a_worker(self):
        # intake_ledger.py:134 looks at the raw truthiness, so `agent_id: 7`
        # is a worker to the ledger. Dropping it to None here files that
        # worker's full-file reads as the parent's, and worker rows stick at
        # 1.0 by design -- the parent rate would swell toward 1.0 with it.
        self.assertEqual('7', hook.record(event(agent_id=7))['agent_id'])
        self.assertEqual('True', hook.record(event(agent_id=True))['agent_id'])
        self.assertEqual('9', hook.record(event(agent_type=9))['agent_type'])

    def test_a_falsy_agent_field_still_reads_as_the_parent(self):
        # `str(False)` is truthy, so coercing every non-string would turn the
        # parent into a worker: the same error mirrored.
        for value in (False, 0, '', None):
            with self.subTest(value=value):
                self.assertIsNone(hook.record(event(agent_id=value))['agent_id'])
                self.assertIsNone(hook.record(event(agent_type=value))['agent_type'])

    def test_the_other_fields_keep_the_string_only_rule(self):
        # Only the two agent fields are read for their truthiness; widening
        # the rest would invent session ids that never existed.
        self.assertIsNone(hook.record(dict(event(), session_id=7))['session_id'])

    def test_the_recorded_path_is_the_real_path(self):
        # judge.py:646-656 normalises for this reason: one file reached
        # through a symlink or `..` splits into two rows, so the same lines
        # taken twice look like two healthy partial reads of two files.
        # The run directory is gone by aggregation time, so it happens here.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            real = root / 'real.py'
            real.write_text('x\n')
            link = root / 'link.py'
            link.symlink_to(real)
            self.assertEqual(str(real),
                             hook.record(event(path=str(link)))['file_path'])
            dotted = root / 'sub' / '..' / 'real.py'
            self.assertEqual(str(real),
                             hook.record(event(path=str(dotted)))['file_path'])

    def test_the_response_path_wins_over_the_requested_path(self):
        # `tool_response.file.filePath` is what the tool actually opened.
        got = hook.record(dict(event(), tool_input={'file_path': '/c/asked.py'}))
        self.assertEqual('/corpus/migration.py', got['file_path'])

class EntryPointTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith('TOKEN_SHUNT_')}
        self.env['TMPDIR'] = str(self.root / 'tmp')
        os.mkdir(self.env['TMPDIR'])

    def run_hook(self, body, log=None):
        env = dict(self.env)
        if log is not None:
            env['TOKEN_SHUNT_HOOK_LOG'] = str(log)
        return subprocess.run([sys.executable, str(SOURCE)],
                              input=json.dumps(body), text=True, timeout=10,
                              capture_output=True, env=env)

    def test_a_read_appends_one_line_to_the_hook_log(self):
        log = self.root / 'hooklog'
        result = self.run_hook(event(), log)
        self.assertEqual((0, '', ''), (result.returncode, result.stdout, result.stderr))
        rows = [json.loads(l) for l in log.read_text().splitlines()]
        self.assertEqual(1, len(rows))
        self.assertEqual(('record-coverage', 139, 50, 316),
                         (rows[0]['hook'], rows[0]['start'], rows[0]['lines'],
                          rows[0]['total']))

    def test_without_a_log_path_it_writes_nothing_at_all(self):
        # Fails if the instrument is ever switched on by default: an
        # unmeasured mechanism ships off.
        result = self.run_hook(event())
        self.assertEqual((0, '', ''), (result.returncode, result.stdout, result.stderr))
        self.assertEqual([], list(self.root.rglob('*hooklog*')))

    def test_it_creates_no_state_directory(self):
        # Fails if this is ever rewritten as a ledger: Lock A and Lock B are
        # two state files already, and a third would be a third way to break.
        self.run_hook(event(), self.root / 'hooklog')
        self.assertEqual([], sorted(Path(self.env['TMPDIR']).glob('token-shunt-*')))

    def test_junk_on_stdin_exits_zero_and_says_nothing(self):
        for junk in ('', 'not json', '[]', 'null'):
            with self.subTest(junk=junk):
                result = subprocess.run(
                    [sys.executable, str(SOURCE)], input=junk, text=True,
                    timeout=10, capture_output=True,
                    env=dict(self.env, TOKEN_SHUNT_HOOK_LOG=str(self.root / 'j')))
                self.assertEqual((0, '', ''),
                                 (result.returncode, result.stdout, result.stderr))

    def test_the_hook_has_no_way_to_deny_anything(self):
        # The safety property is structural, not behavioural: if a decision
        # path is ever added, this fails before any test of its behaviour.
        source = SOURCE.read_text()
        for forbidden in ('hookSpecificOutput', 'permissionDecision'):
            self.assertNotIn(forbidden, source)

    def test_the_hook_does_not_import_lock_b(self):
        # Lock B is inert at budget 0, which is the shipped default. Sharing
        # a module with it would make this instrument inert too. A comment
        # may cite intake_ledger.py:134 -- only an import is forbidden.
        self.assertIsNone(re.search(r'(?m)^\s*(import|from)\s+intake_ledger',
                                    SOURCE.read_text()))

    def test_stdout_stays_empty_even_for_a_read_it_records(self):
        result = self.run_hook(event(), self.root / 'hooklog')
        self.assertEqual('', result.stdout)


    def test_it_drains_stdin_before_it_looks_at_the_environment(self):
        # Every other hook reads stdin unconditionally. A large Read event
        # exceeds the pipe buffer, so returning on the default-off path
        # before reading breaks the writer's pipe instead of exiting quietly.
        payload = self.root / 'payload.json'
        payload.write_text(json.dumps(event(content='x' * 2_000_000)))
        producer = self.root / 'producer.py'
        producer.write_text('import sys\n'
                            'sys.stdout.write(open(sys.argv[1]).read())\n')
        result = subprocess.run(
            ['bash', '-c', '"$1" "$2" "$3" | "$1" "$4"; echo "${PIPESTATUS[0]}"',
             'bash', sys.executable, str(producer), str(payload), str(SOURCE)],
            text=True, timeout=30, capture_output=True, env=self.env)
        self.assertEqual('0', result.stdout.strip(), result.stderr)

    def test_a_noisy_write_hook_log_cannot_reach_the_parents_streams(self):
        # The child inherits fd 1 and fd 2 unless they are closed off. The
        # two other callers block them with `3>&2 2>/dev/null`; here the
        # structural "cannot deny" of spec section 4 must not depend on
        # today's write-hook-log happening to stay silent.
        stage = self.root / 'stage'
        stage.mkdir()
        copy = stage / 'record-coverage'
        copy.write_bytes(SOURCE.read_bytes())
        (stage / 'write-hook-log').write_text(
            'import sys\n'
            'sys.stdin.read()\n'
            'sys.stdout.write("{\"hookSpecificOutput\": 1}")\n'
            'sys.stderr.write("noise")\n')
        result = subprocess.run(
            [sys.executable, str(copy)], input=json.dumps(event()), text=True,
            timeout=10, capture_output=True,
            env=dict(self.env, TOKEN_SHUNT_HOOK_LOG=str(self.root / 'quiet')))
        self.assertEqual((0, '', ''),
                         (result.returncode, result.stdout, result.stderr))

class WiringTests(unittest.TestCase):
    def test_the_hook_is_registered_after_record_intake_on_post_read(self):
        config = json.loads((HOOKS / 'hooks.json').read_text())
        post = [g for g in config['hooks']['PostToolUse']
                if g.get('matcher') == 'Read'][0]['hooks']
        names = [h['command'].rsplit('/', 1)[-1] for h in post]
        self.assertEqual(['check-reader-contract', 'record-intake',
                          'record-coverage'], names)

    def test_the_hook_is_executable(self):
        self.assertTrue(os.access(str(SOURCE), os.X_OK))
