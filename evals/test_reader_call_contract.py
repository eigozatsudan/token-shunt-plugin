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


# New test classes from later tasks go ABOVE this block. unittest.main() must
# stay the last thing in this file: evals/run.sh executes this module
# directly (python3 -B evals/test_reader_call_contract.py), so anything
# appended after this block would never be loaded.
if __name__ == '__main__':
    unittest.main()
