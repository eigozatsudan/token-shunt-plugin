# token-shunt

Claude Code plugin that keeps large-file contents and boilerplate output out of
the parent context. PreToolUse hooks deny oversized `Read` / `Bash` reads and
point the parent at the `bulk-reader` / `code-writer` named subagents, which
return short summaries instead of file bodies.

Shipping: keeps large bodies out of the parent; **cost reduction is unproven**.
Cost claims only if §26.5 measurements are not worse than direct. Isolation
pass and cost regression are not separate product editions.

Design: `docs/2026-09-12-token-shunt-design.md` (approved 2026-09-13).

Status: **v0.1 under development.** Hooks, manifests, packaging, and hook evals
(PR1) plus the `bulk-reader` / `code-writer` skills + named agents and the
real-machine compare-eval machinery (PR2) are in tree. Compare evals skip if
`claude` is missing; they fail on plugin load failure, direct-mode
contamination, or foreign hooks. The plugin is not release-ready until those
runs pass. Token savings are unconfirmed. Do not call body-byte cuts "token
savings."

## Requirements

- Claude Code (a version that puts `agent_type` on the PreToolUse hook stdin)
- `jq` on `PATH` — required. If missing, SessionStart warns once and both
  PreToolUse hooks fail-closed (exit 2) on every `Read` and `Bash`.

## Install

```bash
# from source
claude --plugin-dir plugin/

# packaged zip (see docs/distribution/README.md)
scripts/build-zip.sh        # -> token-shunt.zip
claude --plugin-dir ./token-shunt.zip

# or add the repo-root marketplace (`owner.name` required), then install
# token-shunt from it. Zip hooks must carry Unix exec bits
# (`scripts/build-zip.sh` sets them).
```

Do not enable alongside Spotify `shunt@portal` (their deny would kill worker
reads; multiple PreToolUse denies merge as deny).

## What the hooks do

- `check-file-size` (Read): files over `TOKEN_SHUNT_MIN_LINES` (default 350)
  **or** `TOKEN_SHUNT_MIN_BYTES` (default 65536) are denied unless the request
  is a targeted `offset`/`limit` read whose actual byte/line range fits.
  `limit=1` gets no exception: a single line over `MIN_BYTES` is denied.
  Symbolic links are measured using the target file's size (also for Bash).
  Image / PDF / `.ipynb` paths pass (the official Read tool handles them via
  visual/page/cell paths, not raw text). Non-regular paths pass.
- `check-bash-read` (Bash): `cat`/`head`/`tail`/`less`/`more` on oversized
  files are denied. Quote-aware: `|` inside quotes is not a pipe. Pipes are
  judged by the last command (narrowing filters pass; `| head/tail` passes only
  for interpretable `-c N` with `N <= MIN_BYTES`; `| cat`/`tee`/`less`/`more`
  fall through to the first command). Compound commands (`;`/`&&`/`||`/newline/
  `&`) check every segment's explicit files at full thresholds. A plain
  `>`/`>>` stdout redirect on a single command passes.
  Leading literal `cd <dir>` / `cd -- <dir>` chains separated by `&&`, `;`,
  or newlines resolve subsequent file arguments from the destination.
- Passing a hook emits **no** `permissionDecision` — it never bypasses the
  normal permission flow or other hooks.
- `token-shunt:bulk-reader` (Read + Bash) and `token-shunt:code-writer`
  (Read only) `agent_type` values bypass the size gate so workers can read
  large files; permission checks are unchanged. `agent_type` is read only
  from the harness-set top-level field — `tool_input.agent_type` is
  model-controlled and ignored.

## Skills

- `/token-shunt:bulk-reader --worker-model auto|haiku|sonnet <paths...> --question "..."`
  delegates bounded reads (max 3 explicit paths per invocation, each read
  once; child answers within a 4000-char cap, `confirmed:`/`inferred:`/
  `unconfirmed:` + `status`/`stop_reason`). 4+ paths follow the inter-batch
  evidence contract: integrate only corroborated facts; do not guess
  unconfirmed relations.
- `/token-shunt:code-writer --worker-model auto|haiku|sonnet --reference <ref> --target <t> --verify "<cmd>" --spec "..."`
  delegates boilerplate generation; the parent runs the verify command and
  reports `verification: minimal|syntax|requirements`. `minimal` / `syntax`
  means generated but content-unverified — report `partial` plus remaining
  checks. Complete only when requirements are confirmed. Unknown
  `--worker-model` values are rejected before any worker starts.
- Model selection and small-task policy are SKILL.md conventions, not hook
  enforcement. Evals observe compliance; they do not defend every live call.
- Small-task: explicit files or known needed ranges totaling <=16KiB, with
  each Read passing the hook, stay in the parent. A few known lines on a
  large file (still under 16KiB) use parent targeted Read. Mid-band: over
  16KiB but under hook thresholds (e.g. 200 lines / 20KiB) is skill-judged
  delegation; isolation is best-effort. Generation under ~50 lines with
  <=16KiB references stays in the parent.
- auto starts Haiku and uses Sonnet only when needed. No guarantee of
  subscription-fee reduction or a 90% bill cut.

## Environment

| var | default | meaning |
|---|---|---|
| `TOKEN_SHUNT_MIN_LINES` | 350 | line threshold |
| `TOKEN_SHUNT_MIN_BYTES` | 65536 | byte threshold |
| `TOKEN_SHUNT_SCAN_BUDGET_BYTES` | 8388608 | scan byte budget (incl. offset skip; bounded lookahead as below) |
| `TOKEN_SHUNT_SCAN_BUDGET_MS` | 2000 | elapsed scan check; exceeded -> deny |
| `TOKEN_SHUNT_HOOK_LOG` | unset | eval fallback only; appends 1-line JSON per decision. Not for production |

Line scans bound input before parsing lines, so a huge single line cannot
force the parser to buffer the whole file. Each forward scan supplies at most
the byte budget plus one lookahead byte. Tail scans limit the suffix to the
same size before selecting lines, plus a separate one-byte newline probe.
These limits bound parser input; system utilities and the OS may read ahead
internally. A prefix cut off before the requested range is complete is denied.
The elapsed-time check runs after the bounded scan; it does not interrupt a
blocked filesystem read.

## Known limits (v0.1)

- `@file` references, `Grep` content mode, `sed`/`python -c`, and PowerShell
  are not gated. Nested/indirect invocations (`bash -c`, `xargs`, `dd if=`,
  `$(cat ...)`) and pipes to unknown tail commands pass (intended fail-open).
- Bash directory tracking is limited to leading literal `cd` chains. It does
  not interpret `||`, background lists, grouping, expansions, `cd` options
  other than `--`, or a `cd` after another command. Relative directory operands
  that depend on a nonempty `CDPATH` are also outside this tracking scope.
  Use explicit absolute file paths for reliable size checks in those cases.
- Explore / Plan / general-purpose launches themselves are not blocked; their
  large Reads are denied. Final-message quotes can still leak.
- code-writer Write is not hook-enforced. Completion is the parent's
  verification step.
- A parent can still drain a file via repeated in-budget targeted Reads
  (`limit=350` sliding); the hook does not correlate across calls. Sequential
  `limit=350` remains a hook limit, not a recovery path. The compare evals
  treat that as a path violation on the delegation side.
- PreToolUse hook timeout is fail-open (official): on a very slow FS the 10s
  hook timeout can fire before the scan budget, letting a large Read through.
- Edits are guaranteed only through a targeted Read of the original that
  passes the hook. `head`/`tail` are viewing-only; do not use Bash viewing as
  the edit-path original. byte-span / dd+temp / unread-Edit fallbacks are
  out of scope.
- The child's final message is the only parent boundary. Fences or quotes in
  the child reply become parent noise; there is no script fence-strip.
- A single huge file is one worker; do not even-split by lines.
- Compare-eval results are pending a working Claude login on this machine;
  until they pass, nothing here is release-validated.

The article's ~90% is *parent input-token* reduction on a different harness,
not this plugin's parent+child cost. Effect is likeliest when the parent is
Sonnet / Opus; a parent Haiku should expect isolation only. Parent input,
child usage, and combined estimated USD are separate metrics.

## Evals

```bash
evals/run.sh             # hook evals + zip + marketplace schema; no Claude CLI needed
evals/compare/run.sh     # real-machine compare evals; requires `claude` + auth
evals/compare/run.sh <case-id>          # single case
SUITE=A evals/compare/run.sh            # A suite only
python3 -m unittest discover -s evals/compare -p 'test_*.py' # offline regression checks
```

Compare evals run each case twice: direct (no plugin) vs delegated
(`--plugin-dir plugin/`). On this CLI, isolation uses `--setting-sources ""`
plus a clean cwd — `--bare` keeps enabled marketplace plugins and skips
plugin-agent registration, so it is not used (the spec's OAuth alternative,
not a contradiction). `isolation_ok` compares UTF-8 bytes vs UTF-8 bytes.
Skip if `claude` is missing. Fail on plugin load failure, direct-mode
token-shunt contamination, or foreign hooks. Results and the required
parent-token measurements (`parent_input_tokens` breakdown,
`parent_output_tokens`) land in `evals/compare/last-run.json`.
Each invocation keeps its manifest, verdicts, and transcripts in a fresh
`evals/compare/tmp/runs/run.*` directory. Model-visible references and targets
are restored before every mode; evidence stays outside that reset directory.
The aggregate requires all planned results and comparison evidence. A selected
case or suite can pass without being a complete release evaluation; check
`release_eligible` separately from `selected_run_valid` in the aggregate.
Parent input, child usage, and combined estimated USD are separate
metrics; do not treat body-byte cuts as token savings.

`scripts/doctor.sh` checks jq, prints `claude --version` when present, warns
if `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1`, notes whether agents registered on
the plugin-load stream, and explains how to confirm `agent_type` on the hook
stdin. A missing live dump is not a doctor failure.
