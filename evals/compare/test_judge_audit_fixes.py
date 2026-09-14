"""Regression evidence for reader summaries, recovery auditing, and metrics."""
import contextlib
import io
import copy
import json
import tempfile
import unittest
from pathlib import Path

import judge
import test_child_result_evidence as child_tests
import test_aggregate as aggregate_tests


class AuditTests(unittest.TestCase):
    def test_non_pipeline_body_recovery_and_metadata(self):
        for command in ("sed -n '1,9999p' /repo/f", "grep . /repo/f", "sort /repo/f",
                        "nl /repo/f", "od /repo/f", "xxd /repo/f", "perl -ne 'print' /repo/f",
                        "cat /repo/f | head -c5", "cat < /repo/f", "grep -e -lc /repo/f", "python3 -c 'print(open(\"/repo/f\").read())'"):
            with self.subTest(command=command):
                self.assertTrue(judge.bash_recovers_body({'input': {'command': command}}, '/repo/f'))
        for command in ("grep -l token /repo/f", "grep -c token /repo/f", "rg --files /repo/f",
                        "wc -lc /repo/f", "stat /repo/f", "grep . /repo/other",
                        "echo 'python /repo/f'", "grep -l x /repo/f; python --version"):
            with self.subTest(command=command):
                self.assertFalse(judge.bash_recovers_body({'input': {'command': command}}, '/repo/f'))

    def test_malformed_events_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.jsonl'
            for line in ('{broken', '[]', 'null'):
                path.write_text(line + '\n' + json.dumps({'type': 'result', 'result': 'ok'}))
                verdict, ok = judge.judge(str(path), {'id': 'bad'}, {'mode': 'auto'})
                self.assertFalse(ok)
                self.assertFalse(verdict['checks']['transcript'])
                self.assertIn('line 1', verdict['reasons'][0])
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(judge.leakcheck(str(path), str(path)), 2)

    def test_attempt_metrics_keep_unknown_fields_null(self):
        events = [{'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'id': 'a', 'name': 'Agent', 'input': {
                'subagent_type': 'token-shunt:bulk-reader', 'model': 'haiku',
                'prompt': 'question\nretry_reason: missing symbol'}}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result',
                'tool_use_id': 'a', 'content': 'status: partial\nstop_reason: read_budget'}]}},
            {'type': 'result', 'result': 'done'}]
        metrics = judge.Transcript(events).metrics()
        attempt = metrics['worker_attempts'][0]
        self.assertEqual(attempt['stop_reason'], 'read_budget')
        self.assertEqual(attempt['requested_model'], 'haiku')
        self.assertEqual(attempt['retry_reason'], 'missing symbol')
        self.assertIsNone(attempt['fallback_reason'])
        self.assertIsNone(metrics['stop_reason'])
        self.assertIsNone(metrics['fallback_reason'])


class StatusTests(unittest.TestCase):
    setUp = child_tests.ChildResultEvidenceTests.setUp
    evaluate = child_tests.ChildResultEvidenceTests.evaluate
    def test_reader_status_required_without_optional_body_checks(self):
        self.spec['expect']['delegate'] = {'agent_type': 'token-shunt:bulk-reader'}
        reply = copy.deepcopy(self.reply)
        reply['message']['content'][0]['content'] = 'facts found'
        verdict, ok = self.evaluate([self.call, reply, self.final])
        self.assertFalse(ok)
        self.assertFalse(verdict['checks']['child_status'])
        verdict, ok = self.evaluate([self.call, self.reply, self.final])
        self.assertTrue(ok, verdict['reasons'])
        self.assertTrue(verdict['checks']['child_status'])

    def test_bullet_status_fields_preserve_validation(self):
        for prefix in ('- ', '* ', '+ '):
            reply = copy.deepcopy(self.reply)
            reply['message']['content'][0]['content'] = (
                prefix + 'status: complete\n' + prefix + 'stop_reason: facts found')
            verdict, ok = self.evaluate([self.call, reply, self.final])
            self.assertTrue(ok, verdict['reasons'])
            self.assertTrue(verdict['checks']['child_status'])
            fields = judge.reader_fields(reply['message']['content'][0]['content'])
            self.assertEqual(fields['status'], 'complete')
            self.assertEqual(fields['stop_reason'], 'facts found')

    def test_missing_invalid_duplicate_and_empty_fields(self):
        for text in ('done', 'status: complete', 'status: unknown\nstop_reason: done',
                     'status: partial\nstop_reason:',
                     'status: partial\nstatus: complete\nstop_reason: done',
                     'status: complete\nstop_reason: done\nextra body'):
            reply = copy.deepcopy(self.reply)
            reply['message']['content'][0]['content'] = text
            verdict, ok = self.evaluate([self.call, reply, self.final])
            self.assertFalse(ok, text)
            self.assertFalse(verdict['checks']['child_status'])


class CostTests(unittest.TestCase):
    setUp = aggregate_tests.AggregateTests.setUp
    put = aggregate_tests.AggregateTests.put
    add = aggregate_tests.AggregateTests.add
    run_aggregate = aggregate_tests.AggregateTests.run_aggregate
    def test_cost_missing_is_explicit_and_does_not_gate_release(self):
        self.add()
        status, out = self.run_aggregate()
        self.assertEqual(status, 0)
        costs = out['suite_cost_usd']
        self.assertFalse(costs['evidence_complete'])
        self.assertIsNone(costs['delta_usd'])
        self.assertFalse(costs['release_gate'])

    def test_all_four_costs_include_failed_runs(self):
        ids = ('auto-bulk-facts', 'auto-one-line', 'auto-explicit-multifile', 'auto-large-writer')
        for cid in ids:
            self.add(cid, modes=('direct', 'haiku', 'sonnet', 'auto'))
            for mode, cost in (('direct', 0.1), ('haiku', 0.15), ('sonnet', 0.3), ('auto', 0.2)):
                path = self.root / 'v' / (cid + '.' + mode + '.json')
                value = json.loads(path.read_text())
                value['metrics']['total_cost_usd'] = cost
                if cid == 'auto-large-writer':
                    value['verdict'] = 'fail'
                path.write_text(json.dumps(value))
        _, out = self.run_aggregate()
        costs = out['suite_cost_usd']
        self.assertTrue(costs['evidence_complete'])
        self.assertFalse(costs['runs_passed'])
        self.assertAlmostEqual(costs['delta_usd'], 0.4)
        self.assertTrue(costs['regression'])
        self.assertTrue(costs['all_modes_evidence_complete'])
        self.assertAlmostEqual(costs['auto_minus_sonnet_usd'], -0.4)
        self.assertIn('not repeated-run medians', costs['basis'])


if __name__ == '__main__':
    unittest.main()
