#!/usr/bin/env python3
"""Offline controls for current-run aggregation and evidence completeness."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import judge


class AggregateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for d in ('v', 's', 'f'):
            (self.root / d).mkdir()
        self.catalog = json.loads(Path(judge.__file__).with_name('cases.json').read_text())['cases']
        self.manifest = {'planned': [], 'required': [
            {'case': c['id'], 'mode': m} for c in self.catalog for m in c['modes']]}

    def put(self, name, obj):
        (self.root / name).write_text(json.dumps(obj))

    def add(self, cid='auto-bulk-facts', modes=('direct', 'auto')):
        spec = next(c for c in self.catalog if c['id'] == cid)
        for rel in spec.get('fixture_bytes', []):
            f = self.root / 'f' / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text('x' * 1000)
        for mode in modes:
            self.manifest['planned'].append({'case': cid, 'mode': mode})
            stem = cid + '.' + mode
            self.put('s/' + stem + '.json', spec)
            self.put('v/' + stem + '.json', {
                'case': cid, 'mode': mode, 'verdict': 'pass', 'checks': {},
                'metrics': {'parent_added_utf8_bytes': 500 if mode == 'direct' else 20,
                            'parent_input_tokens': {'uncached': 1, 'cache_read': 0, 'cache_creation': 0},
                            'parent_output_tokens': 2}})
        return spec

    def run_aggregate(self):
        self.put('manifest.json', self.manifest)
        with contextlib.redirect_stdout(io.StringIO()):
            status = judge.aggregate(str(self.root/'v'), str(self.root/'s'), str(self.root/'f'),
                                     str(self.root/'out.json'), str(self.root/'manifest.json'))
        return status, json.loads((self.root/'out.json').read_text())

    def test_selected_success_not_release(self):
        self.add()
        status, out = self.run_aggregate()
        self.assertEqual(status, 0)
        self.assertTrue(out['selected_run_valid'])
        self.assertFalse(out['release_eligible'])

    def test_full_mandatory_success_is_release_eligible(self):
        for spec in self.catalog:
            self.add(spec['id'], tuple(spec['modes']))
            for mode in spec['modes']:
                stem = spec['id'] + '.' + mode
                if spec.get('disk_check'):
                    self.put('v/' + stem + '.disk.json', {'disk_ok': True})
                if spec.get('isolation') == 'writer_body_absent':
                    p = self.root/'v'/(stem + '.json')
                    v = json.loads(p.read_text())
                    v['checks']['writer_body_absent'] = True
                    p.write_text(json.dumps(v))
        status, out = self.run_aggregate()
        self.assertEqual(status, 0, out['errors'])
        self.assertTrue(out['release_eligible'])

    def test_empty_and_missing_manifest_fail(self):
        self.assertEqual(self.run_aggregate()[0], 1)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(judge.aggregate(str(self.root/'v'), str(self.root/'s'),
                                           str(self.root/'f'), str(self.root/'out.json')), 1)

    def test_missing_mode_fails(self):
        self.add(modes=('auto',))
        self.assertEqual(self.run_aggregate()[0], 1)

    def test_missing_expected_verdict_or_spec_fails(self):
        self.add()
        for folder in ('v', 's'):
            with self.subTest(folder=folder):
                p = self.root/folder/'auto-bulk-facts.auto.json'
                contents = p.read_text()
                p.unlink()
                self.assertEqual(self.run_aggregate()[0], 1)
                p.write_text(contents)

    def test_unplanned_stale_verdict_ignored(self):
        self.add()
        self.put('v/stale.auto.json', {'case': 'stale', 'mode': 'auto', 'verdict': 'fail'})
        status, out = self.run_aggregate()
        self.assertEqual(status, 0)
        self.assertNotIn('stale', out['cases'])

    def test_missing_fixture_fails(self):
        spec = self.add()
        (self.root/'f'/spec['fixture_bytes'][0]).unlink()
        self.assertEqual(self.run_aggregate()[0], 1)

    def test_missing_token_evidence_fails(self):
        self.add()
        p = self.root/'v/auto-bulk-facts.auto.json'
        v = json.loads(p.read_text())
        del v['metrics']['parent_input_tokens']['cache_read']
        p.write_text(json.dumps(v))
        self.assertEqual(self.run_aggregate()[0], 1)

    def test_disk_evidence_required(self):
        cid = 'auto-small-writer'
        self.add(cid, ('auto',))
        self.assertEqual(self.run_aggregate()[0], 1)
        self.put('v/' + cid + '.auto.disk.json', {'disk_ok': True})
        self.assertEqual(self.run_aggregate()[0], 0)

    def test_writer_leak_evidence_required(self):
        cid = 'compare-code-writer-ok'
        self.add(cid, ('auto',))
        self.put('v/' + cid + '.auto.disk.json', {'disk_ok': True})
        self.assertEqual(self.run_aggregate()[0], 1)
        p = self.root/'v'/ (cid + '.auto.json')
        v = json.loads(p.read_text())
        v['checks']['writer_body_absent'] = True
        p.write_text(json.dumps(v))
        self.assertEqual(self.run_aggregate()[0], 0)


if __name__ == '__main__':
    unittest.main()
