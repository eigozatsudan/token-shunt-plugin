"""The forwarding counter must not quietly change what it counts."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prompt_forwarding as pf

DENY = ('Explicit delegation (no hook deny) Delegate now - do not read these '
        'paths yourself, and do not load the bulk-reader skill for this call. '
        'Question: what does report_token() return?')
CLEAN = ('Question: what does report_token() return? Paths: /srv/a.py '
         '(65669 bytes)')
OLD_FORMAT = CLEAN + ' One bullet per fact: confirmed: <absolute path> ...'


class ClassifyTests(unittest.TestCase):
    def test_a_forwarded_deny_is_recognised_across_line_wrapping(self):
        wrapped = DENY.replace('do not read these paths yourself',
                               'do not read these\n  paths yourself')
        self.assertTrue(pf.classify_prompt(wrapped)['forwards_deny'])

    def test_a_clean_prompt_carries_neither_marker(self):
        got = pf.classify_prompt(CLEAN)
        self.assertEqual(got, {'forwards_deny': False, 'restates_format': False})

    def test_the_old_response_format_is_counted_separately(self):
        got = pf.classify_prompt(OLD_FORMAT)
        self.assertFalse(got['forwards_deny'])
        self.assertTrue(got['restates_format'])

    def test_an_empty_prompt_is_not_a_launch(self):
        for empty in (None, '', '   '):
            self.assertIsNone(pf.classify_prompt(empty))


class EraTests(unittest.TestCase):
    def test_a_session_lands_in_the_era_it_was_last_written_in(self):
        eras = ((0, 'before'), (100, 'middle'), (200, 'after'))
        self.assertEqual(pf.era(99, eras), 'before')
        self.assertEqual(pf.era(100, eras), 'middle')
        self.assertEqual(pf.era(10 ** 6, eras), 'after')

    def test_every_era_appears_in_a_scan_with_no_sessions(self):
        result = pf.scan('/nonexistent-sessions-*/*.jsonl')
        self.assertEqual(sorted(result), sorted(label for _, label in pf.ERAS))
        self.assertEqual(result[pf.ERAS[0][1]]['launches'], 0)


if __name__ == '__main__':
    unittest.main()
