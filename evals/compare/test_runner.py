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
        for name in ("run.sh", "cases.json", "judge.py", "routing_checks.py", "flow_checks.py"):
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

    def test_selected_run_end_to_end_with_local_cli_double(self):
        # Exercise the shell loop, resolved specs, judge and aggregate together.
        # The double only emits a small-files transcript; no live model is used.
        bindir = Path(self.temp.name) / "bin"
        bindir.mkdir()
        cli = bindir / "claude"
        cli.write_text('#!' + sys.executable + '\n' + '''
import json, re, sys
if sys.argv[1:3] == ['plugin', 'validate']:
    sys.exit(0)
prompt = sys.stdin.read()
loaded = '--plugin-dir' in sys.argv
print(json.dumps({'type':'system','subtype':'init',
    'plugins':[{'name':'token-shunt'}] if loaded else [],
    'agents':['token-shunt:bulk-reader','token-shunt:code-writer'] if loaded else []}))
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
''')
        cli.chmod(0o755)
        result = subprocess.run(
            ["bash", str(self.compare / "run.sh"), "auto-small-files"],
            text=True, capture_output=True,
            env={**os.environ, "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
                 "SUITE": ""})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        verdict = json.loads((self.compare / "last-run.json").read_text())
        self.assertTrue(verdict["selected_run_valid"])
        self.assertFalse(verdict["release_eligible"])
        self.assertEqual(set(verdict["cases"]), {"auto-small-files"})


if __name__ == "__main__":
    unittest.main()
