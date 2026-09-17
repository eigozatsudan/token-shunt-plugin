"""The three retention checks, including cases the saved corpus lacks.

The archived runs are dominated by one shape: three golds in three
different files. Everything that shape cannot exercise -- two facts from
one file, a partial drop, a demoted line, a vanished file -- is synthetic
here, because that is exactly where file coverage and line retention stop
agreeing.
"""
import os
import shutil
import sys
import tempfile
import unittest

# The hook ships with the plugin, so the tests reach into
# `plugin/hooks/` rather than keeping a second copy here.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), 'plugin', 'hooks'))

import sendback_retention as rc

A = '/srv/app/models/user.rb'
B = '/srv/app/jobs/welcome_email_job.rb'


def here(path):
    """Stand-in filesystem: A and B exist, nothing else does."""
    return path in (A, B)


def item(path, fact):
    return 'confirmed: %s — %s' % (path, fact)


class VacuousItemTests(unittest.TestCase):
    """`confirmed: none` claims nothing; a pathless fact claims something."""

    def test_placeholder_and_empty_heads_are_vacuous(self):
        for line in ('confirmed:', 'confirmed: none', 'confirmed: (none)',
                     'confirmed: N/A',
                     'confirmed: none — the line exceeds the read limit'):
            with self.subTest(line=line):
                self.assertTrue(rc.vacuous_item(line))

    def test_a_stated_fact_is_never_vacuous(self):
        for line in ('confirmed: %s — one' % A,
                     'confirmed: user.rb — class User',
                     'confirmed: /tmp/.../user.rb — class User'):
            with self.subTest(line=line):
                self.assertFalse(rc.vacuous_item(line))


class ConfirmedLineTests(unittest.TestCase):
    def test_list_markers_and_indentation_are_stripped(self):
        text = '  - confirmed: %s — one\n* confirmed: %s — two\n' % (A, B)
        self.assertEqual(rc.confirmed_lines(text),
                         [item(A, 'one'), item(B, 'two')])

    def test_unconfirmed_lines_are_not_retention_targets(self):
        # Demotion is the prescribed recovery when a path is missing, so
        # counting it as a target would flag the correct behaviour.
        text = 'unconfirmed: %s — one\nconfirmed: %s — two\n' % (A, B)
        self.assertEqual(rc.confirmed_lines(text), [item(B, 'two')])

    def test_citation_is_the_path_before_the_dash(self):
        self.assertEqual(rc.citation(item(A, 'mentions /etc/passwd')), A)

    def test_a_line_number_suffix_still_cites_the_file(self):
        """`path:12` is how a reader writes a citation, not a filename.

        Read left as-is it resolves to nothing, the item classifies as
        UNDETERMINED, and a parent that dropped the line is passed.
        """
        for suffix in (':12', ':12:5', ':12-40', '#L12'):
            with self.subTest(suffix=suffix):
                self.assertEqual(rc.citation(item(A + suffix, 'TOKEN is 42')),
                                 A)
                self.assertEqual(rc.classify_path(
                    rc.citation(item(A + suffix, 'x')), here), rc.OK)

    def test_a_dropped_line_with_a_line_number_is_a_violation(self):
        child = item(A + ':12', 'TOKEN is 42')
        got = rc.check_line_retention([child], 'nothing of the sort', here)
        self.assertEqual(got['status'], rc.VIOLATION)

    def test_citation_of_a_pathless_line_is_none(self):
        self.assertIsNone(rc.citation('confirmed: user.rb — relative'))


class PathClassificationTests(unittest.TestCase):
    def test_an_existing_absolute_path_is_ok(self):
        self.assertEqual(rc.classify_path(A, here), rc.OK)

    def test_an_elided_path_is_a_violation_without_touching_disk(self):
        # /tmp/.../user.rb names no file; that is visible in the text.
        self.assertEqual(rc.classify_path('/srv/.../user.rb', here),
                         rc.VIOLATION)
        self.assertEqual(rc.classify_path('/srv/…/user.rb', here),
                         rc.VIOLATION)

    def test_a_relative_path_is_a_violation(self):
        self.assertEqual(rc.classify_path('app/models/user.rb', here),
                         rc.VIOLATION)

    def test_a_vanished_file_is_undetermined_not_a_violation(self):
        # The file may have been deleted since the worker read it. That is
        # not evidence the parent dropped anything.
        self.assertEqual(rc.classify_path('/srv/app/gone.rb', here),
                         rc.UNDETERMINED)


class ChildItemsTests(unittest.TestCase):
    def test_missing_worker_output_is_undetermined(self):
        r = rc.check_child_items(None, here)
        self.assertEqual(r['status'], rc.UNDETERMINED)
        self.assertIn('unavailable', r['reason'])

    def test_a_worker_that_returned_nothing_is_a_violation(self):
        r = rc.check_child_items(['status: complete'], here)
        self.assertEqual(r['status'], rc.VIOLATION)
        self.assertIn('no confirmed item', r['reason'])

    def test_pathless_worker_items_are_a_violation_on_the_worker(self):
        r = rc.check_child_items(['confirmed: user.rb — no path'], here)
        self.assertEqual(r['status'], rc.VIOLATION)
        self.assertEqual(r['usable'], [])

    def test_all_citations_vanished_is_undetermined(self):
        r = rc.check_child_items([item('/srv/app/gone.rb', 'x')], here)
        self.assertEqual(r['status'], rc.UNDETERMINED)

    def test_one_usable_item_is_enough(self):
        r = rc.check_child_items(
            [item(A, 'x') + '\n' + 'confirmed: rel.rb — y'], here)
        self.assertEqual(r['status'], rc.OK)
        self.assertEqual(r['usable'], [item(A, 'x')])
        self.assertEqual(r['unusable'], ['confirmed: rel.rb — y'])


class FileCoverageTests(unittest.TestCase):
    def test_citing_every_worker_file_is_ok(self):
        child = [item(A, 'x'), item(B, 'y')]
        final = item(A, 'x') + '\n' + item(B, 'y')
        self.assertEqual(rc.check_file_coverage(child, final, here)['status'],
                         rc.OK)

    def test_dropping_a_whole_file_is_a_violation_that_names_it(self):
        child = [item(A, 'x'), item(B, 'y')]
        r = rc.check_file_coverage(child, item(A, 'x'), here)
        self.assertEqual(r['status'], rc.VIOLATION)
        self.assertEqual(r['missing'], [B])

    def test_coverage_cannot_see_a_second_fact_from_the_same_file(self):
        # The case the archived corpus never produced, and the reason
        # coverage does not stand in for the contract: both facts cite A,
        # so dropping one leaves coverage satisfied.
        child = [item(A, 'first fact'), item(A, 'second fact')]
        final = item(A, 'first fact')
        self.assertEqual(rc.check_file_coverage(child, final, here)['status'],
                         rc.OK)
        self.assertEqual(
            rc.check_line_retention(child, final, here)['dropped'],
            [item(A, 'second fact')])

    def test_an_elided_path_in_the_final_answer_does_not_cover_the_file(self):
        child = [item(A, 'x')]
        r = rc.check_file_coverage(child, item('/srv/.../user.rb', 'x'), here)
        self.assertEqual(r['status'], rc.VIOLATION)
        self.assertEqual(r['missing'], [A])

    def test_unavailable_worker_output_is_undetermined_not_a_drop(self):
        self.assertEqual(rc.check_file_coverage(None, 'anything', here)['status'],
                         rc.UNDETERMINED)


class LineRetentionTests(unittest.TestCase):
    def test_verbatim_copies_of_every_line_pass(self):
        child = [item(A, 'x'), item(B, 'y')]
        final = 'Summary.\n%s\n%s\n' % (item(A, 'x'), item(B, 'y'))
        r = rc.check_line_retention(child, final, here)
        self.assertEqual(r['status'], rc.OK)
        self.assertEqual(len(r['kept']), 2)

    def test_identical_lines_collapse(self):
        # The contract allows collapsing exactly identical lines only.
        child = [item(A, 'x'), item(A, 'x')]
        r = rc.check_line_retention(child, item(A, 'x'), here)
        self.assertEqual(r['status'], rc.OK)
        self.assertEqual(len(r['kept']), 1)

    def test_a_paraphrase_is_reported_as_altered_not_dropped(self):
        # The path survives, the wording does not. Gold-style checks accept
        # this; the contract does not, and the two must stay distinguishable.
        child = [item(A, 'registers an after_create callback')]
        r = rc.check_line_retention(child, item(A, 'after_create hook'), here)
        self.assertEqual(r['status'], rc.VIOLATION)
        self.assertEqual(r['altered'], child)
        self.assertEqual(r['dropped'], [])

    def test_a_partial_drop_from_one_file_is_reported(self):
        child = [item(A, 'first'), item(A, 'second')]
        r = rc.check_line_retention(child, item(A, 'first'), here)
        self.assertEqual(r['status'], rc.VIOLATION)
        self.assertEqual(r['dropped'], [item(A, 'second')])

    def test_worker_lines_with_unusable_paths_are_not_held_against_parent(self):
        child = ['confirmed: user.rb — pathless']
        r = rc.check_line_retention(child, 'unconfirmed: user.rb — pathless',
                                    here)
        self.assertEqual(r['status'], rc.UNDETERMINED)

    def test_vanished_files_make_retention_undetermined(self):
        child = [item('/srv/app/gone.rb', 'x')]
        r = rc.check_line_retention(child, '', here)
        self.assertEqual(r['status'], rc.UNDETERMINED)


class LocatorRetentionTests(unittest.TestCase):
    """What stripping the locator does to the verbatim comparison.

    The citation is now the file either way, so the line is judged
    instead of passing as UNDETERMINED -- and the judgement is the
    contract's: the line is kept verbatim or it is not. Dropping `:12`
    while restating the fact is an alteration, and a block.
    """

    def test_restating_without_the_line_number_is_an_alteration(self):
        child = [item(A + ':12', 'TOKEN is 42')]
        got = rc.check_line_retention(child, item(A, 'TOKEN is 42'), here)
        self.assertEqual(got['status'], rc.VIOLATION)
        self.assertEqual(got['altered'], [item(A + ':12', 'TOKEN is 42')])

    def test_keeping_the_line_as_written_passes(self):
        line = item(A + ':12', 'TOKEN is 42')
        self.assertEqual(rc.check_line_retention([line], line, here)['status'],
                         rc.OK)


class VanishedFileTests(unittest.TestCase):
    """Lines citing a file that is gone cannot be judged -- or reported OK.

    They are excluded from the targets, which is right: nobody can say
    whether the parent dropped them. Calling the result "retention ok"
    was not right, because a line nobody checked was dropped from the
    answer, and the record said the check had passed.
    """

    def test_an_unjudgeable_line_leaves_the_verdict_undetermined(self):
        child = [item(A, 'one'), item('/srv/gone.rb', 'two')]
        got = rc.check_line_retention(child, item(A, 'one'), here)
        self.assertEqual(got['status'], rc.UNDETERMINED)
        self.assertIn('no longer exists', got['reason'])

    def test_a_judgeable_drop_is_still_a_violation(self):
        child = [item(A, 'one'), item('/srv/gone.rb', 'two')]
        got = rc.check_line_retention(child, 'nothing kept', here)
        self.assertEqual(got['status'], rc.VIOLATION)

    def test_nothing_missing_is_still_plain_ok(self):
        got = rc.check_line_retention([item(A, 'one')], item(A, 'one'), here)
        self.assertEqual(got['status'], rc.OK)


class RunAllTests(unittest.TestCase):
    def test_the_three_checks_are_reported_separately(self):
        child = [item(A, 'first'), item(A, 'second'), item(B, 'third')]
        final = item(A, 'first')
        r = rc.run_all(child, final, here)
        self.assertEqual(r['child_items']['status'], rc.OK)
        self.assertEqual(r['file_coverage']['status'], rc.VIOLATION)
        self.assertEqual(r['file_coverage']['missing'], [B])
        self.assertEqual(r['line_retention']['status'], rc.VIOLATION)
        self.assertEqual(sorted(r['line_retention']['dropped']),
                         sorted([item(A, 'second'), item(B, 'third')]))


class RelapseTests(unittest.TestCase):
    """A parent that restates the lines and then finishes without them.

    Observed once in 30 runs (reviews/sendback-rescue-2026-09-16.md section 3):
    the send-back was answered in full, and the turn then ended on a shorter
    message that dropped the lines again. The second Stop carries
    stop_hook_active, so nothing looked at it.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.src = os.path.join(self.dir, 'user.rb')
        with open(self.src, 'w', encoding='utf-8') as fh:
            fh.write('class User\n')
        self.line = 'confirmed: %s — class User' % self.src
        self.child = [self.line]

    def test_restated_then_finished_without_them(self):
        got = rc.check_relapse(self.child, 'Here:\n' + self.line,
                               'In short, the user model sends the email.')
        self.assertEqual(rc.VIOLATION, got['status'])
        self.assertEqual([self.line], got['lost'])

    def test_a_final_answer_that_still_carries_them_is_ok(self):
        got = rc.check_relapse(self.child, 'Here:\n' + self.line,
                               'Summary.\n' + self.line)
        self.assertEqual(rc.OK, got['status'])

    def test_a_repair_that_never_landed_is_undetermined(self):
        # The earlier text does not hold the lines either, so this is a
        # failed repair, not a relapse. Blocking it again is the loop
        # stop_hook_active exists to stop.
        got = rc.check_relapse(self.child, 'Still just a summary.',
                               'Another summary.')
        self.assertEqual(rc.UNDETERMINED, got['status'])

    def test_no_earlier_text_is_undetermined(self):
        self.assertEqual(rc.UNDETERMINED,
                         rc.check_relapse(self.child, None, 'Summary.')['status'])
        self.assertEqual(rc.UNDETERMINED,
                         rc.check_relapse(self.child, 'x', None)['status'])

    def test_an_unjudgeable_worker_is_undetermined(self):
        self.assertEqual(rc.UNDETERMINED,
                         rc.check_relapse(['status: complete'], 'x', 'y')['status'])

    def test_a_line_whose_file_is_gone_is_undetermined(self):
        os.remove(self.src)
        got = rc.check_relapse(self.child, 'Here:\n' + self.line, 'Summary.')
        self.assertEqual(rc.UNDETERMINED, got['status'])


if __name__ == '__main__':
    unittest.main()


class CodeFenceTests(unittest.TestCase):
    """The worker contract forbids code fences, including around one value.

    Measured live on Redmine: three of twelve `redmine-last-query` worker
    reports wrapped the requested `def` line in a fence
    (reviews/redmine-dose-2026-09-17.md section 5). The rule is not about
    how much source is quoted, so one line breaks it exactly as a body does.
    """

    def test_a_contracted_report_has_no_fence(self):
        got = rc.check_code_fence(item(A, 'last method: deliver_notification'))
        self.assertEqual(got['status'], rc.OK)
        self.assertEqual(got['fences'], [])

    def test_a_fence_around_a_single_line_is_a_violation(self):
        # The exact shape observed live.
        got = rc.check_code_fence(
            'The last def is at line 1691:\n\n'
            '```\ndef joins_for_order_statement(order_options)\n```\n\n'
            + item(A, 'last method: joins_for_order_statement'))
        self.assertEqual(got['status'], rc.VIOLATION)
        # One entry per fenced block, not per marker line.
        self.assertEqual(len(got['fences']), 1)
        self.assertIn('code fence', got['reason'])

    def test_the_entry_locates_the_fence_and_quotes_what_is_inside(self):
        # Measured 2026-09-17: a bare fence made the send-back say
        # '```; ```', which tells the worker nothing about what to delete
        # (reviews/fence-sendback-2026-09-17.md section 4).
        got = rc.check_code_fence(
            'line one\nline two\n```\ndef joins_for_order_statement(o)\n```')
        entry = got['fences'][0]
        self.assertIn('line 3', entry)
        self.assertIn('def joins_for_order_statement(o)', entry)

    def test_an_info_string_is_kept(self):
        got = rc.check_code_fence('```ruby\ndef x\n```')
        self.assertIn('```ruby', got['fences'][0])

    def test_a_long_quoted_line_is_truncated(self):
        got = rc.check_code_fence('```\n' + 'z' * 500 + '\n```')
        entry = got['fences'][0]
        self.assertLess(len(entry), 200)
        self.assertIn('…', entry)

    def test_an_empty_fence_says_so_rather_than_quoting_nothing(self):
        got = rc.check_code_fence('```\n```')
        self.assertIn('empty', got['fences'][0])

    def test_the_first_non_empty_line_inside_is_the_one_quoted(self):
        got = rc.check_code_fence('```\n\n\ndef x\n```')
        self.assertIn('def x', got['fences'][0])

    def test_an_unclosed_fence_is_still_reported(self):
        got = rc.check_code_fence('```\ndef x')
        self.assertEqual(got['status'], rc.VIOLATION)
        self.assertEqual(len(got['fences']), 1)
        self.assertIn('def x', got['fences'][0])

    def test_two_blocks_are_two_entries(self):
        got = rc.check_code_fence('```\ndef a\n```\nprose\n```\ndef b\n```')
        self.assertEqual(len(got['fences']), 2)
        self.assertIn('def a', got['fences'][0])
        self.assertIn('def b', got['fences'][1])

    def test_a_tilde_fence_counts(self):
        got = rc.check_code_fence('~~~ruby\ndef x\n~~~')
        self.assertEqual(got['status'], rc.VIOLATION)

    def test_an_indented_fence_counts(self):
        got = rc.check_code_fence('  ```\n  def x\n  ```')
        self.assertEqual(got['status'], rc.VIOLATION)

    def test_inline_backticks_are_not_a_fence(self):
        # Single backticks around a symbol are not what the contract bans,
        # and blocking them would send back reports that follow it.
        got = rc.check_code_fence(
            item(A, 'the method is `deliver_notification`'))
        self.assertEqual(got['status'], rc.OK)

    def test_two_backticks_are_not_a_fence(self):
        self.assertEqual(rc.check_code_fence('``x``')['status'], rc.OK)

    def test_an_empty_report_is_not_a_violation(self):
        for text in ('', None):
            with self.subTest(text=text):
                self.assertEqual(rc.check_code_fence(text)['status'], rc.OK)

    def test_the_reason_quotes_the_opening_line(self):
        got = rc.check_code_fence('```ruby\ndef x\n```')
        self.assertIn('```ruby', got['reason'])
        self.assertIn('def x', got['reason'])


class DeclaredLengthTests(unittest.TestCase):
    """A worker that states a value's length has checked its own copy.

    The sonnet run at 9346d19 returned a 64-hex digest with three
    characters missing (reviews/a-suite-failures-9346d19-2026-09-16.md
    section 2). Nothing offline can tell a correct digest from a wrong
    one -- but a digest the report itself calls 64 characters long, which
    is 61 characters long, is wrong on its own terms.
    """

    def test_a_declaration_that_matches_the_value_passes(self):
        got = rc.check_declared_lengths(
            'confirmed: /srv/one.json — payload_sha (64 chars): '
            'sha256:' + '6' * 64)
        self.assertEqual(got['status'], rc.OK)
        self.assertEqual(got['mismatched'], [])

    def test_a_short_copy_of_a_declared_value_is_a_violation(self):
        got = rc.check_declared_lengths(
            'confirmed: /srv/one.json — payload_sha (64 chars): '
            'sha256:' + '6' * 61)
        self.assertEqual(got['status'], rc.VIOLATION)
        self.assertEqual(len(got['mismatched']), 1)
        self.assertIn('64', got['reason'])

    def test_a_report_that_declares_nothing_is_undetermined(self):
        # No opinion: this check only reads what the worker asserted, so a
        # report using the older form must not be sent back by it.
        got = rc.check_declared_lengths(
            'confirmed: /srv/one.json — payload_sha: sha256:' + '6' * 61)
        self.assertEqual(got['status'], rc.UNDETERMINED)

    def test_the_word_characters_is_the_same_declaration(self):
        self.assertEqual(rc.check_declared_lengths(
            'confirmed: /p — token (10 characters): abcdefghij')['status'],
            rc.OK)

    def test_a_declaration_counts_the_value_not_the_whole_line(self):
        # The line is far longer than 10; only the literal is measured.
        self.assertEqual(rc.check_declared_lengths(
            'confirmed: /srv/data.json — api_key (10 chars): `abcdefghij`'
        )['status'], rc.OK)

    def test_a_line_count_is_not_a_value_declaration(self):
        # `40 lines` is not a character count and must not be matched.
        self.assertEqual(rc.check_declared_lengths(
            'confirmed: /p — the file is 40 lines long')['status'],
            rc.UNDETERMINED)

    def test_an_unconfirmed_line_is_not_judged(self):
        self.assertEqual(rc.check_declared_lengths(
            'unconfirmed: /p — payload_sha (64 chars): unread')['status'],
            rc.UNDETERMINED)
