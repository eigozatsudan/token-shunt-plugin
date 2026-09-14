"""Regression checks for the operational review's confirmed Bash findings."""
import json
import os
import shlex
from pathlib import Path
import subprocess
import tempfile
import unittest

HOOK = Path(__file__).resolve().parents[1] / "plugin/hooks/check-bash-read"


class BashOperationalHooksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="shunt-operational-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.large = (b"x" * 819 + b"\n") * 100
        self.small = b"small\n"
        (self.root / "large.txt").write_bytes(self.large)
        (self.root / "small.txt").write_bytes(self.small)
        for name in ("#large.txt", "file#name", "file #name"):
            (self.root / name).write_bytes(self.large)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith("TOKEN_SHUNT_")}

    def assert_command(self, command, decision, output_bytes, stderr_bytes=0):
        # Evaluate before execution: tee and redirections can replace operands.
        result = subprocess.run([str(HOOK)], input=json.dumps({"tool_input": {
            "command": command}}), cwd=self.root, env=self.env, text=True,
            capture_output=True, timeout=10)
        # Check Bash's actual stdout as well as the hook decision, so a parsing
        # assertion cannot accidentally encode a false-positive shell model.
        actual = subprocess.run(["bash", "--noprofile", "--norc", "-c", command],
                                cwd=self.root, env=self.env, capture_output=True,
                                timeout=10)
        self.assertEqual(actual.returncode, 0, actual.stderr.decode())
        self.assertEqual(len(actual.stdout), output_bytes)
        self.assertEqual(len(actual.stderr), stderr_bytes)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        observed = (json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]
                    if result.stdout else "pass")
        self.assertEqual(observed, decision, command)

    def test_redirect_spelling_words_preserve_following_operands(self):
        (self.root / "long.txt").write_bytes(b"x" * 82000)
        for name in (">", ">>", ">|", ">&", "2>", "22>", "&>", "&>>", ">file"):
            (self.root / name).write_bytes(b"")
            for spelling in (shlex.quote(name), '"' + name + '"',
                             "".join("\\" + c if c in ">&|" else c for c in name)):
                for tool in ("cat", "head -q", "tail -q"):
                    with self.subTest(spelling=spelling, tool=tool):
                        self.assert_command(f"{tool} {spelling} long.txt", "deny", 82000)

    def test_quoted_redirect_words_can_be_large_operands(self):
        for name in (">", ">file", "2>"):
            (self.root / name).write_bytes(self.large)
            with self.subTest(name=name):
                self.assert_command("cat " + shlex.quote(name), "deny", len(self.large))

    def test_quoted_redirect_words_with_large_head_tail_interval(self):
        (self.root / ">").write_bytes(b"")
        (self.root / "long.txt").write_bytes(b"x" * 82000)
        for tool in ("head", "tail"):
            with self.subTest(tool=tool):
                self.assert_command(f"{tool} -q '>' long.txt", "deny", 82000)
                self.assert_command(f"{tool} -q -c 1 '>' long.txt", "pass", 1)

    def test_token_kinds_survive_assignments_pipelines_and_cd(self):
        (self.root / ">").write_bytes(b"")
        for command in ("FLAG=yes cat '>' large.txt",
                        "cat '>' large.txt | cat",
                        "cat small.txt | FLAG=yes cat '>' large.txt",
                        "cd . && FLAG=yes cat '>' large.txt",
                        "cat '>' large.txt 2> errors.txt; true"):
            with self.subTest(command=command):
                self.assert_command(command, "deny", len(self.large))
        self.assert_command("cat large.txt | FLAG=yes head -c 1", "pass", 1)
        self.assert_command("cat small.txt | head -q -c 1 '>' large.txt", "deny", 1)

    def test_real_redirects_still_remove_only_their_targets(self):
        for redirection in ("2>", "22>", "2>>", "2>|", "2>&",
                            "02>", "002>>", "02>|"):
            with self.subTest(redirection=redirection):
                target = "1" if redirection == "2>&" else "large.txt"
                self.assert_command(f"cat small.txt {redirection} {target}",
                                    "pass", len(self.small))
                # The prior command may truncate large.txt as a real target.
                (self.root / "large.txt").write_bytes(self.large)
        self.assert_command("cat large.txt 2> errors.txt", "deny", len(self.large))
        for redirection in ("02>", "002>>", "02>|"):
            with self.subTest(redirection=redirection):
                self.assert_command(f"cat large.txt {redirection} errors.txt",
                                    "deny", len(self.large))

    def test_comment_redirection_does_not_hide_stdout(self):
        self.assert_command("cat large.txt # > discarded", "deny", len(self.large))

    def test_comment_file_is_not_an_operand(self):
        self.assert_command("cat small.txt # large.txt", "pass", len(self.small))

    def test_comment_operators_are_not_commands(self):
        self.assert_command("cat small.txt # | cat large.txt; cat large.txt",
                            "pass", len(self.small))

    def test_newline_ends_comment(self):
        self.assert_command("cat small.txt # > discarded\ncat large.txt",
                            "deny", len(self.small) + len(self.large))

    def test_hash_in_filename_is_not_comment(self):
        for filename in ("'#large.txt'", '"#large.txt"', r"\#large.txt", "file#name",
                         "''#large.txt", r"file\ #name"):
            with self.subTest(filename=filename):
                self.assert_command("cat " + filename, "deny", len(self.large))

    def test_last_cat_explicit_input(self):
        self.assert_command("cat small.txt | cat large.txt", "deny", len(self.large))

    def test_last_cat_input_after_bounded_middle_stage(self):
        self.assert_command("cat small.txt | head -c 1 | cat large.txt",
                            "deny", len(self.large))

    def test_middle_cat_explicit_input(self):
        self.assert_command("cat small.txt | cat large.txt | cat",
                            "deny", len(self.large))

    def test_small_pipeline_passes(self):
        self.assert_command("cat small.txt | cat small.txt | cat",
                            "pass", len(self.small))

    def test_tee_file_is_output_not_input(self):
        self.assert_command("cat small.txt | tee large.txt | cat",
                            "deny", len(self.small))

    def test_stdout_redirect_aliases(self):
        for target in ("/dev/stdout", "/dev/fd/1", "/proc/self/fd/1"):
            if not Path(target).exists():
                continue  # These descriptor aliases are platform dependent.
            with self.subTest(target=target):
                self.assert_command("cat large.txt > " + target, "deny", len(self.large))
                self.assert_command(f'cat large.txt>"{target}"&', "deny", len(self.large))

    @unittest.skipUnless(Path("/dev/stdout").exists(), "requires /dev/stdout")
    def test_stdout_redirect_symlink(self):
        (self.root / "stdout-link").symlink_to("/dev/stdout")
        self.assert_command("cat large.txt > stdout-link", "deny", len(self.large))

    def test_regular_file_redirect_passes(self):
        self.assert_command("cat large.txt > output.txt", "pass", 0)
        self.assertEqual((self.root / "output.txt").read_bytes(), self.large)

    @unittest.skipUnless(Path("/dev/stderr").exists(), "requires /dev/stderr")
    def test_zero_padded_stdout_redirects(self):
        for fd in ("1", "01", "001", "0" * 80 + "1"):
            for operator in (">", ">>", ">|"):
                with self.subTest(fd=fd, operator=operator):
                    self.assert_command(
                        f"cat large.txt > first.txt {fd}{operator}/dev/stderr",
                        "deny", 0, len(self.large))
                    self.assert_command(
                        f"cat large.txt {fd}{operator}output.txt", "pass", 0)
                    self.assert_command(
                        f"cat large.txt {fd}{operator}/dev/null", "pass", 0)

    @unittest.skipUnless(Path("/dev/stderr").exists(), "requires /dev/stderr")
    def test_stdout_redirect_descriptor_token_boundaries(self):
        for spelling, filename in (("file2", "file2"), ("'2'", "2"),
                                   ('"02"', "02"), (r"\2", "2"),
                                   ("''2", "2"), ("0'2'", "02")):
            (self.root / filename).write_bytes(b"")
            for operator in (">", ">>", ">|"):
                with self.subTest(spelling=spelling, operator=operator):
                    self.assert_command(
                        f"cat large.txt > first.txt {spelling}{operator}/dev/stderr",
                        "deny", 0, len(self.large))
                    self.assert_command(
                        f"cat large.txt {spelling}{operator}output.txt", "pass", 0)

    def test_null_redirect_passes(self):
        self.assert_command("cat large.txt > /dev/null", "pass", 0)

    def test_quoted_regular_file_redirect_passes(self):
        self.assert_command('cat large.txt>"output space.txt"', "pass", 0)
        self.assertEqual((self.root / "output space.txt").read_bytes(), self.large)

    def test_multiple_regular_file_redirects_pass(self):
        self.assert_command("cat large.txt > first.txt > final.txt", "pass", 0)
        self.assertEqual((self.root / "first.txt").read_bytes(), b"")
        self.assertEqual((self.root / "final.txt").read_bytes(), self.large)

    @unittest.skipUnless(Path("/dev/stdout").exists(), "requires /dev/stdout")
    def test_mixed_redirect_targets_conservatively_denied(self):
        # /dev/stdout reopens the already redirected descriptor here, so Bash
        # emits no captured output. Mixed targets intentionally stay conservative.
        self.assert_command("cat large.txt > first.txt > /dev/stdout",
                            "deny", 0)

    @unittest.skipUnless(Path("/dev/stderr").exists(), "requires /dev/stderr")
    def test_bounded_pipeline_checks_stdout_that_bypasses_limiter(self):
        redirects = ("1>&2", "01>&02", ">&2", "3>&2 1>&3",
                     ">/dev/stderr", ">>/dev/stderr", ">|/dev/stderr",
                     ">/dev/fd/2", ">/proc/self/fd/2")
        for redirect in redirects:
            if redirect.startswith(">/") and not Path(redirect.lstrip(">|")).exists():
                continue
            for connector in ("|", "|&"):
                with self.subTest(redirect=redirect, connector=connector):
                    self.assert_command(
                        f"cat large.txt {redirect} {connector} head -c 1",
                        "deny", 0, len(self.large))
        # The leaking stage need not be the first stage.
        self.assert_command("cat small.txt | cat large.txt 1>&2 | head -c 1",
                            "deny", 0, len(self.large))
        self.assert_command("cat small.txt 1>&2 | head -c 1",
                            "pass", 0, len(self.small))
        # A stage's own supported byte/line bound still limits its side output.
        self.assert_command("head -c 1 large.txt 1>&2 | head -c 1",
                            "pass", 0, 1)
        self.assert_command("tail -c 1 large.txt >/dev/stderr | head -c 1",
                            "pass", 0, 1)
        self.assert_command("head -n 1 large.txt 1>&2 | head -c 1",
                            "pass", 0, 820)


    @unittest.skipUnless(Path("/dev/stderr").exists(), "requires /dev/stderr")
    def test_bounded_pipeline_checks_tee_side_outputs(self):
        (self.root / "stderr-link").symlink_to("/dev/stderr")
        for target in ("/dev/stderr", "/dev/fd/2", "stderr-link"):
            if target.startswith("/") and not Path(target).exists():
                continue
            with self.subTest(target=target):
                # tail drains its input, making the complete stderr copy
                # deterministic rather than racing head's early SIGPIPE.
                self.assert_command(f"cat large.txt | tee {target} | tail -c 1",
                                    "deny", 1, len(self.large))
        self.assert_command("cat large.txt | tee out /dev/stderr | tail -c 1",
                            "deny", 1, len(self.large))

    @unittest.skipUnless(Path("/dev/stderr").exists(), "requires /dev/stderr")
    def test_bounded_pipeline_preserves_safe_descriptor_routes(self):
        for redirects in ("", "2>&1", "2>&1 1>&2", "3>&1 1>&3",
                          ">/dev/stdout", ">/dev/fd/1"):
            if redirects.startswith(">/") and not Path(redirects[1:]).exists():
                continue
            with self.subTest(redirects=redirects):
                self.assert_command(f"cat large.txt {redirects} | head -c 1",
                                    "pass", 1)
        for redirects in (">output.txt", ">/dev/null", "3>output.txt 1>&3"):
            with self.subTest(redirects=redirects):
                self.assert_command(f"cat large.txt {redirects} | head -c 1",
                                    "pass", 0)
        self.assert_command("cat large.txt | tee output.txt | tail -c 1",
                            "pass", 1)
        self.assertEqual((self.root / "output.txt").read_bytes(), self.large)
        self.assert_command("cat large.txt | tee /dev/stderr 2>&1 | tail -c 1",
                            "pass", 1)
        self.assert_command("cat large.txt | tee /dev/stderr |& tail -c 1",
                            "pass", 1)

    @unittest.skipUnless(Path("/dev/stderr").exists(), "requires /dev/stderr")
    def test_upstream_byte_bound_applies_to_each_side_output(self):
        self.assert_command("cat large.txt | head -c 1 | tee /dev/stderr | head -c 1",
                            "pass", 1, 1)
        self.assert_command("cat large.txt | head -c 1 1>&2 | head -c 1",
                            "pass", 0, 1)
        self.assert_command("cat large.txt | tail -c 1 >/dev/stderr | head -c 1",
                            "pass", 0, 1)
        (self.root / "otherlarge.txt").write_bytes(self.large)
        self.assert_command(
            "cat large.txt | head -c 1 | cat otherlarge.txt 1>&2 | head -c 1",
            "deny", 0, len(self.large))
        self.assert_command(
            "cat large.txt 1>&2 | head -c 1 | tee /dev/stderr | head -c 1",
            "deny", 0, len(self.large))
        # A quoted redirection-looking filename remains an explicit input,
        # even though the preceding source has a byte bound.
        (self.root / "1>&2").write_bytes(self.large)
        self.assert_command(
            "cat small.txt | head -c 1 | cat '1>&2' 1>&2 | head -c 1",
            "deny", 0, len(self.large))

    def test_bounded_pipeline_quoted_redirect_words_are_operands(self):
        for name in ("1>&2", "2>", "&>"):
            (self.root / name).write_bytes(b"")
            self.assert_command("cat " + shlex.quote(name) + " large.txt | head -c 1",
                                "pass", 1)


if __name__ == "__main__":
    unittest.main()
