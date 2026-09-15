"""Pull the retention checks' inputs out of a real session transcript.

A real session is shaped nothing like the evaluation harness's stream-json:
it carries no `isSidechain` rows and no `parent_tool_use_id`. A worker's
answer reaches the parent as a `user` entry holding a `<task-notification>`
block, and the worker's own transcript sits beside the session file:

    <project>/<session-id>.jsonl                  the parent
    <project>/<session-id>/subagents/agent-<id>.jsonl   each worker
    <project>/<session-id>/subagents/agent-<id>.meta.json

The notification's `<output-file>` is not the worker's answer: it is that
worker's session jsonl, the same content as the `subagents/` file.

Two encodings must be undone before the notification text can be compared
with anything: the body is XML-escaped, and the harness may prepend a
notice (a turn-limit PARTIAL warning, a neutralized-control-tags note).
Where the two sources disagree for any other reason, this module refuses to
guess and reports the worker output as unavailable, so the checks return
undetermined rather than blaming the parent.
"""
import glob
import html
import json
import os
import re

TASK_NOTE = '<task-notification>'
_TAG = {k: re.compile(r'<%s>(.*?)</%s>' % (k, k), re.S)
        for k in ('task-id', 'tool-use-id', 'output-file', 'status', 'result')}
# Harness notices prepended to a result. Their presence means the body is
# not simply the worker's text.
_PARTIAL = re.compile(r'PARTIAL output|stopped at its \d+-turn limit')
_NEUTRALIZED = re.compile(r'^\[harness:[^\]]*\]\s*', re.S)


def read_jsonl(path):
    rows = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue          # a partially flushed tail is not fatal
    return rows


def _tag(text, name):
    m = _TAG[name].search(text or '')
    return m.group(1) if m else None


def _content(entry):
    return (entry.get('message') or {}).get('content')


def notifications(rows):
    """Every task notification in issue order, parsed."""
    out = []
    for entry in rows:
        body = _content(entry)
        if entry.get('type') != 'user' or not isinstance(body, str):
            continue
        if TASK_NOTE not in body:
            continue
        out.append({'agent_id': _tag(body, 'task-id'),
                    'tool_use_id': _tag(body, 'tool-use-id'),
                    'output_file': _tag(body, 'output-file'),
                    'status': _tag(body, 'status'),
                    'result': _tag(body, 'result'),
                    'raw': body})
    return out


def agent_tool_uses(rows):
    """Agent launches the parent made, keyed by tool_use id."""
    out = {}
    for entry in rows:
        if entry.get('type') != 'assistant':
            continue
        for block in _content(entry) or []:
            if isinstance(block, dict) and block.get('type') == 'tool_use' \
                    and block.get('name') in ('Agent', 'Task'):
                out[block.get('id')] = block.get('input') or {}
    return out


def worker_final_text(path):
    """The last text block a worker emitted in its own transcript."""
    last = None
    for entry in read_jsonl(path):
        if entry.get('type') != 'assistant':
            continue
        for block in _content(entry) or []:
            if isinstance(block, dict) and block.get('type') == 'text':
                last = block.get('text')
    return last


def _clean_result(result):
    """Unescape a notification body and strip harness notices.

    Returns (text, partial). `partial` marks output the harness itself
    labelled incomplete.
    """
    if result is None:
        return None, False
    partial = bool(_PARTIAL.search(result))
    text = _NEUTRALIZED.sub('', html.unescape(result))
    if partial:
        text = '\n'.join(line for line in text.splitlines()
                         if not _PARTIAL.search(line)).strip()
    return text, partial


def launches(session_path, agent_type=None):
    """Correlate notification, worker transcript and meta for each launch.

    `agent_id` ties all three together: it is the notification's `task-id`,
    the `subagents/agent-<id>.jsonl` basename, and the name of the
    `<output-file>`. `tool_use_id` ties that back to the parent's own Agent
    call, which is what `.meta.json` records.
    """
    rows = read_jsonl(session_path)
    base = session_path[:-6] if session_path.endswith('.jsonl') \
        else session_path
    tool_uses = agent_tool_uses(rows)
    by_agent = {}
    for note in notifications(rows):
        # A notification with no task-id names no launch and cannot be
        # correlated with anything; ignoring it is not a silent drop of
        # worker output, since its result has no owner.
        if note['agent_id']:
            by_agent.setdefault(note['agent_id'], []).append(note)

    found = {}
    for meta_path in sorted(glob.glob(os.path.join(base, 'subagents',
                                                   'agent-*.meta.json'))):
        agent_id = os.path.basename(meta_path)[len('agent-'):-len('.meta.json')]
        try:
            with open(meta_path, encoding='utf-8') as fh:
                meta = json.load(fh)
        except (OSError, json.JSONDecodeError):
            meta = {}
        found[agent_id] = meta
    # A worker may notify without leaving a meta file, and vice versa.
    for agent_id in by_agent:
        found.setdefault(agent_id, {})

    out = []
    for agent_id, meta in sorted(found.items(), key=lambda kv: kv[0]):
        notes = by_agent.get(agent_id) or []
        # Progress notifications share the agent id with the final one; only
        # a completed notification carries the answer the parent acted on.
        final_note = next((n for n in reversed(notes)
                           if n['status'] == 'completed' and n['result']), None)
        transcript = os.path.join(base, 'subagents', 'agent-%s.jsonl' % agent_id)
        transcript = transcript if os.path.isfile(transcript) else None
        tool_use_id = meta.get('toolUseId') or (notes[0]['tool_use_id']
                                                if notes else None)
        rec = {'agent_id': agent_id,
               'tool_use_id': tool_use_id,
               'agent_type': meta.get('agentType'),
               'launch_input': tool_uses.get(tool_use_id),
               'transcript': transcript,
               'output_file': final_note['output_file'] if final_note else None,
               'notifications': len(notes),
               'status': final_note['status'] if final_note
                         else (notes[-1]['status'] if notes else None)}
        rec.update(_reconcile(final_note, transcript))
        out.append(rec)
    if agent_type is not None:
        out = [r for r in out if r['agent_type'] == agent_type]
    return out


def _reconcile(final_note, transcript):
    """Compare the two copies of a worker's answer.

    'complete'      both agree (or only one exists and carries no warning)
    'partial'       the harness marked the output incomplete
    'mismatch'      the copies differ for an unexplained reason
    'unavailable'   neither source produced text
    """
    noted, partial = _clean_result(final_note['result'] if final_note else None)
    written = worker_final_text(transcript) if transcript else None
    if partial:
        # The worker stopped early, so what the parent received is not the
        # answer it was owed. Retention cannot be judged against it.
        return {'text': None, 'completeness': 'partial',
                'detail': 'harness marked the worker output incomplete'}
    if noted is None and written is None:
        return {'text': None, 'completeness': 'unavailable',
                'detail': 'no notification result and no worker transcript'}
    if noted is None:
        return {'text': written, 'completeness': 'transcript_only',
                'detail': 'no completed notification carried a result'}
    if written is None:
        return {'text': noted, 'completeness': 'notification_only',
                'detail': 'worker transcript missing or empty'}
    if noted.strip() == written.strip():
        return {'text': written, 'completeness': 'complete', 'detail': ''}
    return {'text': None, 'completeness': 'mismatch',
            'detail': 'notification (%d chars) and worker transcript (%d) '
                      'differ' % (len(noted), len(written))}


# Anything that interrupts a run of assistant text: the parent's own tool
# call, its result, or a worker reporting back.
def _is_interruption(entry):
    if entry.get('type') == 'user':
        body = _content(entry)
        if isinstance(body, str):
            return TASK_NOTE in body or not entry.get('isMeta')
        return any(isinstance(b, dict) and b.get('type') == 'tool_result'
                   for b in body or [])
    if entry.get('type') == 'assistant':
        return any(isinstance(b, dict) and b.get('type') == 'tool_use'
                   for b in _content(entry) or [])
    return False


def final_answer(session_path):
    """The text the parent ended its turn with.

    Not simply the last assistant text: a parent narrates between tool calls
    ("the worker is reading the three files now") and those lines are not the
    answer. Only the run of assistant text after the last interruption
    counts. When no such run exists the answer cannot be identified, and
    that is reported rather than approximated.

    `no_final_text` says only that: the final answer was not identifiable.
    It is not a claim about why the turn ended. A transcript's tool sequence
    does not distinguish an interrupted turn from one the CLI ended on a
    tool result, an MCP end-turn or a loop tick -- the endings whose
    Stop-hook block is discarded -- so the two must not be equated here.
    """
    return final_answer_from_rows(read_jsonl(session_path))


def final_answer_from_rows(rows):
    """final_answer() on rows already in hand.

    Note for hook callers: a Stop hook runs before the message ending the
    turn reaches the session file, so these rows do not yet contain it. The
    Stop input's `last_assistant_message` is the source there.
    """
    cut = -1
    for i, entry in enumerate(rows):
        if _is_interruption(entry):
            cut = i
    texts = []
    for entry in rows[cut + 1:]:
        if entry.get('type') != 'assistant' or entry.get('isSidechain'):
            continue
        for block in _content(entry) or []:
            if isinstance(block, dict) and block.get('type') == 'text' \
                    and block.get('text'):
                texts.append(block['text'])
    if not texts:
        return {'text': None, 'status': 'no_final_text',
                'detail': 'the turn ended without assistant text after the '
                          'last tool result or worker report'}
    return {'text': '\n'.join(texts), 'status': 'ok', 'detail': ''}


def check_inputs(session_path, agent_type='token-shunt:bulk-reader'):
    """Worker texts and final answer, or None where they cannot be had."""
    runs = launches(session_path, agent_type=agent_type)
    usable = [r for r in runs if r['text'] is not None]
    blocked = [r for r in runs if r['text'] is None]
    final = final_answer(session_path)
    return {'launches': runs,
            'child_texts': [r['text'] for r in usable] if usable and not blocked
                           else None,
            'child_detail': '; '.join('%s: %s' % (r['agent_id'][:8], r['detail'])
                                      for r in blocked),
            'final': final['text'] if final['status'] == 'ok' else None,
            'final_detail': final['detail']}
