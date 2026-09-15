"""Extraction from a real-session transcript, on synthetic sessions.

The shapes pinned here are the ones a real transcript actually produces and
the checks depend on: one agent id tying notification, worker transcript and
meta together; progress notifications sharing that id with the completed
one; an XML-escaped notification body; a harness PARTIAL notice; and a
parent that narrates between tool calls before writing its answer.
"""
import json
import os
import shutil
import tempfile
import unittest

import retention_checks as rc
import session_extract as se

AGENT = 'a1234567890abcdef'
TOOL_USE = 'toolu_01example'
ANSWER = ('confirmed: /srv/app/user.rb — class User < ApplicationRecord\n'
          'status: complete')


def note(agent_id=AGENT, status='completed', result=ANSWER, tool_use=TOOL_USE,
         output_file='/tmp/out.output'):
    body = ['<task-notification>', '<task-id>%s</task-id>' % agent_id,
            '<tool-use-id>%s</tool-use-id>' % tool_use,
            '<output-file>%s</output-file>' % output_file,
            '<status>%s</status>' % status]
    if result is not None:
        body.append('<result>%s</result>' % result)
    body.append('</task-notification>')
    return {'type': 'user', 'message': {'role': 'user',
                                        'content': '\n'.join(body)}}


def assistant(*blocks):
    return {'type': 'assistant', 'message': {'role': 'assistant',
                                             'content': list(blocks)}}


def text(s):
    return {'type': 'text', 'text': s}


def tool_use(name='Agent', tid=TOOL_USE, inp=None):
    return {'type': 'tool_use', 'id': tid, 'name': name, 'input': inp or {}}


def tool_result(tid=TOOL_USE, content='Async agent launched successfully.'):
    return {'type': 'user',
            'message': {'role': 'user',
                        'content': [{'type': 'tool_result',
                                     'tool_use_id': tid, 'content': content}]}}


def prompt(s='What happens after a User is created?'):
    return {'type': 'user', 'message': {'role': 'user', 'content': s}}


class SessionFixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.session = os.path.join(self.dir, 'sess.jsonl')

    def write(self, rows, worker=ANSWER, agent_id=AGENT,
              agent_type='token-shunt:bulk-reader', meta=True):
        with open(self.session, 'w', encoding='utf-8') as fh:
            for row in rows:
                fh.write(json.dumps(row) + '\n')
        sub = os.path.join(self.dir, 'sess', 'subagents')
        os.makedirs(sub, exist_ok=True)
        if worker is not None:
            with open(os.path.join(sub, 'agent-%s.jsonl' % agent_id), 'w',
                      encoding='utf-8') as fh:
                fh.write(json.dumps(assistant(text(worker))) + '\n')
        if meta:
            with open(os.path.join(sub, 'agent-%s.meta.json' % agent_id), 'w',
                      encoding='utf-8') as fh:
                json.dump({'agentType': agent_type, 'toolUseId': TOOL_USE}, fh)
        return self.session


class CorrelationTests(SessionFixture):
    def test_one_launch_ties_notification_meta_and_transcript_together(self):
        self.write([prompt(), assistant(tool_use()), tool_result(), note(),
                    assistant(text('Done.'))])
        (launch,) = se.launches(self.session)
        self.assertEqual(launch['agent_id'], AGENT)
        self.assertEqual(launch['tool_use_id'], TOOL_USE)
        self.assertEqual(launch['agent_type'], 'token-shunt:bulk-reader')
        self.assertTrue(launch['transcript'].endswith('agent-%s.jsonl' % AGENT))
        self.assertEqual(launch['output_file'], '/tmp/out.output')
        self.assertEqual(launch['completeness'], 'complete')

    def test_progress_notifications_do_not_displace_the_completed_one(self):
        # Both carry the same task-id; only the completed one is the answer.
        self.write([prompt(), assistant(tool_use()), tool_result(),
                    note(status='in_progress', result='partway'),
                    note(), assistant(text('Done.'))])
        (launch,) = se.launches(self.session)
        self.assertEqual(launch['notifications'], 2)
        self.assertEqual(launch['completeness'], 'complete')
        self.assertIn('class User', launch['text'])

    def test_launches_can_be_filtered_by_agent_type(self):
        # launches() reports every worker; check_inputs() is what narrows to
        # the reader, so another agent's launch must not supply its texts.
        self.write([prompt(), assistant(tool_use()), tool_result(), note(),
                    assistant(text('Done.'))], agent_type='Explore')
        self.assertEqual(len(se.launches(self.session)), 1)
        self.assertEqual(se.launches(self.session, agent_type='token-shunt:bulk-reader'), [])
        self.assertIsNone(se.check_inputs(self.session)['child_texts'])


class CompletenessTests(SessionFixture):
    def test_xml_escaped_notification_still_matches_the_transcript(self):
        escaped = ANSWER.replace('<', '&lt;')
        self.write([prompt(), assistant(tool_use()), tool_result(),
                    note(result=escaped), assistant(text('Done.'))])
        (launch,) = se.launches(self.session)
        self.assertEqual(launch['completeness'], 'complete')
        self.assertIn('class User < ApplicationRecord', launch['text'])

    def test_a_harness_partial_notice_makes_the_output_unjudgeable(self):
        marked = ('NOTE: this agent stopped at its 6-turn limit before '
                  'finishing. The text below is PARTIAL output.\n\n' + ANSWER)
        self.write([prompt(), assistant(tool_use()), tool_result(),
                    note(result=marked), assistant(text('Done.'))])
        (launch,) = se.launches(self.session)
        self.assertEqual(launch['completeness'], 'partial')
        self.assertIsNone(launch['text'])

    def test_unexplained_disagreement_is_a_mismatch_not_a_guess(self):
        self.write([prompt(), assistant(tool_use()), tool_result(),
                    note(result='something else entirely'),
                    assistant(text('Done.'))])
        (launch,) = se.launches(self.session)
        self.assertEqual(launch['completeness'], 'mismatch')
        self.assertIsNone(launch['text'])

    def test_a_missing_worker_transcript_falls_back_to_the_notification(self):
        self.write([prompt(), assistant(tool_use()), tool_result(), note(),
                    assistant(text('Done.'))], worker=None)
        (launch,) = se.launches(self.session)
        self.assertEqual(launch['completeness'], 'notification_only')
        self.assertIn('class User', launch['text'])

    def test_no_result_anywhere_is_unavailable(self):
        self.write([prompt(), assistant(tool_use()), tool_result(),
                    note(result=None), assistant(text('Done.'))], worker=None)
        (launch,) = se.launches(self.session)
        self.assertEqual(launch['completeness'], 'unavailable')
        self.assertIsNone(launch['text'])


class FinalAnswerTests(SessionFixture):
    def test_narration_before_the_worker_reports_is_not_the_answer(self):
        # The exact shape a real session produced: the parent says it is
        # waiting, the worker reports, then the answer comes.
        self.write([prompt(), assistant(tool_use()), tool_result(),
                    assistant(text('The worker is reading the files now.')),
                    note(), assistant(text('Final answer here.'))])
        self.assertEqual(se.final_answer(self.session)['text'],
                         'Final answer here.')

    def test_text_emitted_before_a_tool_call_is_not_the_answer(self):
        self.write([prompt(), assistant(text('Let me check the size first.')),
                    assistant(tool_use(name='Bash', tid='toolu_b')),
                    tool_result(tid='toolu_b', content='22546'),
                    assistant(tool_use()), tool_result(), note(),
                    assistant(text('Answer.'))])
        self.assertEqual(se.final_answer(self.session)['text'], 'Answer.')

    def test_a_turn_ending_on_a_tool_result_has_no_final_text(self):
        # The same turn shape whose Stop-hook block the CLI discards.
        self.write([prompt(), assistant(tool_use()), tool_result()])
        got = se.final_answer(self.session)
        self.assertIsNone(got['text'])
        self.assertEqual(got['status'], 'no_final_text')

    def test_consecutive_assistant_text_blocks_are_joined(self):
        self.write([prompt(), assistant(tool_use()), tool_result(), note(),
                    assistant(text('First.'), text('Second.'))])
        self.assertEqual(se.final_answer(self.session)['text'],
                         'First.\nSecond.')


class EndToEndTests(SessionFixture):
    def rows(self, final):
        return [prompt(), assistant(tool_use()), tool_result(), note(),
                assistant(text(final))]

    def test_a_retained_line_passes_all_three_checks(self):
        line = 'confirmed: /srv/app/user.rb — class User < ApplicationRecord'
        self.write(self.rows('Here is what I found.\n' + line))
        got = se.check_inputs(self.session)
        r = rc.run_all(got['child_texts'], got['final'],
                       exists=lambda p: p == '/srv/app/user.rb')
        self.assertEqual([v['status'] for v in r.values()],
                         [rc.OK, rc.OK, rc.OK])

    def test_an_unauthorised_demotion_is_reported_as_retention_loss(self):
        # The worker's path was absolute and real; rewriting the line as
        # unconfirmed discards evidence rather than applying the contract's
        # demotion rule, which is only for lines without a usable path.
        demoted = ('unconfirmed: /srv/app/user.rb — class User '
                   '< ApplicationRecord')
        self.write(self.rows('Summary.\n' + demoted))
        got = se.check_inputs(self.session)
        r = rc.run_all(got['child_texts'], got['final'],
                       exists=lambda p: p == '/srv/app/user.rb')
        self.assertEqual(r['line_retention']['status'], rc.VIOLATION)
        self.assertEqual(len(r['line_retention']['demoted']), 1)
        self.assertEqual(r['line_retention']['dropped'], [])
        # Coverage cannot see it: an unconfirmed line is not a citation.
        self.assertEqual(r['file_coverage']['status'], rc.VIOLATION)

    def test_a_permitted_demotion_is_not_reported(self):
        # Worker gave no absolute path, so demotion is the prescribed move.
        pathless = 'confirmed: user.rb — no path given'
        self.write([prompt(), assistant(tool_use()), tool_result(),
                    note(result=pathless),
                    assistant(text('unconfirmed: user.rb — no path given'))],
                   worker=pathless)
        got = se.check_inputs(self.session)
        r = rc.run_all(got['child_texts'], got['final'], exists=lambda p: False)
        self.assertEqual(r['child_items']['status'], rc.VIOLATION)
        self.assertEqual(r['line_retention']['status'], rc.UNDETERMINED)

    def test_unobtainable_worker_output_blocks_judgement_of_the_parent(self):
        self.write([prompt(), assistant(tool_use()), tool_result(),
                    note(result='something else entirely'),
                    assistant(text('Answer with no citations.'))])
        got = se.check_inputs(self.session)
        self.assertIsNone(got['child_texts'])
        r = rc.run_all(got['child_texts'], got['final'])
        self.assertEqual(r['file_coverage']['status'], rc.UNDETERMINED)
        self.assertEqual(r['line_retention']['status'], rc.UNDETERMINED)


if __name__ == '__main__':
    unittest.main()
