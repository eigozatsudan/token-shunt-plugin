"""A worker reads the paths its own invocation declared, and no others.

Section 4 of reviews/a-suite-failures-9346d19-2026-09-16.md recorded this
as a blind spot: `check-reader-contract` counts paths but not identity, so
a second invocation that re-read a path from the first passed the gate.
The reason given was that the declared set is not on the hook's stdin --
true, but the launch prompt is in the worker's own transcript, which the
stdin does name by session and agent id.

Nothing known means nothing denied: an unreadable transcript, a prompt
with no absolute path, or a declared path that does not exist leaves the
scope empty and the Read is allowed.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

HOOKS = Path(__file__).resolve().parent.parent / 'plugin' / 'hooks'
sys.path.insert(0, str(HOOKS))
import reader_scope as rs  # noqa: E402

AGENT = 'a1b2'


class ScopeFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.alpha = self.root / 'alpha.py'
        self.beta = self.root / 'beta.py'
        for path in (self.alpha, self.beta):
            path.write_text('x = 1\n')
        self.session = self.root / 'session.jsonl'
        self.session.write_text(json.dumps({'type': 'user'}) + '\n')
        self.subagents = self.root / 'session' / 'subagents'
        self.subagents.mkdir(parents=True)

    def declare(self, prompt, agent=AGENT):
        (self.subagents / ('agent-%s.jsonl' % agent)).write_text('\n'.join([
            json.dumps({'type': 'user',
                        'message': {'role': 'user', 'content': prompt}}),
            json.dumps({'type': 'assistant', 'message': {'content': []}}),
        ]))

    def event(self, **kw):
        ev = {'hook_event_name': 'PreToolUse', 'session_id': 's1',
              'agent_id': AGENT, 'agent_type': 'token-shunt:bulk-reader',
              'transcript_path': str(self.session)}
        ev.update(kw)
        return ev


class DeclaredPathTests(ScopeFixture):
    def test_the_prompt_paths_are_the_scope(self):
        self.declare('Read %s and %s and answer.' % (self.alpha, self.beta))
        self.assertEqual(rs.declared_paths(self.event()),
                         {os.path.realpath(self.alpha),
                          os.path.realpath(self.beta)})

    def test_a_path_in_the_prompt_that_does_not_exist_is_not_scope(self):
        # A named-but-absent file cannot be what the worker is reading, and
        # keeping it would not change any decision.
        self.declare('Read %s and /nowhere/gone.py' % self.alpha)
        self.assertEqual(rs.declared_paths(self.event()),
                         {os.path.realpath(self.alpha)})

    def test_a_prompt_with_no_absolute_path_declares_nothing(self):
        self.declare('Read alpha.py and answer.')
        self.assertEqual(rs.declared_paths(self.event()), set())

    def test_a_missing_transcript_declares_nothing(self):
        self.assertEqual(rs.declared_paths(self.event()), set())

    def test_a_broken_transcript_declares_nothing(self):
        (self.subagents / ('agent-%s.jsonl' % AGENT)).write_text('{not json')
        self.assertEqual(rs.declared_paths(self.event()), set())

    def test_the_worker_transcript_may_be_named_directly(self):
        self.declare('Read %s' % self.alpha)
        direct = self.event(transcript_path=str(
            self.subagents / ('agent-%s.jsonl' % AGENT)))
        self.assertEqual(rs.declared_paths(direct),
                         {os.path.realpath(self.alpha)})

    def test_only_the_launch_prompt_is_read_not_later_turns(self):
        # A later turn mentioning a path -- the worker's own Read, a tool
        # result, a quoted line -- must not widen the scope.
        (self.subagents / ('agent-%s.jsonl' % AGENT)).write_text('\n'.join([
            json.dumps({'type': 'user',
                        'message': {'role': 'user',
                                    'content': 'Read %s' % self.alpha}}),
            json.dumps({'type': 'user',
                        'message': {'role': 'user',
                                    'content': 'now %s' % self.beta}}),
        ]))
        self.assertEqual(rs.declared_paths(self.event()),
                         {os.path.realpath(self.alpha)})

    def test_content_blocks_are_read_like_plain_text(self):
        (self.subagents / ('agent-%s.jsonl' % AGENT)).write_text(json.dumps({
            'type': 'user', 'message': {'role': 'user', 'content': [
                {'type': 'text', 'text': 'Read %s' % self.alpha}]}}))
        self.assertEqual(rs.declared_paths(self.event()),
                         {os.path.realpath(self.alpha)})

    def test_a_path_written_with_trailing_punctuation_is_still_scope(self):
        self.declare('Read %s, then answer.' % self.alpha)
        self.assertIn(os.path.realpath(self.alpha),
                      rs.declared_paths(self.event()))

    def test_an_agent_id_that_is_not_ours_declares_nothing(self):
        self.declare('Read %s' % self.alpha)
        self.assertEqual(rs.declared_paths(self.event(agent_id='other')),
                         set())


class OutOfScopeTests(ScopeFixture):
    def test_a_declared_path_is_in_scope(self):
        self.declare('Read %s' % self.alpha)
        self.assertIsNone(rs.out_of_scope(self.event(), str(self.alpha)))

    def test_a_path_from_an_earlier_invocation_is_refused(self):
        # The observed case: invocation two declared beta and re-read alpha
        # (reviews/a-suite-failures-9346d19-2026-09-16.md section 4).
        self.declare('Read %s' % self.beta)
        reason = rs.out_of_scope(self.event(), str(self.alpha))
        self.assertIsNotNone(reason)
        self.assertIn(str(self.beta), reason)
        self.assertIn('partial', reason)

    def test_an_empty_scope_refuses_nothing(self):
        self.assertIsNone(rs.out_of_scope(self.event(), str(self.alpha)))

    def test_a_symlinked_spelling_of_a_declared_path_is_in_scope(self):
        link = self.root / 'link.py'
        link.symlink_to(self.alpha)
        self.declare('Read %s' % self.alpha)
        self.assertIsNone(rs.out_of_scope(self.event(), str(link)))


class TrialLogTests(unittest.TestCase):
    """The product's own reading of the declared set, recorded while it runs.

    It cannot be recovered afterwards: `declared_paths` requires the files to
    exist, and the eval deletes its fixture tree between modes, so a post-hoc
    scoring sees an empty set for every invocation
    (reviews/scope-prevention-stage1-2026-09-16.md section 7.2). Opt-in, like
    the send-back trial log, and never able to change a decision.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, 'scope.jsonl')

    def read(self):
        with open(self.path, encoding='utf-8') as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def test_a_record_is_one_json_line(self):
        rs.log({'event': 'scope', 'scope': ['/a.py']}, self.path)
        rs.log({'event': 'refused', 'path': '/b.py'}, self.path)
        self.assertEqual(['scope', 'refused'], [r['event'] for r in self.read()])

    def test_nothing_is_written_without_a_destination(self):
        rs.log({'event': 'scope'}, None)
        self.assertFalse(os.path.exists(self.path))

    def test_the_environment_names_the_destination(self):
        os.environ[rs.LOG_ENV] = self.path
        self.addCleanup(os.environ.pop, rs.LOG_ENV, None)
        rs.log({'event': 'scope'})
        self.assertEqual(1, len(self.read()))

    def test_an_unwritable_destination_is_swallowed(self):
        # Telemetry must never raise into a hook that is deciding a Read.
        rs.log({'event': 'scope'}, os.path.join(self.tmp.name, 'no', 'such.jsonl'))

    def test_a_record_that_cannot_be_serialized_is_swallowed(self):
        rs.log({'event': 'scope', 'bad': object()}, self.path)
        self.assertFalse(os.path.exists(self.path))


if __name__ == '__main__':
    unittest.main()
