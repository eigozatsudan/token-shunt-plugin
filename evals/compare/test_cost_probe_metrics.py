"""The cost probe must count skill loads and the bytes each deny injects."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cost_probe


class MetricsTests(unittest.TestCase):
    def write(self, events):
        fh = tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False,
                                         encoding='utf-8')
        for event in events:
            fh.write(json.dumps(event) + '\n')
        fh.close()
        return fh.name

    def assistant(self, *tools, child=False):
        event = {'type': 'assistant',
                 'message': {'content': [{'type': 'tool_use', 'name': n}
                                         for n in tools]}}
        if child:
            event['parent_tool_use_id'] = 'toolu_1'
        return event

    def result(self):
        return {'type': 'result', 'is_error': False, 'total_cost_usd': 0.1,
                'usage': {}, 'modelUsage': {}, 'num_turns': 2, 'result': 'ok'}

    def read_skill_md(self):
        return {'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'name': 'Read',
             'input': {'file_path': '/p/plugin/skills/bulk-reader/SKILL.md'}}]}}

    def test_skill_loads_count_both_tool_and_skill_md_read(self):
        path = self.write([self.assistant('Skill'),
                           self.read_skill_md(),
                           self.assistant('Agent'),
                           self.result()])
        row = cost_probe.metrics(path)
        self.assertEqual(row['skill_loads'], 2)
        self.assertEqual(row['parent_reads'], 1)

    def test_child_skill_use_is_not_counted_as_a_parent_load(self):
        path = self.write([self.assistant('Skill', child=True), self.result()])
        self.assertEqual(cost_probe.metrics(path)['skill_loads'], 0)

    def test_deny_count_and_bytes_come_from_the_hook_log(self):
        path = self.write([self.assistant('Read'), self.result()])
        log = tempfile.NamedTemporaryFile('w', suffix='.hooklog', delete=False,
                                          encoding='utf-8')
        log.write(json.dumps({'hook': 'check-file-size', 'decision': 'pass',
                              'reason': ''}) + '\n')
        log.write(json.dumps({'hook': 'check-file-size', 'decision': 'deny',
                              'reason': 'ありがとう' * 10}) + '\n')
        log.close()
        row = cost_probe.metrics(path, log.name)
        self.assertEqual(row['deny_count'], 1)
        self.assertEqual(row['deny_bytes'], len(('ありがとう' * 10).encode()))

    def test_missing_hook_log_is_recorded_as_missing_not_zero(self):
        # A lost log is unmeasured, not "no denies": the difference decides
        # whether the run counts toward the injection total at all.
        path = self.write([self.assistant('Read'), self.result()])
        row = cost_probe.metrics(path, '/nonexistent/hook.log')
        self.assertIsNone(row['deny_count'])
        self.assertIsNone(row['deny_bytes'])
        self.assertEqual(row['hooklog'], 'missing')

    def test_direct_condition_has_no_hook_log_by_design(self):
        path = self.write([self.assistant('Read'), self.result()])
        row = cost_probe.metrics(path)
        self.assertIsNone(row['deny_count'])
        self.assertEqual(row['hooklog'], 'not_applicable')

    def test_present_hook_log_is_marked_ok(self):
        path = self.write([self.assistant('Read'), self.result()])
        log = tempfile.NamedTemporaryFile('w', suffix='.hooklog', delete=False,
                                          encoding='utf-8')
        log.close()
        row = cost_probe.metrics(path, log.name)
        self.assertEqual((row['deny_count'], row['deny_bytes']), (0, 0))
        self.assertEqual(row['hooklog'], 'ok')


if __name__ == '__main__':
    unittest.main()
