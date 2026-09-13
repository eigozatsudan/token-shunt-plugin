---
name: code-writer
description: Use for substantial tests, config, docstrings, type stubs, or generation where more than 80% is predictable from a reference file. Keep small generation in the parent under the small-task policy. Do not use for novel logic, debugging, or safety-critical code.
---

# code-writer

Interpret --worker-model auto|haiku|sonnet before any Agent invocation.
Default: auto. Reject unknown values before starting a worker.
For delegated work, invoke Agent(subagent_type="token-shunt:bulk-reader"
or "token-shunt:code-writer", model="haiku"|"sonnet", prompt=...)
according to --worker-model. auto starts with haiku.

Examples:

```text
/token-shunt:code-writer --worker-model haiku --reference /abs/greeter.py --target /abs/greeter_test.py --verify "python -m unittest /abs/greeter_test.py" --spec "参照に沿ったテストを生成"
```

## Fixed procedure

1. **Small-task check first (§26.2).** If the expected output is under 50
   lines AND the reference total is <= 16384 bytes AND each needed Read
   would pass the Read hook, the parent writes and verifies directly — no
   delegation. Without a reference file path, do not use this skill; the
   parent writes small output itself. Never spawn a worker just to
   estimate output size.

2. **Delegation.** `subagent_type` is exactly `token-shunt:code-writer`;
   `model` per --worker-model (auto starts with haiku). Pass: the spec,
   the reference path(s), the target path, and the **verification
   command**. The verification command takes only the target path as an
   argument and must not print the body to stdout. If the spec does not
   name one, use the generic fallback:

   - `.py`: `python -m py_compile <target>` (for tests:
     `python -m unittest <target>`)
   - `.json`: `jq empty <target>`
   - `.yaml` / `.yml`: minimal contract check, same as `.md` (no PyYAML
     runtime dependency; syntax correctness not guaranteed)
   - `.toml`: `python -c "import sys,tomllib;tomllib.load(open(sys.argv[1],'rb'))" <target>`
     (3.11+; on ImportError fall back to minimal contract check)
   - text without a syntax checker (`.md` etc.): **minimal contract
     check** — file non-empty, no gratuitous fence wrapping the whole
     output, line count not orders of magnitude off the spec estimate.
     Proper Markdown code blocks are allowed. This catches empty/coarse
     failures only; it does NOT guarantee content correctness or detect
     mid-generation truncation. The parent runs it via Bash; the body is
     not printed to stdout.
   - If none of the above applies and even a minimal check cannot be
     defined: do not use this skill.

   "No verification command exists" is never a reason for the parent to
   generate the body itself — the generated body would enter the parent
   as output tokens and the purpose is lost.

3. **Serialization.** Same target → serial. Parallel only when targets
   are disjoint.

4. The parent never views the generated code. Follow-on work uses the
   just-written file as the next reference.

5. **Completion requires parent verification.** The child's summary alone
   is not done. The parent runs the verification command via Bash and
   confirms exit 0 (for unittest: `Ran N tests` with N >= 1 and no
   FAIL/ERROR). Report `verification:` level + scope briefly:

   - `minimal`: minimal contract check passed. Generated but content
     unverified — not a completed user task.
   - `syntax`: py_compile / jq empty / TOML parse passed. Generated but
     content unverified — not a completed user task.
   - `requirements`: only when the spec's acceptance conditions were
     verified — via the verification command or targeted Reads of just
     the needed parts. Do not generalize one passing test into unverified
     requirements.
   - If acceptance cannot be confirmed: `status: partial`,
     `stop_reason: verification_incomplete`, plus remaining checks.
   - Verification failure: the parent fixes it with a short diagnosis +
     targeted Read, or re-delegates at most once within Model escalation
     below and the remaining invocation budget. Never re-generate solely
     for lack of a verification means. Never paste the generated body
     into the parent.

6. Surgical follow-up: from the summary, targeted-Read only the needed
   spots and Edit surgically, then re-run step 5's verification.

7. There is no hook on Write. If the parent starts generating itself,
   nothing stops it — the discipline is contractual, and the evals treat
   parent-side Write as a path violation.

## Model escalation

- Before any retry, confirm the current target (Read or `stat`). If
  others edited it, do not auto-overwrite.
- auto: first attempt haiku. Escalate to sonnet at most once, and only
  for: missing required evidence, a response-contract violation, or a
  failed post-generation verification. Never escalate on confidence
  alone.
- Escalation retry carries the original spec, the same reference and
  target paths, and a short note on what was missing. It does not carry
  the haiku transcript (both attempts are billed). The child Reads an
  existing target first; the parent re-verifies after generation. Stop
  after the second failure.
- No escalation on: unspecified dependencies, Read/context limits,
  budget exhaustion, auth/permission errors, missing references,
  unsupported model. Report those as partial.
- Shared cap: Agent invocations for one user question (both workers,
  batches, boundary checks, retries) total at most 4. After the cap,
  report partial plus the unfinished range. Do not bypass via another
  agent name or resume.
