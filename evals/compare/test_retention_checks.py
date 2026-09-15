"""The three retention checks, including cases the saved corpus lacks.

The archived runs are dominated by one shape: three golds in three
different files. Everything that shape cannot exercise -- two facts from
one file, a partial drop, a demoted line, a vanished file -- is synthetic
here, because that is exactly where file coverage and line retention stop
agreeing.
"""
import os
import sys
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


if __name__ == '__main__':
    unittest.main()
