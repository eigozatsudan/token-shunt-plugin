"""State the retention rule at the moment a worker is launched.

A parent that received three absolute paths wrote three basenames
(reviews/a-suite-failures-9346d19-2026-09-16.md section 1). The send-back
repairs that, but only afterwards and only while it is on, and the rule
itself is stated where the parent is furthest from using it: in the skill
it loaded, and in the deny that started the delegation -- a deny that an
explicitly delegated call never sees at all.

The worker's report reaches the parent as a `<task-notification>`, which
no hook event observes (reviews/stop-hook-spec-2026-09-15.md section 1),
so the launch is the last point at which anything can be said before the
answer is written. PostToolUse is the event this CLI turns
`additionalContext` into a message on; PreToolUse accepts the field in its
schema but delivers nothing, so the reminder rides the launch result
rather than `check-agent-model`.

This prevents; it does not judge. Whether the parent actually kept the
lines is check-final-answer's question.
"""
import json
import sys

WORKERS = ('token-shunt:bulk-reader', 'token-shunt:code-writer')
TOOLS = ('Agent', 'Task')

REMINDER = (
    "this worker returns `confirmed: <absolute path> — <fact>` lines. "
    "Copy each one into your final answer verbatim, one per line, keeping "
    "the full absolute path unabbreviated — never shorten it to a "
    "basename or a relative path, and never replace the lines with a "
    "summary. Collapse only identical lines. A line whose path is not "
    "absolute keeps its text but becomes `unconfirmed:`. This is "
    "addressed to you, not to the worker: do not copy it into a prompt."
)


def launched(response):
    """Did this call actually start a worker?

    PostToolUse also fires for a call the tool refused, and a launch that
    never happened has no report to retain. An unrecognised response shape
    is treated as a launch: the reminder costs a sentence, and staying
    silent on the real case is the failure being fixed.
    """
    if isinstance(response, dict):
        return not response.get('error')
    if isinstance(response, str):
        return 'error' not in response.lower()
    return True


def decide(event):
    """The reminder for this launch, or None if it is not ours."""
    if event.get('tool_name') not in TOOLS:
        return None
    inp = event.get('tool_input')
    if not isinstance(inp, dict):
        return None
    if inp.get('subagent_type') not in WORKERS:
        return None
    if not launched(event.get('tool_response')):
        return None
    return REMINDER


def main(stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    try:
        event = json.load(stdin)
    except (json.JSONDecodeError, ValueError):
        return 0                   # never fail a turn over a reminder
    if not isinstance(event, dict):
        return 0
    try:
        note = decide(event)
    except Exception:
        return 0
    if note:
        json.dump({'hookSpecificOutput': {
            'hookEventName': 'PostToolUse',
            'additionalContext': 'token-shunt: ' + note}}, stdout)
    return 0


if __name__ == '__main__':
    sys.exit(main())
