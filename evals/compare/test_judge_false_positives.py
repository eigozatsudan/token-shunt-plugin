"""Regression coverage for transcript-confirmed evaluator false positives."""
import copy
import unittest

import judge
from routing_checks import _paths
import test_child_result_evidence as evidence


class MetadataTests(unittest.TestCase):
    def test_count_only_commands(self):
        for command in ("awk 'END{print NR}' /tmp/source.rb",
                        "awk 'END{print NR}' /tmp/source.rb /tmp/b.rb /tmp/c.rb",
                        "awk 'END{print NR}' /tmp/b.rb /tmp/source.rb /tmp/c.rb",
                        "awk 'END { print NR }' < /tmp/source.rb",
                        'wc -l /tmp/source.rb', 'wc -l < /tmp/source.rb'):
            with self.subTest(command=command):
                self.assertFalse(judge.bash_recovers_body(
                    {'input': {'command': command}}, '/tmp/source.rb'))

    def test_body_commands_still_fail(self):
        for command in ("awk '{print} END{print NR}' /tmp/source.rb",
                        "awk 'END{print $0}' /tmp/source.rb",
                        "awk 'END{print NR}' /tmp/source.rb; cat /tmp/source.rb",
                        "awk 'END{print NR}' /tmp/source.rb -f /tmp/program.awk",
                        "awk 'END{print NR}' /tmp/source.rb ARGV=changed",
                        'wc -l /tmp/source.rb; head /tmp/source.rb'):
            with self.subTest(command=command):
                self.assertTrue(judge.bash_recovers_body(
                    {'input': {'command': command}}, '/tmp/source.rb'))

    def test_callback_prose_is_not_a_fourth_path(self):
        self.assertEqual({'/tmp/a.rb', '/tmp/b.rb', '/tmp/c.rb'}, _paths(
            '/tmp/a.rb /tmp/b.rb /tmp/c.rb Explain `after_create`/callback'))

    def test_unknown_explicit_path_is_still_counted(self):
        self.assertIn('/unexpected.rb', _paths('/tmp/a.rb /unexpected.rb'))


class TrailerTests(unittest.TestCase):
    setUp = evidence.ChildResultEvidenceTests.setUp
    evaluate = evidence.ChildResultEvidenceTests.evaluate
    trailer = ('\nagentId: abc123 (use SendMessage with to: \'abc123\' to send a message to this agent)'
               '\n<usage>subagent_tokens: 123\ntool_uses: 6\nduration_ms: 456</usage>')

    def test_blank_lines_between_terminal_fields(self):
        for gap in ('\n\n', '\n \t\n\n'):
            reply = copy.deepcopy(self.reply)
            reply['message']['content'][0]['content'] = (
                'status: partial' + gap + 'stop_reason: budget_exhausted')
            verdict, ok = self.evaluate([self.call, reply, self.final])
            self.assertTrue(ok, verdict['reasons'])

    def test_intervening_prose_is_not_a_blank_line(self):
        reply = copy.deepcopy(self.reply)
        reply['message']['content'][0]['content'] = (
            'status: partial\nextra body\nstop_reason: budget_exhausted')
        verdict, ok = self.evaluate([self.call, reply, self.final])
        self.assertFalse(verdict['checks']['child_status'])

    def test_native_trailer_does_not_count_or_hide_terminal_fields(self):
        body = 'summary\nstatus: partial\nstop_reason: budget_exhausted'
        self.spec['expect']['delegate']['child_msg_max'] = len(body)
        reply = copy.deepcopy(self.reply)
        reply['message']['content'][0]['content'] = body + self.trailer
        verdict, ok = self.evaluate([self.call, reply, self.final])
        self.assertTrue(ok, verdict['reasons'])

    def test_arbitrary_trailing_content_is_not_removed(self):
        for suffix in ('\nagentId: extra prose', '\n<usage>hidden body</usage>',
                       self.trailer + '\nextra prose'):
            reply = copy.deepcopy(self.reply)
            reply['message']['content'][0]['content'] += suffix
            verdict, ok = self.evaluate([self.call, reply, self.final])
            self.assertFalse(ok)
            self.assertFalse(verdict['checks']['child_status'])

    def test_writer_cap_measures_body_and_still_rejects_excess(self):
        self.call['message']['content'][0]['input']['subagent_type'] = 'token-shunt:code-writer'
        self.spec['expect']['delegate'].update(
            agent_type='token-shunt:code-writer', child_msg_max=800)
        for size, expected in ((671, True), (801, False)):
            with self.subTest(size=size):
                reply = copy.deepcopy(self.reply)
                reply['message']['content'][0]['content'] = 'x' * size + self.trailer
                verdict, ok = self.evaluate([self.call, reply, self.final])
                self.assertEqual(expected, verdict['checks']['child_msg_cap'])

    def test_trailer_does_not_supply_missing_status(self):
        reply = copy.deepcopy(self.reply)
        reply['message']['content'][0]['content'] = 'summary' + self.trailer
        verdict, ok = self.evaluate([self.call, reply, self.final])
        self.assertFalse(verdict['checks']['child_status'])


if __name__ == '__main__':
    unittest.main()
