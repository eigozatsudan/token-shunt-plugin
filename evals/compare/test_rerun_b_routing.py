import unittest

from routing_checks import metadata_only_bash
from judge import bash_recovers_body


class MetadataRecoveryTests(unittest.TestCase):
    def test_live_metadata_commands(self):
        commands = [
            "sed -n '1,400p' /fixtures/bulk_facts.py | wc -c",
            'for f in /app/user.rb /app/notifiable.rb /app/job.rb; '
            'do echo "$f"; wc -c "$f"; awk \'END{print NR}\' "$f"; done',
            'for f in "/app/a b.rb"; do wc -l "$f"; done',
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(metadata_only_bash(command))
                self.assertFalse(bash_recovers_body({'input': {'command': command}}, '/app/user.rb'))

    def test_body_emitting_and_dynamic_variants_are_not_exempt(self):
        commands = [
            "sed -n '1,400p' /app/user.rb",
            "sed -n '1,400p' /app/user.rb | tee /tmp/body | wc -c",
            "sed -n '1,400p' /app/user.rb | wc -c; cat /app/user.rb",
            "sed -n '1,400p' /app/user.rb | wc -c || cat /app/user.rb",
            "sed -n '1,400p' /app/user.rb 2>&1 | wc -c",
            'for f in /app/user.rb; do cat "$f"; done',
            'for f in /app/user.rb; do awk \'{print}\' "$f"; done',
            'for f in /app/user.rb; do echo "$(cat /app/user.rb)"; done',
            'for f in /app/user.rb; do echo `cat /app/user.rb`; done',
            'for f in /app/*; do wc -l "$f"; done',
            'for f in /app/user.rb; do wc -l "$f"; done; cat /app/user.rb',
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertFalse(metadata_only_bash(command))

    def test_recovery_judge_keeps_body_commands(self):
        for command in (
                "sed -n '1,400p' /app/user.rb",
                "sed -n '1,400p' /app/user.rb | tee /tmp/body | wc -c",
                'for f in /app/user.rb; do cat "$f"; done',
                "sed -n '1,400p' /app/user.rb | wc -c; cat /app/user.rb"):
            with self.subTest(command=command):
                self.assertTrue(bash_recovers_body({'input': {'command': command}}, '/app/user.rb'))


if __name__ == '__main__':
    unittest.main()
