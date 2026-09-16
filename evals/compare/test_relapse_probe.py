"""The relapse instrument, on synthetic sessions.

Stage 0 of reviews/relapse-device-design-2026-09-16.md. The requirement
that shapes it: the control arm has no relapse check in the product, so
the trial log cannot count relapses there. The probe has to read a
finished session and decide for itself, from the closing message and what
the parent said before it.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'plugin', 'hooks'))

import relapse_probe as rp
import test_session_extract as ts


class ProbeFixture(ts.SessionFixture):
    def setUp(self):
        # A real file on disk: a citation that does not resolve is
        # undetermined rather than a violation.
        super().setUp()
        self.src = os.path.join(self.dir, 'user.rb')
        with open(self.src, 'w', encoding='utf-8') as fh:
            fh.write('class User\n')
        self.line = 'confirmed: %s — class User' % self.src

    def write_turn(self, *assistant_texts, worker=None):
        worker = self.line if worker is None else worker
        rows = [ts.prompt(), ts.assistant(ts.tool_use()), ts.tool_result(),
                ts.note(result=worker)]
        rows += [ts.assistant(ts.text(t)) for t in assistant_texts]
        return self.write(rows, worker=worker)


class SplitTests(ProbeFixture):
    def test_the_last_assistant_message_is_the_closing(self):
        self.write_turn('Restating:\n' + self.line, 'In short: it sends mail.')
        earlier, closing = rp.split_turn(rp.rows(self.session))
        self.assertEqual('In short: it sends mail.', closing)
        self.assertIn(self.line, earlier)

    def test_a_worker_message_is_not_the_parent_speaking(self):
        rows = rp.rows(self.write_turn('Answer.\n' + self.line, 'Short.'))
        rows.append(dict(ts.assistant(ts.text('worker chatter')),
                         isSidechain=True))
        earlier, closing = rp.split_turn(rows)
        self.assertEqual('Short.', closing)

    def test_a_single_message_turn_has_no_earlier_text(self):
        self.write_turn('Only one message.\n' + self.line)
        earlier, closing = rp.split_turn(rp.rows(self.session))
        self.assertEqual('', earlier)
        self.assertIn(self.line, closing)

    def test_a_session_without_assistant_text_is_empty(self):
        self.write_turn()
        self.assertEqual(('', None), rp.split_turn(rp.rows(self.session)))


class ScoreTests(ProbeFixture):
    def test_restated_then_closed_short_is_a_relapse(self):
        self.write_turn('Restating:\n' + self.line, 'In short: it sends mail.')
        got = rp.score_session(self.session)
        self.assertTrue(got['relapse'])
        self.assertEqual('violation', got['status'])
        self.assertEqual([self.line], got['lost'])
        # The closing message is the answer, so the run ends without them.
        self.assertFalse(got['final_retained'])

    def test_a_closing_message_that_keeps_the_lines_is_not_a_relapse(self):
        self.write_turn('Restating:\n' + self.line, 'Done.\n' + self.line)
        got = rp.score_session(self.session)
        self.assertFalse(got['relapse'])
        self.assertTrue(got['final_retained'])

    def test_a_turn_that_never_restated_is_not_a_relapse(self):
        # Never repaired: a different failure, and not what the fix judges.
        self.write_turn('A summary.', 'Another summary.')
        got = rp.score_session(self.session)
        self.assertFalse(got['relapse'])
        self.assertEqual('undetermined', got['status'])
        self.assertFalse(got['final_retained'])

    def test_a_single_message_answer_is_never_a_relapse(self):
        self.write_turn('Answer.\n' + self.line)
        got = rp.score_session(self.session)
        self.assertFalse(got['relapse'])
        self.assertTrue(got['final_retained'])

    def test_an_unreadable_worker_leaves_it_unmeasured(self):
        self.write_turn('Restating.', 'Short.', worker='status: complete')
        got = rp.score_session(self.session)
        self.assertIsNone(got['relapse'])
        self.assertEqual('unmeasured', got['status'])

    def test_a_missing_session_is_unmeasured(self):
        got = rp.score_session(os.path.join(self.dir, 'gone.jsonl'))
        self.assertIsNone(got['relapse'])
        self.assertEqual('unmeasured', got['status'])


class TrialLogTests(ProbeFixture):
    """E3 and E4 come from the product's own trial log, not from the probe."""

    def log(self, *records):
        path = os.path.join(self.dir, 't.jsonl.sendback.jsonl')
        with open(path, 'w', encoding='utf-8') as fh:
            for rec in records:
                fh.write(json.dumps(rec) + '\n')
        return path

    def test_relapse_blocks_are_counted_per_session(self):
        path = self.log({'outcome': 'blocked', 'relapse': True, 'session_id': 's1'},
                        {'outcome': 'blocked', 'session_id': 's1'},
                        {'outcome': 'reblock_suppressed', 'relapse_status': 'violation',
                         'session_id': 's1'})
        got = rp.relapse_blocks(path)
        self.assertEqual({'s1': 1}, got)

    def test_two_relapse_blocks_in_one_session_are_visible(self):
        # E4: the budget says this cannot happen. The probe must be able to
        # show it if it does, or the safety item is unmeasurable.
        path = self.log({'outcome': 'blocked', 'relapse': True, 'session_id': 's1'},
                        {'outcome': 'blocked', 'relapse': True, 'session_id': 's1'})
        self.assertEqual({'s1': 2}, rp.relapse_blocks(path))

    def test_a_missing_log_counts_nothing(self):
        self.assertEqual({}, rp.relapse_blocks(os.path.join(self.dir, 'none')))


if __name__ == '__main__':
    unittest.main()
