import unittest
from judge import reader_fields
from flow_checks import report_fields
import test_unreadable_and_model as helpers


class PresentationTests(unittest.TestCase):
    check = helpers.UnreadableTests.check

    def test_unreadable_decorations_and_empty_confirmed(self):
        for report in (
            '**unconfirmed: /a.py — TOKEN; unread line 1**\n**status: partial**\n**stop_reason: unreadable_line**',
            '`- unconfirmed: /a.py — TOKEN; unread line 1`\n`- status: partial`\n`- stop_reason: unreadable_line`',
            'confirmed:\nunconfirmed: /a.py — TOKEN; unread line 1\nstatus: partial\nstop_reason: unreadable_line'):
            self.assertTrue(self.check([(1, 1, True)], final=report, child=report))
        self.assertFalse(self.check([(1, 1, True)], final='status: partial\nstop_reason: unreadable_line'))

    def test_duplicate_status_is_not_normalized_away(self):
        self.assertIsNone(reader_fields('**status: partial**\nstatus: complete')['status'])

    def test_explained_table_status(self):
        self.assertEqual(({'syntax'}, {'failed'}), report_fields(
            '| syntax | **failed** — `ok: false`, diagnostic "invalid JSON" |'))
        self.assertEqual(set(), report_fields('| syntax | not failed |')[1])
