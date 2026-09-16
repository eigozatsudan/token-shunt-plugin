---
name: bulk-reader
description: Judge size from metadata (stat/wc -c) before the first Read or content search, never from the body. Then route: delegate when the needed I/O — the whole file when all of it is needed, otherwise the sum of the known ranges — exceeds 16384 bytes; keep known ranges totaling at most 16384 bytes in the parent when each targeted Read passes the hook. Not needed when the deny already carries the call spec — follow it and delegate. Also use for explicit delegation with no hook deny, how to batch (4+ paths) and cross-file relationships, ambiguity between confirmed/unconfirmed evidence, and retry or escalation after partial. After the metadata check: needed range unknown and over budget -> delegate before any content search. Grep output_mode=content on one over-budget file is hooked (size known first, then head_limit 1-20); a directory or glob search is not hooked; never use it to fetch the answer or to discover a range and claim the known-range exception. Ranges known in advance and within budget stay in the parent; position-only search for the edit contract is unchanged. Copy each worker `confirmed:` line into the final answer verbatim, one per line; collapse only identical lines; a line whose path is not absolute keeps its text but becomes `unconfirmed:`. Resolve auto to haiku before calling Agent; never pass "auto". Not for debugging, architecture, or edits needing exact parent context. Do not @-mention large files.
---

# bulk-reader

Copy a worker's final `status:` and `stop_reason:` verbatim as separate
plain lines — no bold, backticks, or prose summary. Preserve
source-scoped unconfirmed items and unread ranges.

`--worker-model auto|haiku|sonnet` selects the worker model; unspecified
or `auto` resolves to haiku — the literal string `auto` never reaches
Agent.

1. **Small-task check first (§26.2).** If the named files or known
   needed ranges total <= 16384 bytes, **and** each targeted Read would
   pass the Read hook (§9), answer directly — do not delegate. Do not
   recover a full file via sequential in-budget Reads. Judge size from
   metadata only (`stat`/`wc -c` via Bash, never `cat`/`head`/`tail`/
   `less`/`more`, never Read the body to size it up). File count alone
   is not a trigger. A denied full Read, a range-unknown read over
   budget, or a needed size over 16384 bytes → delegate, even a
   16385-byte file the hook would allow to Read.

   **Route before searching (§26.5).** Decide the route from metadata
   *before* running a content search. On a single file already over
   budget, Grep `output_mode=content` is hooked: the size has to be known
   first, then the bound below. A directory, a `glob` set or a bare
   search is not hooked, and neither are `-o`, `head -c`, ... — those can
   still pull body text out of an oversized file and make routing moot.
   Don't content-search for the answer — delegate, and let the child
   read. Content search there stays allowed only to establish
   *positions* for the §11.6 edit contract or confirm a known range,
   with `files_with_matches`, or `content` with `head_limit`
   1-20 and no `-A`/`-B`/`-C`/`context`. After a denied Read, never
   recover the answer through Bash, Grep, or smaller parent Reads;
   follow-ups go to a new bounded worker call, and parent Reads stay
   reserved for the edit contract in step 4.

2. **Batching.** One invocation = at most 3 explicit paths. Relationship
   questions across files MUST pass those paths in the same invocation
   (one context; do not stitch per-file partials into a guessed answer).
   4+ paths → split into batches of 3 and integrate per the evidence
   contract below. Requests exceeding 4 total invocations (incl. retries
   and boundary checks; up to 12 paths when only new paths are read)
   must ask the user to narrow scope BEFORE starting — do not accept
   and truncate into partial.

   **Inter-batch evidence contract:** splitting by file count alone does
   not guarantee answer quality. Instruct each child to return, within
   its 4000-char budget, the source paths/symbols/identifiers the
   question needs. Integrate only corroborated facts; do not mark a
   relationship `confirmed` from name similarity or call-target guesses.
   If a relationship is missing or ambiguous, you may — at most once —
   run a boundary-check invocation naming the boundary files (each
   region still read at most once). If still unverifiable, mark it
   `unconfirmed` and report the result as partial. partial never
   counts as success.

3. **Follow-ups.** Re-ask in a NEW invocation with the same
   explicit paths. No resume, no answer index; the re-input is paid.
   The same holds when a worker stops without a report (turn limit,
   error, empty return): ask again in a NEW invocation with the same
   explicit paths, which counts against the shared cap of 4. Once the
   cap is reached, report partial with the paths you could not confirm.
   A stopped worker is never resumed or messaged.

4. **Edit contract (§11.6).** Position authority is the parent's Grep
   (short unique pattern, line numbers, limited output; over budget, the
   §26.5 form, not one line back) or an already
   verified known range — never the child's line numbers verbatim. If
   Grep matches multiple times, narrow it; if it can't be made unique,
   don't edit. Then Read(offset, limit) the original, confirm hook pass
   + tool success + actual target text, and only then Edit — never from
   PARTIAL/elided output. `limit=1` can still fail (single line over
   MIN_BYTES, scan budget, Read cap); if it fails, report the uneditable
   range instead of byte-spans, dd+temp, or unread-Edit workarounds.
   `head -c`/`tail -c` stay viewing-only; edits require a successful
   targeted Read of the original.

5. **Explore denied by hooks:** if a hook denied a Read inside Explore
   or another agent, the PARENT invokes this skill — don't ask Explore
   to retry the large read.

## Model escalation

- auto: first attempt haiku. Escalate to sonnet at most once, only for
  missing required evidence, a response-contract violation, or a failed
  post-generation verification — never on confidence alone. A
  suggestive function name isn't grounds to escalate.
- The retry carries the original question, same paths/metadata, the
  response contract, and `retry_reason:` (`missing required evidence` /
  `response contract violation` / `verification failed`) plus the
  concrete failure. It re-reads the same files; no transcript carries.
- No escalation on: unspecified dependencies, Read/context limits,
  budget exhaustion, auth/permission errors, missing references,
  unsupported model — report those as partial.
- Shared cap: Agent invocations for one question (workers, batches,
  boundary checks, retries) total at most 4. Once reached, report
  partial plus the unfinished paths — don't bypass via another agent
  name or resume.

## Explicit delegation (no hook deny)

Read `${CLAUDE_PLUGIN_ROOT}/hooks/reader-call-contract`, substitute
`{REASON}` with `Explicit delegation (no hook deny)` and `{PATHS}` with
the target paths and their sizes, then call Agent exactly as that
contract specifies. Write `(size unknown)` for any path whose size you
don't already have; don't run metadata commands just to get a size.

## Out of scope in v0.1

Several small files, each under the hook thresholds, can still total
over 16384 bytes without firing a deny. v0.1 does not auto-delegate
that; delegate through this skill only when the parent decides it's
needed.
