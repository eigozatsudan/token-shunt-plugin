"""Exercise the runner's real reset/selection functions without a model call."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class RunnerIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.compare = Path(self.temp.name) / "evals" / "compare"
        self.compare.mkdir(parents=True)
        source = Path(__file__).parent
        for name in ("run.sh", "cases.json", "judge.py", "routing_checks.py",
                     "flow_checks.py", "report_text.py", "writer_unittest_check.py"):
            shutil.copy2(source / name, self.compare / name)
        for name in ("rails", "codegen"):
            shutil.copytree(source / "fixtures" / name,
                            self.compare / "fixtures" / name)

    def shell(self, code, *args):
        return subprocess.run(
            ["bash", "-c", 'source "$1"\n' + code, "review-test",
             str(self.compare / "run.sh"), *args],
            text=True, capture_output=True)

    def test_startup_failure_invalidates_previous_summary(self):
        summary = self.compare / "last-run.json"
        summary.write_text('{"selected_run_valid":true,"release_eligible":true}')
        # A broken fixture source fails after planning, before any CLI call.
        shutil.rmtree(self.compare / "fixtures" / "rails")
        bindir = Path(self.temp.name) / "bin"
        bindir.mkdir()
        cli = bindir / "claude"
        cli.write_text("#!/bin/sh\nexit 99\n")
        cli.chmod(0o755)
        result = subprocess.run(["bash", str(self.compare / "run.sh")],
                                env={**os.environ, "PATH": str(bindir) + os.pathsep + os.environ["PATH"]},
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        verdict = json.loads(summary.read_text())
        self.assertFalse(verdict["selected_run_valid"])
        self.assertFalse(verdict["release_eligible"])
        self.assertIn("incomplete", verdict["errors"][0])

    def test_every_mode_starts_with_clean_targets_and_restored_references(self):
        result = self.shell('''
ONLY=''; SUITE=''; setup_run || exit 1
gen_fixtures || exit 2
original=$(cat "$FIX/codegen/greeter.py")
printf 'evidence' > "$VRD/retained.json"
printf 'old target' > "$TMP/large_test.py"
printf 'old target' > "$TMP/small_cfg.json"
printf 'old target' > "$FIX/codegen/out/old.py"
printf 'mutated reference' > "$FIX/codegen/greeter.py"
printf 'mutated fixture' > "$GEN/bulk_facts.py"
gen_fixtures || exit 3
[[ ! -e $TMP/large_test.py && ! -e $TMP/small_cfg.json ]] || exit 4
[[ ! -e $FIX/codegen/out/old.py ]] || exit 5
[[ $(cat "$FIX/codegen/greeter.py") == "$original" ]] || exit 6
[[ $(wc -c < "$GEN/bulk_facts.py") -gt 65536 ]] || exit 7
[[ -s $VRD/retained.json ]] || exit 8
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_edit_hint_gold_and_prompts_agree_with_disk_check(self):
        result = self.shell('''
ONLY=auto-edit-grep-location; SUITE=B; setup_run || exit 1
gen_fixtures || exit 2
cp "$GEN/edit_hint.py" "$SNAP/auto-edit-grep-location.edit_hint.pre"
python3 - "$GEN" "$CMP/cases.json" <<'PY'
import json, sys
from pathlib import Path
gen = Path(sys.argv[1])
case = next(c for c in json.loads(Path(sys.argv[2]).read_text())['cases']
            if c['id'] == 'auto-edit-grep-location')
gold, = json.loads((gen / 'gold-edit-hint.json').read_text())
for key in ('prompt_direct', 'prompt_delegate'):
    assert gold in case[key]
target = gen / 'edit_hint.py'
body = target.read_bytes()
old = case['expect']['direct']['edit_flow']['original_mark'].encode()
assert body.count(old) == 1
target.write_bytes(body.replace(old, gold.encode()))
PY
[[ $? == 0 ]] || exit 3
spec=$(jq -c '.cases[] | select(.id == "auto-edit-grep-location")' "$CMP/cases.json")
disk_check "$spec" direct || exit 4
cat "$GEN/gold-edit-hint.json"
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), ["HDR_MODE = 'on'"])

    def test_fifty_line_fixture_matches_question_and_gold(self):
        result = self.shell("ONLY=''; SUITE=''; setup_run && gen_fixtures && cat \"$GEN/bounds/l50.py\"")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 50)
        self.assertEqual(lines[49], 'def task_fifty(): return 50')
        namespace = {}
        exec(compile(result.stdout, 'l50.py', 'exec'), namespace)
        self.assertEqual(namespace['task_fifty'](), 50)

    def test_edit_flow_prompt_states_the_required_procedure(self):
        # §11.6 / design row 835 requires Grep -> targeted Read -> Edit in all
        # four modes, but `direct` loads no plugin and sees no hook guidance,
        # so the shared prompt has to carry the procedure itself.
        cases = json.loads((self.compare / "cases.json").read_text())["cases"]
        for case_id in ("auto-edit-grep-location", "auto-edit-grep-ambiguous"):
            case = next(c for c in cases if c["id"] == case_id)
            for key in ("prompt_direct", "prompt_delegate"):
                with self.subTest(case=case_id, prompt=key):
                    prompt = case[key].lower()
                    self.assertIn("grep", prompt, key)
                    self.assertIn("targeted read", prompt, key)
                    self.assertLess(prompt.index("grep"), prompt.index("targeted read"), key)
                    self.assertLess(prompt.index("targeted read"), prompt.rindex("edit"), key)
                    self.assertIn("narrow", prompt, key)

    def test_rails_fixture_keeps_delegation_threshold_with_bounded_padding(self):
        model = self.compare / 'fixtures/rails/app/models/user.rb'
        body = model.read_bytes()
        self.assertGreater(len(body.splitlines()), 350)
        self.assertGreater(len(body), 16384)
        # Leave headroom for sequential reads of user plus two related files.
        # Native tool behavior remains a live-eval requirement.
        self.assertLess(len(body), 24576)
        self.assertIn(b'after_create :send_welcome_email', body)
        self.assertIn(b'def send_welcome_email\n    deliver_notifications', body)

    def test_runs_have_distinct_evidence_and_manifest_selects_exact_modes(self):
        result = self.shell('''
ONLY=auto-small-files; SUITE=B; setup_run || exit 1
first=$RUN_ROOT
printf 'stale' > "$VRD/stale.auto.json"
setup_run || exit 2
[[ $first != "$RUN_ROOT" && ! -e $VRD/stale.auto.json ]] || exit 3
cat "$MANIFEST"
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = json.loads(result.stdout)
        self.assertEqual(manifest["planned"], [
            {"case": "auto-small-files", "mode": mode}
            for mode in ("direct", "haiku", "sonnet", "auto")])
        self.assertGreater(len(manifest["required"]), len(manifest["planned"]))

    def test_unknown_case_is_an_error_before_any_model_call(self):
        result = self.shell("ONLY=does-not-exist; SUITE=''; setup_run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no cases match", result.stdout)

    def run_with_cli_double(self, only="auto-small-files", **settings):
        # Exercise the shell loop, resolved specs, judge and aggregate together.
        # The double only emits a small-files transcript; no live model is used.
        bindir = Path(self.temp.name) / "bin"
        bindir.mkdir(exist_ok=True)
        cli = bindir / "claude"
        cli.write_text('#!' + sys.executable + '\n' + '''
import json, os, re, sys
if sys.argv[1:3] == ['plugin', 'validate']:
    sys.exit(0)
prompt = sys.stdin.read()
loaded = '--plugin-dir' in sys.argv
probe = prompt == 'Reply with just OK'
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write(('load' if loaded else 'isolation') if probe
              else ('case resume' if '--resume' in sys.argv else 'case'))
    log.write('\\n')
failure = os.environ.get('PROBE_FAILURE') if probe and (
    os.environ.get('FAIL_PROBE') == ('load' if loaded else 'isolation')) else None
if not probe:
    failure = os.environ.get('CASE_FAILURE')
if failure == 'empty':
    sys.exit(0)
print(json.dumps({'type':'system','subtype':'init','session_id':'sess-double',
    'plugins':([{'name':'token-shunt'}] if loaded or failure == 'loaded-direct' else [])
        + ([{'name':'superpowers'}] if failure == 'dormant-plugin' else []),
    'agents':['token-shunt:bulk-reader','token-shunt:code-writer'] if loaded else []}))
if failure == 'init-only':
    sys.exit(0)
if failure == 'foreign-hook':
    print(json.dumps({'type':'system','subtype':'hook_response',
        'hook_name':'foreign:PreToolUse'}))
if failure == 'compact-hook':
    print(json.dumps({'type':'system','subtype':'hook_response',
        'hook_name':'SessionStart:compact','hook_event':'SessionStart'}))
if failure == '429':
    print(json.dumps({'type':'result','subtype':'success','is_error':True,
        'result':'Rate limit reached','terminal_reason':'api_error','api_error_status':429}))
    sys.exit(0)
if failure == 'invalid-result':
    print(json.dumps({'type':'result','is_error':False,'result':None}))
    sys.exit(0)
if failure == 'missing-error-flag':
    print(json.dumps({'type':'result','result':'OK'}))
    sys.exit(0)
for i, path in enumerate(re.findall(r'(/[^\\s]+/gen/small3/[abc]\\.txt)', prompt)):
    uid = 'read-' + str(i)
    print(json.dumps({'type':'assistant','message':{'id':uid,'content':[
      {'type':'tool_use','id':uid,'name':'Read','input':{'file_path':path}}]}}))
    with open(path) as f: body=f.read()
    print(json.dumps({'type':'user','message':{'content':[
      {'type':'tool_result','tool_use_id':uid,'content':body,'is_error':False}]}}))
print(json.dumps({'type':'result','is_error':False,
    'result':'ALPHA-111 BRAVO-222 CHARLIE-333',
    'usage':{'input_tokens':10,'output_tokens':5,
             'cache_read_input_tokens':0,'cache_creation_input_tokens':0}}))
sys.exit(17 if failure == 'nonzero' else 0)
''')
        cli.chmod(0o755)
        result = subprocess.run(
            ["bash", str(self.compare / "run.sh"), only],
            text=True, capture_output=True,
            env={**os.environ, "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
                 "SUITE": "", "CALL_LOG": str(Path(self.temp.name) / "calls.log"),
                 **settings})
        return result

    def test_cli_environment_preserves_model_overrides_but_removes_hook_settings(self):
        result = self.shell("""
ONLY=''; SUITE=''; setup_run || exit 1
mkdir -p "$TMP/bin"
cat > "$TMP/bin/claude" <<'CLI'
#!/bin/bash
printf '%s\\n' "${TOKEN_SHUNT_MIN_BYTES-unset}" "${CDPATH-unset}" "$ANTHROPIC_MODEL" "$TOKEN_SHUNT_EVAL_FIXTURES"
CLI
chmod +x "$TMP/bin/claude"
export PATH="$TMP/bin:$PATH" TOKEN_SHUNT_MIN_BYTES=999999 CDPATH=/unwanted ANTHROPIC_MODEL=override
run_claude prompt "$TRD/env"
cat "$TRD/env"
printf '%s\\n' "$FIX"
""")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[:3], ['unset', 'unset', 'override'])
        self.assertEqual(lines[3], lines[4])

    def test_declared_gold_invalid_aborts_cases_before_cli(self):
        catalog_path = self.compare / 'cases.json'
        catalog = json.loads(catalog_path.read_text())
        case = next(c for c in catalog['cases'] if c['id'] == 'auto-small-files')
        gold = self.compare / 'fixtures/rails/test-gold.json'
        for content in (None, 'not json', '[]', '{}', '[""]', '[1]', '["ok"] ["extra"]'):
            with self.subTest(content=content):
                if content is None:
                    gold.unlink(missing_ok=True)
                else:
                    gold.write_text(content)
                case['gold_file'] = 'rails/test-gold.json'
                catalog_path.write_text(json.dumps(catalog))
                calls = Path(self.temp.name) / 'calls.log'
                calls.write_text('')
                result = self.run_with_cli_double()
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('invalid or missing declared gold_file', result.stdout)
                self.assertNotIn('case', calls.read_text().splitlines())
                summary = json.loads((self.compare / 'last-run.json').read_text())
                self.assertFalse(summary['selected_run_valid'])
                self.assertFalse(summary['release_eligible'])
                for verdict in summary['cases']['auto-small-files']['modes'].values():
                    self.assertIn('invalid or missing declared gold_file', verdict['reasons'])
                    self.assertNotIn('missing or mismatched spec/verdict identity', verdict['reasons'])

    def test_native_read_limit_is_pinned_and_recorded_across_modes(self):
        catalog = json.loads((self.compare / 'cases.json').read_text())
        for case in catalog['cases']:
            if case['id'] in ('compare-one-line', 'auto-one-line'):
                self.assertEqual(case['read_max_output_tokens'], 40000)
        for expected in (25000, 40000):
            with self.subTest(limit=expected):
                result = self.shell('''
ONLY=''; SUITE=''; setup_run || exit 1
mkdir -p "$TMP/bin"
cat > "$TMP/bin/claude" <<'CLI'
#!/bin/bash
printf '%s' "$CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS"
CLI
chmod +x "$TMP/bin/claude"
export PATH="$TMP/bin:$PATH" CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS=1
READ_MAX_OUTPUT_TOKENS=$2
run_claude prompt "$TRD/read-cap"
cat "$TRD/read-cap"
''', str(expected))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, str(expected))
        result = self.run_with_cli_double(CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS='1')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for spec in (self.compare / 'tmp/runs').glob('*/specs/auto-small-files.*.json'):
            self.assertEqual(json.loads(spec.read_text())['read_max_output_tokens'], 25000)

    def test_selected_run_end_to_end_with_local_cli_double(self):
        result = self.run_with_cli_double()
        self.assertIn('probes: pass=3 fail=0', result.stdout)
        self.assertIn('done: pass=4 fail=0 runs=4', result.stdout)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        verdict = json.loads((self.compare / "last-run.json").read_text())
        self.assertTrue(verdict["selected_run_valid"])
        self.assertFalse(verdict["release_eligible"])
        self.assertEqual(set(verdict["cases"]), {"auto-small-files"})

    def test_summary_uses_final_verdicts_and_keeps_errors_out_of_run_counts(self):
        summary = self.compare / 'summary.json'
        summary.write_text(json.dumps({
            'cases': {'example': {'modes': {
                'direct': {'verdict': 'pass', 'reasons': []},
                'auto': {'verdict': 'fail', 'reasons': ['isolation: baseline missing']},
                'sonnet': {'verdict': 'fail', 'reasons': ['disk: invalid artifact']},
            }}},
            'fail_count': 3, 'errors': ['missing isolation fixture'],
        }))
        result = self.shell('PASS=6; FAIL=0; CASE_N=3; report_summary "$2"', str(summary))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            'done: pass=1 fail=2 runs=3',
            'FAIL example/auto: isolation: baseline missing',
            'FAIL example/sonnet: disk: invalid artifact',
            'ERROR missing isolation fixture',
        ])

    def test_summary_rejects_incomplete_aggregate(self):
        summary = self.compare / 'summary.json'
        summary.write_text('{"errors":["run incomplete"]}')
        result = self.shell('report_summary "$2"', str(summary))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('done:', result.stdout)

    def test_case_nonzero_exit_is_recorded_but_complete_evidence_still_passes(self):
        result = self.run_with_cli_double(CASE_FAILURE='nonzero')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        verdict = json.loads((self.compare / 'last-run.json').read_text())
        self.assertTrue(verdict['selected_run_valid'])
        for mode in verdict['cases']['auto-small-files']['modes'].values():
            self.assertEqual(mode['cli_exit_code'], 17)
            self.assertEqual(mode['verdict'], 'pass')

    def test_case_error_result_is_not_excused_by_zero_exit(self):
        result = self.run_with_cli_double(CASE_FAILURE='429')
        self.assertNotEqual(result.returncode, 0)
        verdict = json.loads((self.compare / 'last-run.json').read_text())
        self.assertFalse(verdict['selected_run_valid'])
        for mode in verdict['cases']['auto-small-files']['modes'].values():
            self.assertEqual(mode['cli_exit_code'], 0)
            self.assertEqual(mode['verdict'], 'fail')

    def test_failed_probe_runtime_aborts_before_cases(self):
        for probe in ("load", "isolation"):
            for failure, detail in (("empty", "missing init"),
                                    ("init-only", "missing final result"),
                                    ("429", "api_error_status=429"),
                                    ("invalid-result", "invalid or error final result"),
                                    ("missing-error-flag", "invalid or error final result"),
                                    ("nonzero", "claude exit 17")):
                with self.subTest(probe=probe, failure=failure):
                    calls = Path(self.temp.name) / "calls.log"
                    calls.write_text("")
                    result = self.run_with_cli_double(FAIL_PROBE=probe,
                                                      PROBE_FAILURE=failure)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("fail:environment:", result.stdout)
                    self.assertIn(detail, result.stdout)
                    self.assertNotIn("case", calls.read_text().splitlines())
                    verdict = json.loads((self.compare / "last-run.json").read_text())
                    self.assertTrue(verdict["probe_failure"])
                    self.assertTrue(verdict["environment_failure"])
                    self.assertFalse(verdict["selected_run_valid"])
                    self.assertFalse(verdict["release_eligible"])

    def test_isolation_checks_still_reject_loaded_plugin_and_foreign_hooks(self):
        for failure in ("loaded-direct", "foreign-hook", "dormant-plugin", "compact-hook"):
            with self.subTest(failure=failure):
                calls = Path(self.temp.name) / "calls.log"
                calls.write_text("")
                result = self.run_with_cli_double(FAIL_PROBE="isolation",
                                                  PROBE_FAILURE=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("FAIL probe-isolation", result.stdout)
                self.assertNotIn("case", calls.read_text().splitlines())
                verdict = json.loads((self.compare / "last-run.json").read_text())
                self.assertTrue(verdict["probe_failure"])
                self.assertFalse(verdict["environment_failure"])

    def test_load_probe_rejects_dormant_foreign_plugin(self):
        result = self.run_with_cli_double(FAIL_PROBE="load",
                                          PROBE_FAILURE="dormant-plugin")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("superpowers", result.stdout)
        calls = (Path(self.temp.name) / "calls.log").read_text().splitlines()
        self.assertNotIn("case", calls)

    def _claude_prints_trial_log(self):
        return '''
ONLY=''; SUITE=''; setup_run || exit 1
mkdir -p "$TMP/bin"
cat > "$TMP/bin/claude" <<'CLI'
#!/bin/bash
if [[ -n ${SENDBACK_TRIAL_LOG+x} ]]; then printf 'set:%s' "$SENDBACK_TRIAL_LOG"; else printf unset; fi
CLI
chmod +x "$TMP/bin/claude"
export PATH="$TMP/bin:$PATH"
'''

    def test_sendback_trial_log_stays_unset_on_the_baseline(self):
        # The compare suite measures skills, not the send-back
        # (registration decision 3.4). A caller-exported log path must
        # not leak into that baseline
        # (reviews/sendback-fixed-n-probe-design-2026-09-16.md section 7).
        result = self.shell(self._claude_prints_trial_log() + '''
export SENDBACK_TRIAL_LOG=/tmp/should-not-leak
SENDBACK=off
run_claude prompt "$TRD/base"
cat "$TRD/base"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'unset')

    def test_sendback_on_writes_a_per_run_trial_log_path(self):
        result = self.shell(self._claude_prints_trial_log() + '''
SENDBACK=on
run_claude prompt "$TRD/on.jsonl"
cat "$TRD/on.jsonl"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith('set:'), result.stdout)
        self.assertTrue(result.stdout.endswith('on.jsonl.sendback.jsonl'),
                        result.stdout)

    def test_modes_restricts_planned_pairs_and_unset_keeps_every_mode(self):
        result = self.shell('''
ONLY=auto-small-files; SUITE=B; setup_run || exit 1
jq -c .planned "$MANIFEST"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        planned = json.loads(result.stdout)
        self.assertEqual([p['mode'] for p in planned],
                         ['direct', 'haiku', 'sonnet', 'auto'])
        result = self.shell('''
ONLY=auto-small-files; SUITE=B; MODES=haiku,auto; setup_run || exit 1
jq -c .planned "$MANIFEST"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        planned = json.loads(result.stdout)
        self.assertEqual([p['mode'] for p in planned], ['haiku', 'auto'])



    def test_slots_select_exact_case_mode_pairs(self):
        # The probe's eight slots are case/mode pairs, and ONLY x MODES is a
        # cross product: it cannot name them without billing the modes the
        # design excluded
        # (reviews/sendback-fixed-n-probe-design-2026-09-16.md section 4).
        result = self.shell('''
ONLY=''; SLOTS=auto-small-files/haiku,auto-bulk-facts/sonnet; setup_run || exit 1
jq -c '.planned | map(.case + "/" + .mode)' "$MANIFEST"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        # Order follows the catalogue, not the SLOTS list: auto-bulk-facts
        # is declared first and is named second above.
        self.assertEqual(json.loads(result.stdout),
                         ['auto-bulk-facts/sonnet', 'auto-small-files/haiku'])

    def test_a_slot_naming_no_declared_pair_stops_the_run(self):
        # A typo must not quietly bill a smaller set than the one the
        # pre-registered design fixed.
        for bad in ('auto-small-files/opus', 'no-such-case/auto',
                    'auto-small-files'):
            with self.subTest(bad=bad):
                result = self.shell(
                    "ONLY=''; SLOTS=%s; setup_run && echo PLANNED" % bad)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn('PLANNED', result.stdout)
                self.assertIn(bad, result.stdout + result.stderr)

    def test_slots_reach_the_case_loop_not_only_the_manifest(self):
        # The plan and the loop are separate filters; a slot honoured in one
        # and not the other would still bill the modes the design excluded.
        result = self.run_with_cli_double(SLOTS='auto-small-files/haiku')
        calls = Path(self.temp.name) / 'calls.log'
        self.assertEqual(calls.read_text().count('case'), 1, result.stdout)

    def test_unset_slots_plan_every_declared_pair(self):
        result = self.shell('''
ONLY=auto-small-files; setup_run || exit 1
jq -c '.planned | map(.mode)' "$MANIFEST"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         ['direct', 'haiku', 'sonnet', 'auto'])


class FollowUpTurnTests(unittest.TestCase):
    """Several user turns in one session.

    The parent holds no file bodies, so a follow-up question forces a fresh
    worker whose declared set is narrowed -- the opportunity the scope
    measurement counts (reviews/scope-followup-design-2026-09-16.md). A turn
    must continue the session rather than start one, and must not reset the
    tree the question is about.
    """

    # Borrowed, not inherited: subclassing would re-run the isolation suite.
    setUp = RunnerIsolationTests.setUp
    shell = RunnerIsolationTests.shell
    run_with_cli_double = RunnerIsolationTests.run_with_cli_double

    def transcript(self, *rows):
        path = Path(self.temp.name) / "t.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return str(path)

    def test_the_session_id_comes_from_the_init_event(self):
        path = self.transcript({"type": "system", "subtype": "init",
                                "session_id": "abc-123"},
                               {"type": "result", "session_id": "later"})
        result = self.shell('session_id_of "$2"', path)
        self.assertEqual("abc-123", result.stdout.strip())

    def test_a_transcript_without_an_init_event_has_no_session_id(self):
        path = self.transcript({"type": "result", "subtype": "success"})
        result = self.shell('session_id_of "$2"; echo "rc=$?"', path)
        self.assertEqual("rc=0", result.stdout.strip())

    def test_case_turns_substitutes_the_fixture_root(self):
        case = json.dumps({"id": "x", "prompt_turns": [
            "Compare {FIX}/gen/collide/beta.py with what you found.",
            "Which of {FIX}/rails held it?"]})
        result = self.shell('ONLY=""; SUITE=""; setup_run >/dev/null || exit 1\ncase_turns "$2"',
                            case)
        self.assertEqual(result.returncode, 0, result.stderr)
        turns = json.loads(result.stdout)
        self.assertEqual(2, len(turns))
        self.assertNotIn("{FIX}", turns[0])
        self.assertIn("/work/fixtures/gen/collide/beta.py", turns[0])

    def test_a_case_with_no_turns_yields_an_empty_list(self):
        result = self.shell('ONLY=""; SUITE=""; setup_run >/dev/null || exit 1\ncase_turns "$2"',
                            json.dumps({"id": "x"}))
        self.assertEqual([], json.loads(result.stdout))

    def test_a_follow_up_resumes_the_session(self):
        result = self.shell(
            'ONLY=""; SUITE=""; setup_run >/dev/null || exit 1\n'
            '_claude_call() { printf "%s\\n" "$@" >"$RUN_ROOT/args"; }\n'
            'run_claude_resume "second question" "$RUN_ROOT/t2.jsonl" sid-9 '
            '--plugin-dir /p\n'
            'cat "$RUN_ROOT/args"\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        args = result.stdout.split("\n")
        self.assertIn("--resume", args)
        self.assertEqual("sid-9", args[args.index("--resume") + 1])
        self.assertIn("--plugin-dir", args)

    def test_a_follow_up_does_not_reset_the_working_directory(self):
        # fresh_cwd wipes the cwd. Doing that mid-session would delete what
        # the earlier turn left there.
        result = self.shell(
            'ONLY=""; SUITE=""; setup_run >/dev/null || exit 1\n'
            '_claude_call() { :; }\n'
            'fresh_cwd\n'
            'printf kept >"$CWD0/earlier"\n'
            'run_claude_resume q "$RUN_ROOT/t2.jsonl" sid-9\n'
            'cat "$CWD0/earlier"\n')
        self.assertEqual("kept", result.stdout.strip(), result.stderr)

    def test_each_follow_up_gets_its_own_transcript(self):
        path = self.transcript({"type": "system", "subtype": "init",
                                "session_id": "s1"})
        result = self.shell(
            'ONLY=""; SUITE=""; setup_run >/dev/null || exit 1\n'
            '_claude_call() { printf "%s" "$1" >"$2"; }\n'
            'run_followups "$2" \'["first follow-up","second follow-up"]\'\n'
            'cat "$2.turn2.jsonl"; echo\n'
            'cat "$2.turn3.jsonl"\n', path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(["first follow-up", "second follow-up"],
                         result.stdout.strip().split("\n"))

    def test_a_missing_session_id_skips_the_turns_without_failing(self):
        # A first turn that produced no init event still has a verdict;
        # losing the follow-ups must not lose that too.
        path = self.transcript({"type": "result", "subtype": "success"})
        result = self.shell(
            'ONLY=""; SUITE=""; setup_run >/dev/null || exit 1\n'
            '_claude_call() { printf called >>"$RUN_ROOT/called"; }\n'
            'run_followups "$2" \'["follow-up"]\'; echo "rc=$?"\n'
            '[[ -e $RUN_ROOT/called ]] && echo CALLED || echo NOTCALLED\n',
            path)
        self.assertIn("rc=0", result.stdout)
        self.assertIn("NOTCALLED", result.stdout)

    def test_the_loop_runs_the_declared_turns(self):
        cases = self.compare / "cases.json"
        data = json.loads(cases.read_text())
        base = [c for c in data["cases"] if c["id"] == "auto-small-files"][0]
        data["cases"].append(dict(base, id="turn-probe", modes=["auto"],
                                  prompt_turns=["and the second file?",
                                                "and the third?"]))
        cases.write_text(json.dumps(data))
        self.run_with_cli_double(only="turn-probe", SLOTS="turn-probe/auto")
        log = (Path(self.temp.name) / "calls.log").read_text().split("\n")
        self.assertEqual(["case", "case resume", "case resume"],
                         [c for c in log if c.startswith("case")])

    def test_an_experiment_case_is_not_planned_by_default(self):
        # A follow-up case exists to be billed deliberately, by slot. It must
        # not enlarge the default run, and it must not make an ordinary run
        # look incomplete by sitting in `required`.
        self.add_experiment_case()
        result = self.shell("""
ONLY=''; SUITE=''; setup_run || exit 1
jq -c '[.planned[].case] | index("turn-probe")' "$MANIFEST"
jq -c '[.required[].case] | index("turn-probe")' "$MANIFEST"
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(["null", "null"], result.stdout.split())

    def test_an_experiment_case_is_planned_when_its_suite_is_named(self):
        self.add_experiment_case()
        result = self.shell("""
ONLY=''; SUITE=X; setup_run || exit 1
jq -c '[.planned[].case] | unique' "$MANIFEST"
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        planned = json.loads(result.stdout)
        self.assertIn("turn-probe", planned)
        # Naming the shelf plans the shelf and nothing else.
        catalog = json.loads((self.compare / "cases.json").read_text())
        shelf = {c["id"] for c in catalog["cases"] if c.get("suite") == "X"}
        self.assertEqual(shelf, set(planned))

    def add_experiment_case(self, **extra):
        cases = self.compare / "cases.json"
        data = json.loads(cases.read_text())
        base = [c for c in data["cases"] if c["id"] == "auto-small-files"][0]
        data["cases"].append(dict(base, id="turn-probe", suite="X",
                                  modes=["auto"], prompt_turns=["more?"],
                                  **extra))
        cases.write_text(json.dumps(data))

    def test_an_ordinary_run_aggregates_with_an_experiment_case_present(self):
        # The aggregate cross-checks the manifest against cases.json. An
        # experiment sitting in the file must not make every ordinary run
        # report an incomplete suite.
        self.add_experiment_case()
        self.run_with_cli_double()
        summary = json.loads((self.compare / "last-run.json").read_text())
        self.assertEqual([], summary.get("errors", []))
        self.assertTrue(summary["selected_run_valid"])

    def test_an_experiment_run_is_recognized_but_not_release_eligible(self):
        self.add_experiment_case()
        self.run_with_cli_double(only="turn-probe", SLOTS="turn-probe/auto")
        summary = json.loads((self.compare / "last-run.json").read_text())
        self.assertNotIn("unrecognized planned case/mode",
                         summary.get("errors", []))
        self.assertFalse(summary["release_eligible"])

    def test_naming_the_shelf_does_not_shrink_the_mandatory_suite(self):
        # `required` is what a complete suite means; it must not follow the
        # selection. Making it do so made every SUITE=X run report
        # "manifest required pairs differ from mandatory suite".
        self.add_experiment_case()
        result = self.shell("""
ONLY=''; SUITE=X; setup_run || exit 1
jq -c '[.required[].case] | index("turn-probe")' "$MANIFEST"
jq -c '[.required[].case] | index("auto-small-files")' "$MANIFEST"
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        index_of_shelf, index_of_ordinary = result.stdout.split()
        self.assertEqual("null", index_of_shelf)
        self.assertNotEqual("null", index_of_ordinary)

    def test_an_experiment_run_aggregates_without_a_suite_error(self):
        self.add_experiment_case()
        self.run_with_cli_double(only="turn-probe", SUITE="X",
                                 SLOTS="turn-probe/auto")
        summary = json.loads((self.compare / "last-run.json").read_text())
        self.assertEqual([], summary.get("errors", []))

    def test_a_case_without_turns_makes_one_call(self):
        self.run_with_cli_double(SLOTS="auto-small-files/auto")
        log = (Path(self.temp.name) / "calls.log").read_text()
        self.assertEqual(1, log.count("case"))
        self.assertNotIn("resume", log)


if __name__ == "__main__":
    unittest.main()
