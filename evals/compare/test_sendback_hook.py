"""The trial Stop hook, on synthetic sessions.

What is pinned here is the spec's three tightened definitions: the hook
blocks only where the parent can actually be judged; declining to
re-block on `stop_hook_active` is recorded as suppression and never as the
CLI's cap; and resumption needs a new parent reply or tool call, with
transcript lines carried as auxiliary information only.
"""
import io
import json
import os
import sys
import unittest

# The hook ships with the plugin, so the tests reach into
# `plugin/hooks/` rather than keeping a second copy here.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), 'plugin', 'hooks'))

import sendback_stop as sh
import test_session_extract as ts

class HookFixture(ts.SessionFixture):
    def setUp(self):
        # A real file on disk: the checks resolve citations against the
        # filesystem, and a path that does not resolve is undetermined
        # rather than a violation.
        super().setUp()
        self.src = os.path.join(self.dir, 'user.rb')
        with open(self.src, 'w', encoding='utf-8') as fh:
            fh.write('class User < ApplicationRecord\n')
        self.line = ('confirmed: %s — class User < ApplicationRecord'
                     % self.src)

    def event(self, **kw):
        ev = {'hook_event_name': 'Stop', 'session_id': 's1',
              'transcript_path': self.session, 'stop_hook_active': False}
        ev.update(kw)
        return ev

    def run_hook(self, event=None):
        out = io.StringIO()
        sh.main(io.StringIO(json.dumps(event or self.event())), out)
        return json.loads(out.getvalue())

    def session_with(self, final, worker=None):
        worker = self.line if worker is None else worker
        rows = [ts.prompt(), ts.assistant(ts.tool_use()), ts.tool_result(),
                ts.note(result=worker), ts.assistant(ts.text(final))]
        return self.write(rows, worker=worker)


class DecisionTests(HookFixture):
    def test_a_dropped_line_is_sent_back_verbatim(self):
        self.session_with('Here is a summary with no citations.')
        rec, out = sh.decide(self.event())
        self.assertEqual(rec['outcome'], sh.BLOCKED)
        self.assertEqual(out['decision'], 'block')
        self.assertIn(self.line, out['reason'])
        self.assertEqual(rec['lost_lines'], 1)

    def test_a_retained_line_is_not_sent_back(self):
        self.session_with('Findings.\n' + self.line)
        rec, out = sh.decide(self.event())
        self.assertEqual(rec['outcome'], sh.NO_BLOCK)
        self.assertEqual(out, {})

    def test_unobtainable_worker_output_is_never_sent_back(self):
        # Undetermined is not a parent violation; blocking here would
        # break an answer that may well be correct.
        self.write([ts.prompt(), ts.assistant(ts.tool_use()), ts.tool_result(),
                    ts.note(result='something else entirely'),
                    ts.assistant(ts.text('Summary.'))])
        rec, out = sh.decide(self.event())
        self.assertEqual(rec['outcome'], sh.NO_BLOCK)
        self.assertIn('unobtainable', rec['reason'])
        self.assertEqual(out, {})

    def test_a_worker_side_failure_is_never_sent_back(self):
        self.session_with('Summary.', worker='status: complete')
        rec, out = sh.decide(self.event())
        self.assertEqual(rec['outcome'], sh.NO_BLOCK)
        self.assertIn('worker side', rec['reason'])

    def test_an_unidentifiable_final_answer_is_never_sent_back(self):
        self.write([ts.prompt(), ts.assistant(ts.tool_use()), ts.tool_result()],
                   worker=self.line)
        rec, out = sh.decide(self.event())
        self.assertEqual(rec['outcome'], sh.NO_BLOCK)
        self.assertIn('final answer', rec['reason'])

    def test_stop_hook_active_records_suppression_not_a_cap(self):
        self.session_with('Summary.')
        rec, out = sh.decide(self.event(stop_hook_active=True))
        self.assertEqual(rec['outcome'], sh.SUPPRESSED)
        self.assertEqual(rec['reason'], 'stop_hook_active')
        self.assertNotIn('cap', json.dumps(rec))
        self.assertEqual(out, {})
        # The transcript is not even consulted: this is the hook's own
        # decision, not an observation of the CLI.
        self.assertNotIn('checks', rec)


class ResumptionTests(HookFixture):
    def test_a_new_parent_reply_is_a_resumption(self):
        rows = [ts.prompt(), ts.assistant(ts.text('First answer.'))]
        base = sh.parent_progress(rows)
        after = rows + [ts.assistant(ts.text('Corrected answer.\n' + self.line))]
        got = sh.resumption(base, after)
        self.assertEqual(got['status'], 'resumed')
        self.assertEqual(got['cause'], '')

    def test_a_new_parent_tool_call_is_a_resumption(self):
        rows = [ts.prompt(), ts.assistant(ts.text('First answer.'))]
        base = sh.parent_progress(rows)
        got = sh.resumption(base, rows + [ts.assistant(ts.tool_use())])
        self.assertEqual(got['status'], 'resumed')

    def test_appended_notifications_alone_are_not_a_resumption(self):
        # The line count grows, the parent said nothing. Lines must not
        # decide this.
        rows = [ts.prompt(), ts.assistant(ts.text('First answer.'))]
        base = sh.parent_progress(rows)
        got = sh.resumption(base, rows + [ts.note(), ts.note()])
        self.assertEqual(got['status'], 'not_resumed')
        self.assertEqual(got['line_growth'], 2)

    def test_a_parent_that_did_not_resume_leaves_the_cause_open(self):
        # Not "the block was discarded": the transcript cannot tell that
        # apart from any other reason the parent stayed silent.
        rows = [ts.prompt(), ts.assistant(ts.text('First answer.'))]
        got = sh.resumption(sh.parent_progress(rows), rows)
        self.assertEqual(got['status'], 'not_resumed')
        self.assertEqual(got['cause'], 'cause_unknown')

    def test_worker_replies_are_not_the_parent_acting(self):
        rows = [ts.prompt(), ts.assistant(ts.text('First answer.'))]
        base = sh.parent_progress(rows)
        side = dict(ts.assistant(ts.text('worker text')), isSidechain=True)
        self.assertEqual(sh.resumption(base, rows + [side])['status'],
                         'not_resumed')


class LoggingTests(HookFixture):
    def test_every_invocation_appends_one_record(self):
        self.session_with('Summary.')
        log_path = os.path.join(self.dir, 'trial.jsonl')
        os.environ[sh.LOG_ENV] = log_path
        self.addCleanup(os.environ.pop, sh.LOG_ENV, None)
        self.run_hook()
        self.run_hook(self.event(stop_hook_active=True))
        with open(log_path, encoding='utf-8') as fh:
            recs = [json.loads(l) for l in fh]
        self.assertEqual(len(recs), 2)
        self.assertEqual(recs[1]['outcome'], sh.SUPPRESSED)

    def test_an_unreadable_transcript_does_not_fail_the_turn(self):
        self.session_with('Summary.')
        self.assertEqual(self.run_hook(self.event(transcript_path='/nope')), {})

    def test_unparsable_input_does_not_fail_the_turn(self):
        out = io.StringIO()
        sh.main(io.StringIO('not json'), out)
        self.assertEqual(json.loads(out.getvalue()), {})


if __name__ == '__main__':
    unittest.main()


class StopInputTests(HookFixture):
    """The input path the trial exposed: the answer arrives in the event.

    `reviews/sendback-trial-2026-09-15.md` measured 0 blocks in 6 runs
    because the message ending the turn is not in the session file when the
    Stop hook runs. The CLI hands it over as `last_assistant_message`; these
    tests pin how it is used and when it is refused.
    """
    def test_the_event_supplies_the_answer_the_transcript_lacks(self):
        # Exactly the trial's shape: the parent's reply is missing from the
        # file, and the answer dropped the worker's line.
        self.write([ts.prompt(), ts.assistant(ts.tool_use()), ts.tool_result(),
                    ts.note(result=self.line)], worker=self.line)
        rec, out = sh.decide(self.event(
            last_assistant_message='Here is a summary with no citations.'))
        self.assertEqual(rec['outcome'], sh.BLOCKED)
        self.assertEqual(rec['final_source'], 'last_assistant_message')
        self.assertIn(self.line, out['reason'])

    def test_a_retained_line_in_the_event_is_not_sent_back(self):
        self.write([ts.prompt(), ts.assistant(ts.tool_use()), ts.tool_result(),
                    ts.note(result=self.line)], worker=self.line)
        rec, out = sh.decide(self.event(
            last_assistant_message='Findings.\n' + self.line))
        self.assertEqual(rec['outcome'], sh.NO_BLOCK)
        self.assertEqual(out, {})

    def test_text_repeated_from_an_earlier_turn_is_refused(self):
        # The CLI hands over the last assistant message, which need not be a
        # turn-ending one. Judging the parent against its own earlier
        # narration would invent a violation.
        narration = 'The worker is reading the files now.'
        self.write([ts.prompt(), ts.assistant(ts.text(narration)),
                    ts.assistant(ts.tool_use()), ts.tool_result(),
                    ts.note(result=self.line)], worker=self.line)
        rec, out = sh.decide(self.event(last_assistant_message=narration))
        self.assertEqual(rec['outcome'], sh.NO_BLOCK)
        self.assertIn('repeats earlier narration', rec['reason'])
        self.assertEqual(out, {})

    def test_the_transcript_is_still_used_when_the_event_says_nothing(self):
        self.session_with('Summary with no citations.')
        rec, _ = sh.decide(self.event())
        self.assertEqual(rec['final_source'], 'transcript')
        self.assertEqual(rec['outcome'], sh.BLOCKED)


class EarlyStopTests(HookFixture):
    def task(self, status='running', kind='subagent'):
        return {'id': 'task_1', 'type': kind, 'status': status,
                'description': 'reading files', 'agent_type':
                'token-shunt:bulk-reader'}

    def test_a_stop_while_the_worker_runs_is_recorded_apart(self):
        # Three of the trial's six runs stopped before the worker reported.
        # Nothing it has not delivered yet is the parent's omission.
        self.write([ts.prompt(), ts.assistant(ts.tool_use()), ts.tool_result()],
                   worker=self.line)
        rec, out = sh.decide(self.event(background_tasks=[self.task()],
                                        last_assistant_message='Waiting.'))
        self.assertEqual(rec['outcome'], sh.EARLY)
        self.assertEqual(out, {})
        self.assertNotIn('checks', rec)

    def test_a_finished_worker_task_does_not_hold_the_check_back(self):
        self.write([ts.prompt(), ts.assistant(ts.tool_use()), ts.tool_result(),
                    ts.note(result=self.line)], worker=self.line)
        rec, _ = sh.decide(self.event(
            background_tasks=[self.task(status='completed')],
            last_assistant_message='Summary.'))
        self.assertEqual(rec['outcome'], sh.BLOCKED)

    def test_other_background_work_is_not_a_worker(self):
        self.write([ts.prompt(), ts.assistant(ts.tool_use()), ts.tool_result(),
                    ts.note(result=self.line)], worker=self.line)
        rec, _ = sh.decide(self.event(
            background_tasks=[self.task(kind='shell')],
            last_assistant_message='Summary.'))
        self.assertEqual(rec['outcome'], sh.BLOCKED)


class EventKindTests(HookFixture):
    def test_a_subagent_stop_is_not_judged_as_the_parent(self):
        # The CLI converts a Stop hook to SubagentStop for a worker. That
        # event carries the WORKER's last message, which the parent
        # contract has nothing to say about.
        self.session_with('Summary with no citations.')
        rec, out = sh.decide(self.event(hook_event_name='SubagentStop',
                                        agent_id=ts.AGENT,
                                        last_assistant_message='Summary.'))
        self.assertEqual(rec['outcome'], sh.NO_BLOCK)
        self.assertEqual(rec['reason'], 'not a parent Stop')
        self.assertEqual(out, {})
