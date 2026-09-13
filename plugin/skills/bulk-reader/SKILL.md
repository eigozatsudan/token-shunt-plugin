---
name: bulk-reader
description: Use when a Read or Bash hook blocked an oversized file or the needed I/O exceeds the small-task budget. Keep small targeted reads in the parent; file count alone is not a trigger. Do not use for debugging, architectural decisions, or edits that need exact contents in the parent context. Do not @-mention large files.
---

# bulk-reader

Interpret --worker-model auto|haiku|sonnet before any Agent invocation.
Default: auto. Reject unknown values before starting a worker.
For delegated work, invoke Agent(subagent_type="token-shunt:bulk-reader"
or "token-shunt:code-writer", model="haiku"|"sonnet", prompt=...)
according to --worker-model. auto starts with haiku.

Examples:

```text
/token-shunt:bulk-reader --worker-model auto /abs/a.rb /abs/b.rb --question "設定値と定義元を確認"
/token-shunt:bulk-reader --worker-model sonnet /abs/a.rb --question "設定値を確認"
```

## Fixed procedure

1. **Small-task check first (§26.2).** If the explicitly named files or
   the known needed ranges total <= 16384 bytes **and** each targeted
   Read would pass the Read hook (§9), answer directly in the parent —
   do not delegate. The 16384-byte bound applies to both cases. A few
   known lines on a large file (still under 16384 bytes) use parent
   targeted Read; a known range over 16384 bytes is delegated even if
   the hook would pass. Do not recover a full file via sequential
   in-budget targeted Reads. Judge size from metadata only (`stat`/
   `wc -c` via Bash, never `cat`/`head`/`tail`/`less`/`more`, never Read
   the body to size it up). File count alone is not a trigger. A denied
   full Read, a range-unknown full read over budget, or files over the
   small-task budget → delegate.

2. **Delegation prompt.** Contains only: the question, the explicit paths
   to read, and a short diagnosis. Never read or paste file bodies into it.
   `subagent_type` is exactly `token-shunt:bulk-reader` — never Explore,
   never a bare `bulk-reader`. Always pass `model` per --worker-model
   (auto starts with haiku).

3. **Batching.** One invocation = at most 3 explicit paths. Questions about
   relationships between files MUST pass those paths in the same invocation
   (the child sees the relationship in one context; do not stitch per-file
   partials into a guessed answer). 4+ paths → split into batches of 3 per
   invocation and integrate the short answers per the inter-batch evidence
   contract below. Requests that would exceed 4 total invocations (incl.
   retries and boundary checks; up to 12 paths when only new paths are
   read) must ask the user to narrow scope BEFORE starting — do not accept
   and truncate into partial.

   **Inter-batch evidence contract:** file-count splitting alone does not
   guarantee answer quality. Instruct each child to return, within its
   4000-char budget, the source paths / symbols / referenced identifiers the
   question needs. Integrate only facts you can corroborate. Do not mark a
   relationship `confirmed` from name similarity or call-target guesses. If
   a relationship is missing or ambiguous, you may — at most once per
   question — run a boundary-check invocation that explicitly names the
   boundary files to the child (each invocation still reads each path at
   most once). If still unverifiable, mark the relationship `unconfirmed`
   and report the parent result as partial. Distinguish aggregating
   independent facts from questions that require comparing bodies across
   batches. partial never counts as a correct-answer success.

4. **Child contract.** The child reads each specified path at most once
   (<=3 Reads total), does not explore related files, does not Grep/Glob/
   resume, and answers only the question. If the specified paths are
   insufficient it reports the shortage; deciding which paths to add is a
   separate parent task, not an auto-exploration loop.

5. **Follow-ups.** Re-ask in a NEW invocation re-sending the same explicit
   paths. No resume, no answer index. The re-input is paid and counts in
   cost accounting.

6. **Edit contract (§11.6).** Position authority is the parent's Grep
   (short unique pattern, line numbers, limited output) or an already
   verified known range — never the child's line numbers verbatim. If Grep
   matches multiple times, narrow it; if it cannot be made unique, do not
   edit. Then Read(offset, limit) the original, confirm hook pass + tool
   success + actual target text, and only then Edit. Never Edit from
   PARTIAL/elided output. `limit=1` can still fail (single line over
   MIN_BYTES, scan budget, official Read cap). If it fails, report the
   uneditable range. Do not work around with byte-spans, dd+temp, or
   unread-Edit exceptions. `head -c` / `tail -c` remain viewing-only;
   v0.1 edits require a successful targeted Read of the original. Do
   not use Bash viewing as the edit-path original.

7. **Explore denied by hooks:** if a hook denied a Read inside Explore or
   another agent, the PARENT invokes this skill — do not ask Explore to
   retry the large read.

## Model escalation

- auto: first attempt haiku. Escalate to sonnet at most once, and only for:
  missing required evidence, a response-contract violation, or a failed
  post-generation verification. Never escalate on confidence alone.
- Escalation retry carries the original question, the same explicit paths,
  and a short note on what was missing. It does not carry the haiku
  transcript; the child re-reads the same files (both attempts are billed).
- No escalation on: unspecified dependencies, Read/context limits, budget
  exhaustion, auth/permission errors, missing references, unsupported
  model. Report those as partial.
- Shared cap: Agent invocations for one user question (both workers,
  batches, boundary checks, retries) total at most 4. The cap also binds
  after work has started: once it is reached, do not escalate and do not
  start another batch — report partial plus the unfinished paths and
  range. Do not bypass via another agent name or resume.
