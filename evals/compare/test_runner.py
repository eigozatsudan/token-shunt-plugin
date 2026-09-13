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
                     "flow_checks.py", "writer_unittest_check.py"):
            shutil.copy2(source / name, self.compare / name)
        for name in ("rails", "codegen"):
            shutil.copytree(source / "fixtures" / name,
                            self.compare / "fixtures" / name)

    def shell(self, code, *args):
        return subprocess.run(
            ["bash", "-c", 'source "$1"\n' + code, "review-test",
             str(self.compare / "run.sh"), *args],
            text=True, capture_output=True)

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

    def run_with_cli_double(self, **settings):
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
    log.write(('load' if loaded else 'isolation') if probe else 'case')
    log.write('\\n')
failure = os.environ.get('PROBE_FAILURE') if probe and (
    os.environ.get('FAIL_PROBE') == ('load' if loaded else 'isolation')) else None
if not probe:
    failure = os.environ.get('CASE_FAILURE')
if failure == 'empty':
    sys.exit(0)
print(json.dumps({'type':'system','subtype':'init',
    'plugins':[{'name':'token-shunt'}] if loaded or failure == 'loaded-direct' else [],
    'agents':['token-shunt:bulk-reader','token-shunt:code-writer'] if loaded else []}))
if failure == 'init-only':
    sys.exit(0)
if failure == 'foreign-hook':
    print(json.dumps({'type':'system','subtype':'hook_response',
        'hook_name':'foreign:PreToolUse'}))
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
            ["bash", str(self.compare / "run.sh"), "auto-small-files"],
            text=True, capture_output=True,
            env={**os.environ, "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
                 "SUITE": "", "CALL_LOG": str(Path(self.temp.name) / "calls.log"),
                 **settings})
        return result

    def test_selected_run_end_to_end_with_local_cli_double(self):
        result = self.run_with_cli_double()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        verdict = json.loads((self.compare / "last-run.json").read_text())
        self.assertTrue(verdict["selected_run_valid"])
        self.assertFalse(verdict["release_eligible"])
        self.assertEqual(set(verdict["cases"]), {"auto-small-files"})

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
        for failure in ("loaded-direct", "foreign-hook"):
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


if __name__ == "__main__":
    unittest.main()
