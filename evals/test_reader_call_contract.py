"""Check the reader call contract source of truth and its deny rendering."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / 'plugin/hooks'
CONTRACT = HOOKS / 'reader-call-contract'

# The rendered deny must carry the call spec; these markers identify it.
MARKERS = ('Agent: subagent_type=token-shunt:bulk-reader',
           'use haiku. Pass a concrete model, never "auto".',
           'First call only.',
           'paths:')


class ContractBodyTests(unittest.TestCase):
    def test_placeholders_are_present_on_their_own_lines(self):
        lines = CONTRACT.read_text(encoding='utf-8').split('\n')
        self.assertIn('{REASON}', lines)
        self.assertIn('{PATHS}', lines)

    def test_fixed_body_stays_within_900_bytes(self):
        lines = [l for l in CONTRACT.read_text(encoding='utf-8').split('\n')
                 if l not in ('{REASON}', '{PATHS}')]
        fixed = '\n'.join(lines).encode('utf-8')
        self.assertLessEqual(len(fixed), 900, len(fixed))
        self.assertGreater(len(fixed), 400, 'contract looks truncated')

    def test_contract_states_the_required_obligations(self):
        body = CONTRACT.read_text(encoding='utf-8')
        for marker in MARKERS[:3]:
            self.assertIn(marker, body)
        self.assertIn('unabbreviated', body)
        self.assertIn('status: complete|partial', body)


# Captured from the unmodified hooks on 2026-09-14. The fallback path must keep
# returning exactly this, not the shortened template reason.
LEGACY_READ_SIZE = (
    'File exceeds token-shunt thresholds (bytes=%d/65536). '
    'Use /token-shunt:bulk-reader. For edits, use a targeted Read of the '
    'original that passes the hook. If that fails, editing is outside v0.1 scope.')
LEGACY_BASH_SIZE = (
    "Bash 'cat' on a large file exceeds token-shunt thresholds (bytes=%d/65536). "
    'Use /token-shunt:bulk-reader. For edits, use a targeted Read of the '
    'original that passes the hook.')


class RenderedDenyTests(unittest.TestCase):
    """The template must reach the parent only on delegable reader denies."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.big = self.root / 'big.txt'
        self.big.write_bytes(b'x\n' * 200000)
        self.small = self.root / 'small.txt'
        self.small.write_bytes(b'ok\n')
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith('TOKEN_SHUNT_') and k != 'CDPATH'}

    def invoke(self, event, hook='check-file-size', hooks=None):
        result = subprocess.run([str((hooks or HOOKS) / hook)],
                                input=json.dumps(event), cwd=self.root,
                                env=self.env, text=True, capture_output=True,
                                timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        if not result.stdout:
            return 'pass', ''
        payload = json.loads(result.stdout)['hookSpecificOutput']
        return payload['permissionDecision'], payload['permissionDecisionReason']

    def assertTemplated(self, reason):
        for marker in MARKERS:
            self.assertIn(marker, reason)

    def assertNotTemplated(self, reason):
        self.assertNotIn(MARKERS[0], reason)
        self.assertIn('bulk-reader', reason)

    def test_size_exceeded_read_carries_the_contract_and_real_size(self):
        decision, reason = self.invoke({'cwd': str(self.root),
                                        'tool_input': {'file_path': 'big.txt'}})
        self.assertEqual(decision, 'deny')
        self.assertTemplated(reason)
        self.assertIn('%s (%d B)' % (self.big, self.big.stat().st_size), reason)
        self.assertNotIn('{REASON}', reason)
        self.assertNotIn('{PATHS}', reason)

    def test_bad_limit_on_an_oversized_file_carries_the_contract(self):
        for bad in ('0', 'abc', '-1'):
            decision, reason = self.invoke(
                {'cwd': str(self.root),
                 'tool_input': {'file_path': 'big.txt', 'limit': bad}})
            self.assertEqual(decision, 'deny', bad)
            self.assertTemplated(reason)

    def test_oversized_range_carries_the_contract(self):
        decision, reason = self.invoke(
            {'cwd': str(self.root),
             'tool_input': {'file_path': 'big.txt', 'limit': 190000, 'offset': 2}})
        self.assertEqual(decision, 'deny')
        self.assertTemplated(reason)

    def test_worker_read_still_passes(self):
        decision, _ = self.invoke({'cwd': str(self.root),
                                   'agent_type': 'token-shunt:bulk-reader',
                                   'tool_input': {'file_path': 'big.txt'}})
        self.assertEqual(decision, 'pass')

    def test_small_file_still_passes(self):
        decision, _ = self.invoke({'cwd': str(self.root),
                                   'tool_input': {'file_path': 'small.txt'}})
        self.assertEqual(decision, 'pass')

    def legacy(self):
        """The exact wording the parent sees today, for full-string equality."""
        return LEGACY_READ_SIZE % self.big.stat().st_size

    def broken_contract(self, name, mutate):
        alt = self.root / name
        shutil.copytree(HOOKS, alt)
        mutate(alt / 'reader-call-contract')
        return alt

    def test_missing_contract_falls_back_to_the_current_wording(self):
        alt = self.broken_contract('hooks1', lambda f: f.unlink())
        decision, reason = self.invoke({'cwd': str(self.root),
                                        'tool_input': {'file_path': 'big.txt'}},
                                       hooks=alt)
        self.assertEqual(decision, 'deny')
        self.assertEqual(reason, self.legacy())

    def test_unreadable_contract_falls_back_to_the_current_wording(self):
        if os.geteuid() == 0:
            self.skipTest('root ignores the unreadable mode')
        alt = self.broken_contract('hooks2', lambda f: f.chmod(0o000))
        self.addCleanup((alt / 'reader-call-contract').chmod, 0o644)
        decision, reason = self.invoke({'cwd': str(self.root),
                                        'tool_input': {'file_path': 'big.txt'}},
                                       hooks=alt)
        self.assertEqual(decision, 'deny')
        self.assertEqual(reason, self.legacy())

    def test_placeholderless_contract_falls_back(self):
        alt = self.broken_contract(
            'hooks3',
            lambda f: f.write_text('no placeholders here\n', encoding='utf-8'))
        decision, reason = self.invoke({'cwd': str(self.root),
                                        'tool_input': {'file_path': 'big.txt'}},
                                       hooks=alt)
        self.assertEqual(decision, 'deny')
        self.assertEqual(reason, self.legacy())


# New test classes from later tasks go ABOVE this block. unittest.main() must
# stay the last thing in this file: evals/run.sh executes this module
# directly (python3 -B evals/test_reader_call_contract.py), so anything
# appended after this block would never be loaded.
if __name__ == '__main__':
    unittest.main()
