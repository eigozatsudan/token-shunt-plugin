# Evaluation presentation fixes and reader runtime contract

B: The evaluator normalizes whole-line bold, inline-code wrapping, and bullet
markers before reading explicit status fields. Missing or duplicate status
fields still fail. An empty confirmed label is not a factual claim; unreadable
credit still requires a native one-line Read refusal, a source-scoped unconfirmed
item, and the unread line. Table status cells may include an em-dash explanation.
The parent skill now requests verbatim plain-line field preservation.

D: Direct prompts that previously said “Read the file and answer” now explicitly
require the Read tool and consecutive ranges when needed. This is a mechanism
baseline, not a measurement of unconstrained tool selection.

C: check-reader-contract uses PreToolUse, PostToolUse, and PostToolUseFailure.
A private per-user temporary directory stores metadata keyed by session and
agent ID. An exclusive file lock protects six shared attempts, the in-flight
Read, and per-path cursor/retry limits. Denied attempts consume budget; successful
native Read startLine/numLines/totalLines advance the cursor. Unknown endpoints
stop continuation. A token-cap refusal keeps the cursor and requires floor-half
retry. Whole-file refusal counts at most 8 MiB to determine that retry; larger
unknown ranges stop. The initial cursor is line 1. This implementation does not
initialize a non-1 cursor from a parent-declared region; callers must begin at 1.
It enforces at most three accessed paths, but does not parse the parent prompt
to authorize those paths. Existing evaluator checks still enforce declarations.

Requirements: Unix Python 3 with fcntl, in addition to existing Bash/jq.
maxTurns is not the Read budget. State has no source content and persists until
the OS temporary directory is cleaned. Missing agent identity or unusable state
fails closed; actual CLI integration remains to be validated.

Validation:
- Comparison evaluator: 215 tests passed (before removing three duplicate imported
  tests; the three presentation tests passed again after that cleanup).
- Hooks and packaging: 71 tests passed, including an eight-process concurrent
  request test, cross-file shared budget, partial-result cursor, floor-half,
  limit-one refusal, and independent-agent isolation.
- Skill validator, shell syntax check, diff whitespace check, ZIP build passed.

Live evaluation is BLOCKED, not passed. The sandbox attempt encountered API
connection retries and was interrupted. The permitted network attempt stopped
at both preflight probes with “You've hit your session limit · resets 3am
(Asia/Tokyo)”. Evidence: evals/compare/tmp/runs/run.gbtgHtj8/transcripts/.
No changed-plugin model run completed, so no improvement rate is claimed.

After the limit clears, run `bash evals/compare/repeat.sh 2`. It schedules all
30 cases / 75 configured case-mode pairs twice, retaining separate logs and
aggregates under evals/compare/tmp/repeats/. It stops early on environmental
failure and returns failure if either completed run fails.
