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
        # A real Stop carries the text the turn is ending on, so the
        # fixture does too. `last_assistant_message=None` drops it, which
        # is what an older CLI or a turn ending on a tool result looks like.
        ev = {'hook_event_name': 'Stop', 'session_id': 's1',
              'transcript_path': self.session, 'stop_hook_active': False,
              'last_assistant_message': getattr(self, 'answer', None)}
        ev.update(kw)
        if ev.get('last_assistant_message') is None:
            ev.pop('last_assistant_message', None)
        return ev

    def run_hook(self, event=None):
        out = io.StringIO()
        sh.main(io.StringIO(json.dumps(event or self.event())), out)
        return json.loads(out.getvalue())

    def session_with(self, final, worker=None):
        worker = self.line if worker is None else worker
        self.answer = final
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

    def test_a_transcript_sourced_answer_is_recorded_but_not_blocked(self):
        # Without the field there is no text for THIS turn: the session
        # file still ends on the previous one. The violation is recorded
        # -- it is what offline analysis reads -- but nothing is sent back.
        self.session_with('Summary with no citations.')
        rec, out = sh.decide(self.event(last_assistant_message=None))
        self.assertEqual(rec['final_source'], 'transcript')
        self.assertEqual(rec['checks']['line_retention'], 'violation')
        self.assertEqual(rec['outcome'], sh.NO_BLOCK)
        self.assertIn('from the transcript', rec['reason'])
        self.assertEqual(out, {})


class VersionTests(HookFixture):
    """The CLI build is recorded, never inferred (decision §3 item 3)."""

    def write_versioned(self, version):
        rows = [ts.prompt(), ts.assistant(ts.tool_use()), ts.tool_result(),
                ts.note(result=self.line),
                ts.assistant(ts.text('Summary with no citations.'))]
        for row in rows:
            if row.get('type') in ('assistant', 'user') and version:
                row['version'] = version
        self.answer = 'Summary with no citations.'
        return self.write(rows, worker=self.line)

    def test_the_build_that_wrote_the_session_is_recorded(self):
        self.write_versioned('2.1.272')
        rec, _ = sh.decide(self.event())
        self.assertEqual(rec['cli_version'], '2.1.272')
        self.assertFalse(rec['below_version_floor'])
        self.assertEqual(rec['outcome'], sh.BLOCKED)

    def test_a_build_below_the_floor_is_flagged(self):
        self.write_versioned('2.1.268')
        rec, _ = sh.decide(self.event())
        self.assertTrue(rec['below_version_floor'])

    def test_an_unknown_build_is_not_called_old(self):
        # No version in the rows is not evidence of an old CLI, and the
        # field the hook actually depends on is present either way.
        self.write_versioned(None)
        rec, _ = sh.decide(self.event())
        self.assertIsNone(rec['cli_version'])
        self.assertFalse(rec['below_version_floor'])
        self.assertEqual(rec['outcome'], sh.BLOCKED)

    def test_unparsable_version_strings(self):
        for raw in (None, '', '2.1', 'dev', '2.1.x', 2):
            with self.subTest(raw=raw):
                self.assertIsNone(sh.parse_version(raw))
        self.assertEqual(sh.parse_version('2.1.272'), (2, 1, 272))
        self.assertGreaterEqual(sh.parse_version('2.1.269'), sh.VERSION_FLOOR)


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


class SizeTests(HookFixture):
    """The cap bounds the work a turn end pays for (decision §3 item 2)."""

    def test_an_oversized_session_leaves_the_parent_alone(self):
        self.session_with('Here is a summary with no citations.')
        os.environ[sh.SIZE_ENV] = '10'
        self.addCleanup(os.environ.pop, sh.SIZE_ENV, None)
        rec, out = sh.decide(self.event())
        # Same session that blocks under the default cap.
        self.assertEqual(rec['outcome'], sh.TOO_LARGE)
        self.assertGreater(rec['size'], rec['cap'])
        self.assertEqual(out, {})

    def test_the_default_cap_is_used_for_an_unusable_setting(self):
        for raw in ('', 'plenty', '0', '-1'):
            with self.subTest(raw=raw):
                os.environ[sh.SIZE_ENV] = raw
                self.addCleanup(os.environ.pop, sh.SIZE_ENV, None)
                self.assertEqual(sh.max_bytes(), sh.DEFAULT_MAX_BYTES)

    def test_an_oversized_worker_transcript_is_undetermined(self):
        # One copy of the worker's answer is unreadable, so the two cannot
        # be compared -- which is not evidence the parent dropped anything.
        self.session_with('Here is a summary with no citations.')
        sub = os.path.join(self.dir, 'sess', 'subagents')
        big = os.path.join(sub, 'agent-%s.jsonl' % ts.AGENT)
        with open(big, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(ts.assistant(ts.text('x' * 4096))) + '\n')
        os.environ[sh.SIZE_ENV] = str(os.path.getsize(self.session) + 1)
        self.addCleanup(os.environ.pop, sh.SIZE_ENV, None)
        rec, out = sh.decide(self.event())
        self.assertEqual(rec['outcome'], sh.NO_BLOCK)
        self.assertIn('unobtainable', rec['reason'])
        self.assertEqual(out, {})


class SingleParseTests(HookFixture):
    """The session file is read once per invocation, block path included."""

    def counted(self):
        reads = []
        real = sh.se.read_jsonl

        def spy(path, max_bytes=None):
            reads.append(path)
            return real(path, max_bytes)

        sh.se.read_jsonl = spy
        self.addCleanup(setattr, sh.se, 'read_jsonl', real)
        return reads

    def test_a_block_reads_the_session_once(self):
        self.session_with('Here is a summary with no citations.')
        reads = self.counted()
        rec, _ = sh.decide(self.event())
        self.assertEqual(rec['outcome'], sh.BLOCKED)
        self.assertEqual(reads.count(self.session), 1)

    def test_the_baseline_comes_from_that_one_parse(self):
        self.session_with('Here is a summary with no citations.')
        rec, _ = sh.decide(self.event())
        self.assertEqual(rec['baseline'],
                         sh.parent_progress(sh.se.read_jsonl(self.session)))

    def test_a_no_block_reads_the_session_once(self):
        self.session_with('Findings.\n' + self.line)
        reads = self.counted()
        rec, _ = sh.decide(self.event())
        self.assertEqual(rec['outcome'], sh.NO_BLOCK)
        self.assertEqual(reads.count(self.session), 1)
