"""Source identity controls for the second September 14 live rerun."""
import json
from pathlib import Path
import unittest

from judge import gold_confirmed_ok, gold_path_needles


class CatalogEvidenceContracts(unittest.TestCase):
    def setUp(self):
        self.cases = json.loads(Path(__file__).with_name('cases.json').read_text())['cases']

    def test_declared_gold_sources_are_actual_case_fixtures(self):
        for case in self.cases:
            for gold, sources in case.get('gold_paths', {}).items():
                for source in sources if isinstance(sources, list) else [sources]:
                    with self.subTest(case=case['id'], gold=gold, source=source):
                        self.assertIn(source, case['fixtures'])

    def test_exact_run_source_passes_but_basename_and_other_run_do_not(self):
        for case in self.cases:
            if not case.get('gold_paths'):
                continue
            spec = dict(case, fixture_root='/runs/current/fixtures')
            for gold in case['gold_paths']:
                for path in gold_path_needles(gold, spec):
                    with self.subTest(case=case['id'], gold=gold, path=path):
                        self.assertEqual([], gold_confirmed_ok(
                            f'- confirmed: {path} — {gold}', [gold], spec))
                        for wrong in (Path(path).name, path.replace('/current/', '/previous/')):
                            self.assertEqual([gold], gold_confirmed_ok(
                                f'- confirmed: {wrong} — {gold}', [gold], spec))
                        self.assertEqual([gold], gold_confirmed_ok(
                            f'- unconfirmed: {path} — {gold}', [gold], spec))


if __name__ == '__main__':
    unittest.main()
