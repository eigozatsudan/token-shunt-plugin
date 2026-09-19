"""Per-file coverage from the hook's own log, and nothing from transcripts.

Design: docs/superpowers/specs/2026-09-19-targeted-read-coverage-design.md

The denominator (totalLines) exists only in the PostToolUse event, so this
reads what `plugin/hooks/record-coverage` wrote and never parses a
transcript. It reports what the parent did; it does not score it.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
import read_coverage  # noqa: E402


def line(path='/c/a.py', start=1, lines=10, total=100, bytes=500,
         session='s1', agent=None, agent_type=None, offset=1, limit=10,
         is_error=False):
    return {'hook': 'record-coverage', 'session_id': session, 'agent_id': agent,
            'agent_type': agent_type, 'file_path': path, 'start': start,
            'lines': lines, 'total': total, 'bytes': bytes, 'offset': offset,
            'limit': limit, 'is_error': is_error}


class CoverageTests(unittest.TestCase):
    def only(self, *records):
        got = read_coverage.rows(list(records))
        self.assertEqual(1, len(got), got)
        return got[0]

    def test_two_overlapping_reads_count_the_shared_lines_once(self):
        got = self.only(line(start=1, lines=10), line(start=6, lines=10))
        self.assertEqual(15, got['covered'])
        self.assertEqual(5, got['overlap'])
        self.assertEqual(1, got['segments'])
        self.assertEqual(2, got['reads'])

    def test_adjacent_reads_make_one_segment(self):
        got = self.only(line(start=1, lines=10), line(start=11, lines=10))
        self.assertEqual((20, 0, 1), (got['covered'], got['overlap'], got['segments']))

    def test_reads_with_a_gap_stay_two_segments(self):
        got = self.only(line(start=1, lines=10), line(start=50, lines=10))
        self.assertEqual((20, 0, 2), (got['covered'], got['overlap'], got['segments']))

    def test_one_full_read_is_complete_coverage(self):
        got = self.only(line(start=1, lines=100, total=100, offset=None, limit=None))
        self.assertEqual(1.0, got['coverage'])

    def test_a_failed_read_is_counted_but_covers_nothing(self):
        got = self.only(line(start=1, lines=10),
                        line(start=None, lines=None, total=None, bytes=0,
                             is_error=True))
        self.assertEqual((2, 10), (got['reads'], got['covered']))

    def test_a_file_that_changed_size_reports_no_rate(self):
        # An Edit between two reads moves the denominator. Averaging across
        # it would be a number nobody can defend.
        got = self.only(line(start=1, lines=10, total=100),
                        line(start=20, lines=10, total=140))
        self.assertIs(True, got['total_changed'])
        self.assertIsNone(got['coverage'])
        self.assertEqual(140, got['total'])

    def test_parent_and_worker_are_separate_rows(self):
        got = read_coverage.rows([line(agent=None), line(agent='a7')])
        self.assertEqual([True, False], [r['parent'] for r in got])
        self.assertEqual([10, 10], [r['covered'] for r in got])

    def test_a_worker_known_only_by_its_type_is_not_filed_as_the_parent(self):
        # intake_ledger.py:134 judges a parent by `not (agent_id or
        # agent_type)`. Grouping on agent_id alone merges this worker's
        # full-file reads into the parent's row.
        got = read_coverage.rows([
            line(agent=None, start=1, lines=10),
            line(agent=None, agent_type='token-shunt:bulk-reader',
                 start=1, lines=100)])
        self.assertEqual(2, len(got))
        self.assertEqual([True, False], [r['parent'] for r in got])
        self.assertEqual([10, 100], [r['covered'] for r in got])

    def test_a_read_past_the_end_of_the_file_reports_no_rate(self):
        # check-reader-contract:143 treats start+count-1 <= total as a
        # validity condition. Broken data is not a coverage of 1.4.
        got = self.only(line(start=1, lines=140, total=100))
        self.assertIs(True, got['impossible'])
        self.assertIsNone(got['coverage'])

    def test_the_rollup_leaves_out_the_rows_with_no_rate(self):
        got = read_coverage.rollup(read_coverage.rows([
            line(path='/c/a.py', start=1, lines=25, total=100),
            line(path='/c/b.py', start=1, lines=10, total=100),
            line(path='/c/b.py', start=20, lines=10, total=140)]))
        self.assertEqual(1, got['files'])
        self.assertEqual(25, got['covered'])
        self.assertEqual(100, got['total'])
        self.assertEqual(0.25, got['coverage'])
        self.assertEqual(1, got['excluded'])

    def test_two_sessions_in_one_log_are_reported(self):
        # A follow-up turn that starts a new session would split one
        # conversation's coverage in two and read as a lower rate.
        self.assertEqual(['s1', 's2'], read_coverage.sessions(
            [line(session='s1'), line(session='s2'), line(session='s1')]))


class LoadTests(unittest.TestCase):
    def test_other_hooks_lines_are_ignored(self):
        # The hook log is shared: check-file-size writes {hook,decision,...}
        # into the same file.
        with tempfile.NamedTemporaryFile('w', suffix='.hooklog',
                                         delete=False) as handle:
            handle.write(json.dumps({'hook': 'check-file-size',
                                     'decision': 'deny'}) + '\n')
            handle.write(json.dumps(line()) + '\n')
            handle.write('truncated{\n')
            name = handle.name
        self.addCleanup(lambda: Path(name).unlink())
        self.assertEqual(1, len(read_coverage.load(name)))
