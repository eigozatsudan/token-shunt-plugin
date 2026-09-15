"""Exercise the exact build verifier with Python and zipinfo-only PATHs."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ('check-file-size', 'check-bash-read', 'check-jq', 'check-agent-model',
         'check-reader-contract', 'check-final-answer')


class ZipVerificationTests(unittest.TestCase):
    def test_dirty_tree_build_excludes_caches_both_backends(self):
        for backend in ('zip', 'python3'):
            with self.subTest(backend=backend), tempfile.TemporaryDirectory() as tmp:
                if not shutil.which(backend):
                    self.fail(f'{backend} required to test builder')
                root = Path(tmp)
                (root / 'scripts').mkdir()
                shutil.copy2(ROOT / 'scripts/build-zip.sh', root / 'scripts/build-zip.sh')
                shutil.copytree(ROOT / 'plugin', root / 'plugin')
                for name in ('__pycache__/root.pyc', 'hooks/__pycache__/nested.pyc',
                             'hooks/loose.pyc', 'hooks/legacy.pyo'):
                    path = root / 'plugin' / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b'stale bytecode')
                bindir = root / 'bin'
                bindir.mkdir()
                # The zip branch also exercises verification without Python.
                for tool in ('bash', 'dirname', 'chmod', 'rm', 'awk', backend,
                             *(['zipinfo'] if backend == 'zip' else [])):
                    os.symlink(shutil.which(tool), bindir / tool)
                result = subprocess.run(['/bin/bash', str(root / 'scripts/build-zip.sh')],
                                        env={**os.environ, 'PATH': str(bindir)}, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                with zipfile.ZipFile(root / 'token-shunt.zip') as archive:
                    names = archive.namelist()
                    self.assertIn('.claude-plugin/plugin.json', names)
                    self.assertFalse(any('__pycache__' in n.split('/') or n.endswith(('.pyc', '.pyo'))
                                         for n in names), names)
                    for hook in HOOKS:
                        self.assertTrue(archive.getinfo('hooks/' + hook).external_attr >> 16 & 0o111)

    def test_archive_contract_both_backends(self):
        source = (ROOT / 'scripts/build-zip.sh').read_text()
        verifier = source[source.index('verify() {'):source.index('\nverify "$ZIP"')]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for backend in ('python3', 'zipinfo'):
                if not shutil.which(backend):
                    self.fail(f'{backend} required to test verifier')
                bindir = tmp / backend
                bindir.mkdir()
                for tool in (backend, 'awk'):
                    os.symlink(shutil.which(tool), bindir / tool)
                for prefix in ('', 'plugin/'):
                    for defect in ('none', 'missing', 'not_executable', 'duplicate', 'wrong_directory', 'extra_manifest', 'mode_without_type',
                                   'cache_dir', 'root_cache', 'pyc', 'pyo'):
                        with self.subTest(backend=backend, prefix=prefix, defect=defect):
                            archive = tmp / 'test.zip'
                            with warnings.catch_warnings():
                                warnings.simplefilter('ignore', UserWarning)
                                with zipfile.ZipFile(archive, 'w') as z:
                                    z.writestr(prefix + '.claude-plugin/plugin.json', '{}')
                                    for hook in HOOKS:
                                        if hook == 'check-agent-model' and defect == 'missing':
                                            continue
                                        path = prefix + 'hooks/' + hook
                                        if hook == 'check-agent-model' and defect == 'wrong_directory':
                                            path = prefix + 'elsewhere/' + hook
                                        entry = zipfile.ZipInfo(path)
                                        mode = 0o100644 if hook == 'check-agent-model' and defect == 'not_executable' else 0o100755
                                        if defect == 'mode_without_type':
                                            mode = 0o755
                                        entry.external_attr = mode << 16
                                        z.writestr(entry, '#!/bin/sh\n')
                                        if hook == 'check-agent-model' and defect == 'duplicate':
                                            z.writestr(entry, '#!/bin/sh\n')
                                    if defect == 'extra_manifest':
                                        z.writestr('other/.claude-plugin/plugin.json', '{}')
                                    cache_paths = {'cache_dir': 'hooks/__pycache__/data',
                                                   'root_cache': '__pycache__/', 'pyc': 'hooks/stale.pyc',
                                                   'pyo': 'hooks/stale.pyo'}
                                    if defect in cache_paths:
                                        z.writestr(prefix + cache_paths[defect], 'stale')
                            result = subprocess.run(['/bin/bash', '-c', verifier + '\nverify "$1"', 'test', str(archive)],
                                                    env={**os.environ, 'PATH': str(bindir), 'LC_ALL': 'C'}, capture_output=True, text=True)
                            self.assertEqual(result.returncode == 0, defect in ('none', 'mode_without_type'), result.stderr)


if __name__ == '__main__':
    unittest.main()
