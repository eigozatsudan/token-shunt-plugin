"""Evidence regressions for the September 14b native command shapes."""
import json
import unittest

from flow_checks import verification_errors
from judge import Transcript


def transcript(command, output='', error=False):
    return Transcript([
        {'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'id': 'verify', 'name': 'Bash',
             'input': {'command': command}}]}},
        {'type': 'user', 'message': {'content': [
            {'type': 'tool_result', 'tool_use_id': 'verify',
             'content': output, 'is_error': error}]}},
        {'type': 'result', 'result': 'Verification finished.'},
    ])


class NativeVerificationEvidence(unittest.TestCase):
    def test_successful_count_compile_and_label_chain(self):
        command = 'wc -l /tmp/w49.py && python3 -m py_compile /tmp/w49.py && echo COMPILE_OK'
        self.assertEqual([], verification_errors(transcript(command, '49 /tmp/w49.py\nCOMPILE_OK'),
                                                {}, {'parent_py_compile': '/tmp/w49.py'}))
        self.assertTrue(verification_errors(transcript(command, error=True),
                                           {}, {'parent_py_compile': '/tmp/w49.py'}))

    def test_compile_cannot_be_masked_or_simulated(self):
        for command in (
            'python3 -m py_compile /tmp/w49.py; echo COMPILE_OK',
            'python3 -m py_compile /tmp/w49.py || true',
            'echo python3 -m py_compile /tmp/w49.py',
            'python3 -m py_compile /tmp/other.py && echo COMPILE_OK',
            'false && python3 -m py_compile /tmp/w49.py; true',
            'python3 -m py_compile /tmp/w49.py | cat',
            "echo '&&' python3 -m py_compile /tmp/w49.py",
            'echo "&&" python3 -m py_compile /tmp/w49.py',
            r'echo \&\& python3 -m py_compile /tmp/w49.py',
            'echo ignored\npython3 -m py_compile /tmp/w49.py\ntrue',

        ):
            with self.subTest(command=command):
                self.assertTrue(verification_errors(transcript(command), {},
                                                    {'parent_py_compile': '/tmp/w49.py'}))

    def batch(self):
        checks = [{'path': '/work/good.json', 'level': 'syntax', 'checker': '/eval/flow_checks.py'},
                  {'path': '/work/trunc.json', 'level': 'syntax', 'checker': '/eval/flow_checks.py', 'ok': False}]
        command = ('cd /work && \\\n'
                   'echo "=== good ===" && \\\n'
                   'python3 /eval/flow_checks.py --verify syntax good.json; echo "exit:$?"; \\\n'
                   'echo "=== trunc ===" && \\\n'
                   'python3 /eval/flow_checks.py --verify syntax trunc.json; echo "exit:$?"')
        output = ('=== good ===\n' + json.dumps({'path': 'good.json', 'verification': 'syntax', 'ok': True})
                  + '\nexit:0\n=== trunc ===\n'
                  + json.dumps({'path': 'trunc.json', 'verification': 'syntax', 'ok': False}) + '\nexit:1')
        return command, output, {'verification_artifacts': checks}

    def test_continued_batch_preserves_each_json_outcome(self):
        command, output, exp = self.batch()
        self.assertEqual([], verification_errors(transcript(command, output), {}, exp))

    def test_quoted_controls_are_not_batch_execution(self):
        command, output, exp = self.batch()
        for bad_command in (
            'echo "' + command.replace('"', "'") + '"',
            command.replace('cd /work &&', "cd /work '&&'"),
            command.replace('cd /work &&', r'cd /work \&\&'),
            'echo "label &&\npython3 /eval/flow_checks.py --verify syntax /work/good.json"',
        ):
            with self.subTest(command=bad_command):
                self.assertTrue(verification_errors(transcript(bad_command, output), {}, exp))

    def test_batch_rejects_missing_wrong_or_masked_evidence(self):
        command, output, exp = self.batch()
        for bad in (output.replace('exit:1', 'exit:0'),
                    output.replace('trunc.json', 'other.json'),
                    output.replace('"ok": false', '"ok": true'),
                    '\n'.join(output.splitlines()[3:])):
            with self.subTest(output=bad):
                self.assertTrue(verification_errors(transcript(command, bad), {}, exp))
        for bad_command in (command.replace('--verify syntax good.json', '--verify syntax good.json || true'),
                            command.replace('/eval/flow_checks.py', '$(echo /eval/flow_checks.py)')):
            self.assertTrue(verification_errors(transcript(bad_command, output), {}, exp))


if __name__ == '__main__':
    unittest.main()
