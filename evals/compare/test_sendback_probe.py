"""The send-back probe scores the pre-registered items, not the suite."""
import json
from pathlib import Path
import tempfile
import unittest

import sendback_probe as sp


class ScoreRunTests(unittest.TestCase):
    def test_a_later_ok_stop_counts_as_parent_repair(self):
        records = [
            {'event': 'Stop', 'outcome': 'blocked',
             'checks': {'line_retention': 'violation'}, 'lost_lines': 3,
             'baseline': {'assistant_replies': 4, 'tool_calls': 1,
                          'transcript_lines': 10}},
            {'event': 'Stop', 'outcome': 'reblock_suppressed',
             'stop_hook_active': True,
             'checks': {'line_retention': 'ok'}},
        ]
        got = sp.score_run(records, {'verdict': 'pass'})
        self.assertEqual(got['p1'], {'blocked': 1, 'repaired': 1})
        self.assertEqual(got['s1'], 0)
        self.assertEqual(got['s4'], 0)

    def test_a_block_on_ok_retention_is_a_false_block(self):
        records = [{'event': 'Stop', 'outcome': 'blocked',
                    'checks': {'line_retention': 'ok'}}]
        got = sp.score_run(records, {'verdict': 'fail'})
        self.assertEqual(got['s1'], 1)
        self.assertEqual(got['p1']['repaired'], 0)

    def test_zero_block_fails_are_collateral_not_a_diff_against_baseline(self):
        records = [{'event': 'Stop', 'outcome': 'no_block',
                    'checks': {'line_retention': 'ok'}}]
        got = sp.score_run(records, {'verdict': 'fail'})
        self.assertEqual(got['s2'], 1)
        self.assertEqual(got['p1']['blocked'], 0)

    def test_a_block_while_stop_hook_active_is_the_cap(self):
        records = [{'event': 'Stop', 'outcome': 'blocked',
                    'stop_hook_active': True,
                    'checks': {'line_retention': 'violation'}}]
        self.assertEqual(sp.score_run(records)['s4'], 1)

    def test_worker_rewrite_after_subagent_block_is_p2(self):
        records = [
            {'event': 'SubagentStop', 'outcome': 'blocked',
             'checks': {'child_items': 'violation'}},
            {'event': 'SubagentStop', 'outcome': 'no_block',
             'checks': {'child_items': 'ok'}},
        ]
        got = sp.score_run(records)
        self.assertEqual(got['p2'], {'blocked': 1, 'repaired': 1})

    def test_not_resumed_needs_the_session_against_the_block_baseline(self):
        records = [{'event': 'Stop', 'outcome': 'blocked',
                    'checks': {'line_retention': 'violation'},
                    'baseline': {'assistant_replies': 2, 'tool_calls': 1,
                                 'transcript_lines': 8}}]
        # Same counts as the baseline: the parent did not act.
        rows = [{'type': 'assistant', 'message': {'content': [{'type': 'text'}]}},
                {'type': 'assistant',
                 'message': {'content': [{'type': 'tool_use', 'name': 'Read'}]}}]
        got = sp.score_run(records, session_rows=rows)
        self.assertEqual(got['s3'], 1)
        got = sp.score_run(records, session_rows=rows + [
            {'type': 'assistant', 'message': {'content': [{'type': 'text'}]}}])
        self.assertEqual(got['s3'], 0)

    def test_an_unreadable_session_leaves_s3_unmeasured_not_zero(self):
        # The hook's baseline is counted from the CLI session file. With no
        # session to compare it against, "no discard observed" would be a
        # safety claim nothing supports.
        records = [{'event': 'Stop', 'outcome': 'blocked',
                    'checks': {'line_retention': 'violation'},
                    'baseline': {'assistant_replies': 2, 'tool_calls': 1,
                                 'transcript_lines': 8}}]
        got = sp.score_run(records)
        self.assertEqual(got['s3'], 0)
        self.assertEqual(got['s3_unmeasured'], 1)


class ScoreDirTests(unittest.TestCase):
    def test_aggregates_named_trial_logs_next_to_transcripts(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'transcripts').mkdir()
        (root / 'verdicts').mkdir()
        trial = root / 'transcripts' / 'compare-explicit-multifile.haiku.jsonl.sendback.jsonl'
        trial.write_text(json.dumps({
            'event': 'Stop', 'outcome': 'blocked',
            'checks': {'line_retention': 'violation'},
        }) + '\n' + json.dumps({
            'event': 'Stop', 'outcome': 'reblock_suppressed',
            'checks': {'line_retention': 'ok'},
        }) + '\n')
        (root / 'verdicts' / 'compare-explicit-multifile.haiku.json').write_text(
            json.dumps({'verdict': 'pass',
                        'metrics': {'total_cost_usd': 0.11}}))
        got = sp.score_dir(root)
        self.assertEqual(got['p1'], {'blocked': 1, 'repaired': 1})
        self.assertEqual(got['c1']['total'], 0.11)
        self.assertEqual(got['runs'], 1)
        # No baseline in the record, so there is no S3 question to answer.
        self.assertEqual(got['s3_unmeasured'], 0)

    def test_s3_reads_the_session_named_by_the_record_not_the_transcript(self):
        # The eval transcript is stream-json from the CLI's stdout; the
        # hook's baseline was counted over the session file it names in
        # `transcript_path`. Comparing one against the other counts rows
        # from two different files.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'transcripts').mkdir()
        (root / 'verdicts').mkdir()
        session = root / 'session.jsonl'
        session.write_text('\n'.join(json.dumps(r) for r in [
            {'type': 'assistant', 'message': {'content': [{'type': 'text'}]}},
            {'type': 'assistant', 'message': {'content': [{'type': 'text'}]}},
        ]))
        stem = 'reader-bounds.auto'
        (root / 'transcripts' / (stem + '.jsonl')).write_text('\n'.join(
            json.dumps(r) for r in [
                {'type': 'assistant', 'message': {'content': [{'type': 'text'}]}}
            ] * 9))
        (root / 'transcripts' / (stem + '.jsonl.sendback.jsonl')).write_text(
            json.dumps({'event': 'Stop', 'outcome': 'blocked',
                        'transcript_path': str(session),
                        'checks': {'line_retention': 'violation'},
                        'baseline': {'assistant_replies': 2, 'tool_calls': 0,
                                     'transcript_lines': 2}}) + '\n')
        got = sp.score_dir(root)
        # The session did not grow past the baseline, so the block was
        # delivered and nothing followed it.
        self.assertEqual(got['s3'], 1)
        self.assertEqual(got['s3_unmeasured'], 0)
