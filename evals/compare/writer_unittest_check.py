"""Isolated behavioral check; invoked by flow_checks, never mutates fixture files.

Only calls to the exact reference's greet during unittest execution count. Source
loaders also cover explicit spec_from_file_location imports and import aliases.
"""
import functools
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import sys
import unittest


def check(target, reference, mutation):
    reference = Path(reference).resolve()
    active = False
    calls = 0
    original_exec = importlib.machinery.SourceFileLoader.exec_module

    def execute(loader, module):
        original_exec(loader, module)
        if Path(loader.path).resolve() != reference:
            return
        original = module.greet

        @functools.wraps(original)
        def greet(*args, **kwargs):
            nonlocal calls
            if active:
                calls += 1
                if mutation:
                    # Break both normal greetings and the empty-name exception.
                    return '__WRITER_BOUNDARY_BROKEN_GREETING__'
            return original(*args, **kwargs)

        module.greet = greet

    importlib.machinery.SourceFileLoader.exec_module = execute
    sys.path[:0] = [str(Path(target).parent), str(reference.parent)]
    spec = importlib.util.spec_from_file_location('_writer_boundary_tests', target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    active = True
    result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
    active = False
    if result.testsRun < 1 or calls < 1:
        return False
    if mutation:
        return bool(result.failures or result.errors)
    return result.wasSuccessful()


if __name__ == '__main__':
    ok = check(sys.argv[1], sys.argv[2], sys.argv[3] == 'mutation')
    if ok:
        Path(sys.argv[4]).write_text('writer-boundary-check:passed', encoding='utf-8')
    sys.exit(0 if ok else 1)
