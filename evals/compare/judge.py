#!/usr/bin/env python3
"""token-shunt compare-eval transcript judge (design §13, §26.5).

Reads one stream-json transcript plus a case spec and emits a verdict JSON:
accuracy / path_ok / isolation_ok + metrics. Exits non-zero on contract
failures so the runner can stop the release.
"""
import json
import os
import re
import shlex
import sys

from routing_checks import (check_reader_reads, check_routing, unreadable_line_partial,
                            rejected_model_launch, reader_attempt_metrics, metadata_only_bash)
from report_text import plain_report
from flow_checks import edit_flow_errors, position_grep_errors, verification_errors

COMPARE_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURES_DIR = os.environ.get("TOKEN_SHUNT_EVAL_FIXTURES", os.path.join(COMPARE_DIR, "fixtures"))

READ_TOOLS = {"Read"}
BODY_TOOLS = {"cat", "head", "tail", "less", "more"}
TS_HOOKS = ("check-file-size", "check-bash-read", "check-jq", "check-agent-model",
            "check-reader-contract", "check-final-answer", "check-grep-bounds")
# Observed bootstrap matcher; the name alone cannot establish provenance.
BUILTIN_HOOKS = {"SessionStart:startup"}
# This CLI reports only the matcher in `hook_name` ("PreToolUse:Read"), never
# the command path, so token-shunt's own hooks cannot be recognised by name
# (design §13). Foreign hooks are identified by the isolation contract instead:
# a delegate run loads token-shunt and nothing else, so these are the only
# hook responses it may produce. See `foreign_hooks` for the residual gap.
TS_HOOK_NAMES = {"PreToolUse:Read", "PreToolUse:Bash", "PreToolUse:Agent",
                 "PreToolUse:Task", "PreToolUse:Agent|Task",
                 "PreToolUse:Grep", "PostToolUse:Read", "PostToolUse:Bash",
                 "PostToolUseFailure:Read", "Stop", "SubagentStop"}
AGENT_TOOL_NAMES = {"Agent", "Task"}


def token_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def requires_parent_tokens(spec, mode):
    value = spec.get("require_parent_tokens")
    return value is True or (isinstance(value, list) and mode in value)


def spec_evidence_error(spec):
    requirement = spec.get("require_parent_tokens")
    if (requirement is not None and not isinstance(requirement, bool)
            and not (isinstance(requirement, list)
                     and all(isinstance(mode, str) and mode in {"direct", "auto", "haiku", "sonnet"}
                             for mode in requirement))):
        return "require_parent_tokens must be a boolean or list of modes"
    if "gold_file" in spec:
        if not isinstance(spec["gold_file"], str) or not spec["gold_file"].strip():
            return "gold_file must be a nonempty path string"
        gold = spec.get("gold")
        if not isinstance(gold, list) or not gold or not all(isinstance(g, str) and g for g in gold):
            return "declared gold_file requires a nonempty list of gold strings"
    return None


def validate_tool_inputs(events):
    """Reject malformed model-controlled arguments before evidence consumers run.

    Keep the original input intact: coercing invalid arguments to empty values
    can turn a malformed attempt into successful or absent evidence.
    """
    string_fields = {
        "Read": ("file_path", "path"), "Bash": ("command",),
        "Agent": ("subagent_type", "agent_type", "type", "prompt", "model", "resume"),
        "Task": ("subagent_type", "agent_type", "type", "prompt", "model", "resume"),
        "Edit": ("file_path", "path", "old_string", "new_string"),
        "Write": ("file_path", "path", "content"),
        "Grep": ("pattern", "path", "glob", "type", "output_mode"),
        "Glob": ("pattern", "path"),
    }
    for index, event in enumerate(events):
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            location = "event %d tool %r (%r)" % (index + 1, block.get("id"), name)
            if "id" in block and not isinstance(block["id"], str):
                raise ValueError(location + ": id must be a string")
            if not isinstance(name, str):
                raise ValueError(location + ": name must be a string")
            inp = block.get("input", {})
            if not isinstance(inp, dict):
                raise ValueError(location + ": input must be an object")
            for field in string_fields.get(name, ()):
                if field in inp and not isinstance(inp[field], str):
                    raise ValueError(location + ": input." + field + " must be a string")
            if name == "Read":
                for field in ("offset", "limit"):
                    if field in inp and (type(inp[field]) is not int or inp[field] < 1):
                        raise ValueError(location + ": input." + field + " must be a positive integer")


def load_events(path):
    events = []
    with open(path, encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("event must be an object")
                events.append(value)
            except ValueError as exc:
                raise ValueError("invalid transcript line %d: %s" % (number, exc)) from exc
    return events


def text_of(content):
    """Extract printable text from a message content list or string."""
    if isinstance(content, str):
        return content
    out = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    out.append(b.get("text", ""))
                elif b.get("type") == "tool_result":
                    out.append(text_of(b.get("content")))
    return "\n".join(out)


def input_text(value):
    """Stable structural rendering; string values retain literal Unicode/newlines.

    This is a context-size representation, not JSON for round-trip parsing.
    Keeping values literal lets the same text support body-leak checks.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + input_text(value[k])
                              for k in sorted(value)) + "}"
    if isinstance(value, list):
        return "[" + ",".join(input_text(v) for v in value) + "]"
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def unittest_arguments(command):
    """Parse a literal unittest call, optionally after a single cd."""
    if any(c in command for c in ('\n', '`', '$', '<', '>')):
        return None
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|()')
        lexer.whitespace_split = True
        argv = list(lexer)
    except ValueError:
        return None
    if len(argv) >= 3 and argv[0] == 'cd' and argv[2] == '&&':
        argv = argv[3:]
    if (len(argv) < 3 or argv[0] not in ('python', 'python3')
            or argv[1:3] != ['-m', 'unittest']
            or any(token and all(c in ';&|()' for c in token) for token in argv[3:])):
        return None
    return argv[3:]


def unittest_targets(argv):
    """Extract test names or discovery patterns, excluding option values."""
    discovery = bool(argv and argv[0] == 'discover')
    args = argv[1:] if discovery else argv
    targets = []
    positionals = []
    i = 0
    while i < len(args):
        arg = args[i]
        option, sep, value = arg.partition('=')
        if option in ('-s', '--start-directory', '-t', '--top-level-directory',
                      '-p', '--pattern', '-k'):
            if not sep:
                i += 1
                if i >= len(args):
                    return []
                value = args[i]
            if discovery and option in ('-p', '--pattern'):
                targets[:] = [value]
        elif arg.startswith(('-s', '-t', '-p', '-k')) and not arg.startswith('--') and len(arg) > 2:
            if discovery and arg.startswith('-p'):
                targets[:] = [arg[2:]]
        elif arg in ('-v', '--verbose', '-q', '--quiet', '-f', '--failfast',
                     '-c', '--catch', '-b', '--buffer', '--locals'):
            pass
        elif arg.startswith('-'):
            return []
        else:
            positionals.append(arg)
        i += 1
    if discovery:
        # unittest discover [start-directory [pattern [top-level-directory]]]
        if len(positionals) > 3 or (targets and len(positionals) >= 2):
            return []
        if len(positionals) >= 2:
            targets.append(positionals[1])
    else:
        targets.extend(positionals)
    return targets


def parent_bash_contains(command, needle, require_unittest=False):
    """Match unittest evidence against executable arguments, not comments."""
    argv = unittest_arguments(command)
    if needle in ("python -m unittest", "python3 -m unittest"):
        return argv is not None
    if argv is not None or require_unittest:
        if argv is None:
            return False
        # A case's module stem may also be a .py path or a dotted test name.
        return any(needle == target or needle in os.path.basename(target).removesuffix('.py').split('.')
                   for target in unittest_targets(argv))
    return needle in command


class Transcript:
    def __init__(self, events):
        validate_tool_inputs(events)
        self.events = events
        self.init = next((e for e in events if e.get("type") == "system"
                          and e.get("subtype") == "init"), {})
        self.parent_results = []
        seen_results = set()
        for e in events:
            if e.get("type") != "result" or e.get("parent_tool_use_id") is not None:
                continue
            uid = e.get("uuid")
            if uid and uid in seen_results:
                continue
            if uid:
                seen_results.add(uid)
            self.parent_results.append(e)
        self.result = self.parent_results[-1] if self.parent_results else {}
        self.tool_uses = []      # {id,name,input,parent_tool_use_id,msg_id,model}
        self.tool_results = {}   # tool_use_id -> {content_text,is_error,parent_tool_use_id}
        self.hook_events = []    # hook_started/hook_response
        self.assistant_msgs = [] # {id,model,text,parent_tool_use_id}
        self.user_msgs = []      # parent-level user/tool_result messages
        for event_index, e in enumerate(events):
            t = e.get("type")
            ptid = e.get("parent_tool_use_id")
            if t == "system" and e.get("subtype") in ("hook_started", "hook_response"):
                self.hook_events.append(e)
            elif t == "assistant":
                m = e.get("message", {})
                mid = m.get("id")
                text_parts = []
                context_parts = []
                context_blocks = []
                for block_index, b in enumerate(m.get("content", []) or []):
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        block_text = input_text(b.get("input", {}))
                        context_parts.append(block_text)
                        self.tool_uses.append({
                            "id": b.get("id"),
                            "name": b.get("name"),
                            "input": b.get("input", {}),
                            "parent_tool_use_id": ptid,
                            "msg_id": mid,
                            "model": m.get("model"),
                            "position": (event_index, block_index),
                        })
                    elif b.get("type") == "text":
                        block_text = b.get("text", "")
                        text_parts.append(block_text)
                        context_parts.append(block_text)
                    elif b.get("type") == "thinking":
                        block_text = b.get("thinking", "")
                        context_parts.append(block_text)
                    else:
                        continue
                    # API message IDs are shared by distinct content blocks.
                    # Prefer tool identity, then event UUID + block position.
                    # With neither, retain the event rather than guess a replay.
                    if b.get("type") == "tool_use" and b.get("id") and mid:
                        key = ("tool", mid, b["id"])
                    elif e.get("uuid"):
                        key = ("event", e["uuid"], block_index)
                    else:
                        key = ("position", event_index, block_index)
                    context_blocks.append((key, block_text))
                self.assistant_msgs.append({
                    "id": mid, "model": m.get("model"),
                    "text": "\n".join(text_parts), "parent_tool_use_id": ptid,
                    "context_text": "\n".join(context_parts),
                    "context_blocks": context_blocks,
                })
            elif t == "user":
                m = e.get("message", {})
                self.user_msgs.append({"id": m.get("id"), "parent_tool_use_id": ptid,
                                       "message": m})
                for block_index, b in enumerate(m.get("content", []) or []):
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        rec = {
                            "text": text_of(b.get("content")),
                            "is_error": bool(b.get("is_error")),
                            "parent_tool_use_id": ptid,
                            "raw": b,
                            "position": (event_index, block_index),
                            "tool_use_result": e.get("tool_use_result"),
                        }
                        for k in ("resolvedModel", "resolved_model",
                                  "modelsUsed", "models_used"):
                            if k in b:
                                rec[k] = b[k]
                        self.tool_results[b.get("tool_use_id")] = rec

    # ---- queries ----
    def plugins(self):
        return [p.get("name") for p in self.init.get("plugins", []) or []]

    def plugin_errors(self):
        return self.init.get("plugin_errors")

    def agents(self):
        return self.init.get("agents", []) or []

    def skills(self):
        return self.init.get("skills", []) or []

    def parent_tool_uses(self, name=None):
        return [u for u in self.tool_uses
                if u["parent_tool_use_id"] is None
                and (name is None or u["name"] == name)]

    def child_tool_uses(self, agent_use_id, name=None):
        return [u for u in self.tool_uses
                if u["parent_tool_use_id"] == agent_use_id
                and (name is None or u["name"] == name)]

    def all_tool_uses(self, name=None):
        return [u for u in self.tool_uses if name is None or u["name"] == name]

    def result_of(self, tool_use_id):
        return self.tool_results.get(tool_use_id)

    def child_return_of(self, use):
        """Resolve a worker reply, including the CLI's background completion.

        An async launch is only an acknowledgement. The parent-facing completed
        notification carries the returned text; child messages alone do not
        prove delivery to the parent.
        """
        result = self.result_of(use["id"])
        if not result:
            return None
        metadata = result.get("tool_use_result")
        metadata = metadata if isinstance(metadata, dict) else {}
        is_async = (metadata.get("isAsync") is True
                    or metadata.get("status") == "async_launched"
                    or result["text"].startswith("Async agent launched successfully."))
        if not is_async:
            return result
        agent_id = metadata.get("agentId")
        if (not agent_id or result["is_error"]
                or result["parent_tool_use_id"] is not None
                or result["position"] <= use["position"]):
            return None
        for i, event in enumerate(self.events):
            if (event.get("type") == "system"
                    and event.get("subtype") == "task_notification"
                    and event.get("parent_tool_use_id") is None
                    and event.get("tool_use_id") == use["id"]
                    and event.get("task_id") == agent_id
                    and event.get("status") == "completed"
                    and isinstance(event.get("summary"), str)
                    and event["summary"].strip()
                    and (i, 0) > result["position"]):
                return {"text": event["summary"], "is_error": False,
                        "parent_tool_use_id": None, "position": (i, 0)}
        return None

    def agent_uses(self):
        return [u for u in self.all_tool_uses()
                if u["name"] in AGENT_TOOL_NAMES and not rejected_model_launch(self, u)]

    def agent_type_of(self, use):
        i = use["input"]
        return i.get("subagent_type") or i.get("type") or ""

    def final_text(self):
        r = self.result.get("result")
        if isinstance(r, str) and r:
            return r
        texts = [a["text"] for a in self.assistant_msgs
                 if a["parent_tool_use_id"] is None and a["text"]]
        return texts[-1] if texts else ""

    def is_error(self):
        return bool(self.result.get("is_error"))

    # ---- metrics (§13 指標) ----
    def parent_added_text(self):
        seen = set()
        parts = []
        for a in self.assistant_msgs:
            if a["parent_tool_use_id"] is not None:
                continue
            for key, text in a["context_blocks"]:
                if not text or key in seen:
                    continue
                seen.add(key)
                parts.append(text)
        for u in self.user_msgs:
            if u["parent_tool_use_id"] is not None:
                continue
            m = u["message"]
            key = ("u", m.get("id"))
            if m.get("id") and key in seen:
                continue
            seen.add(key)
            parts.append(text_of(m.get("content")))
        # Count only delivered async completions recognized by the same
        # identity/order checks as child-return evidence. Launch text above is
        # also parent context; it is not a substitute for the returned summary.
        for use in self.parent_tool_uses():
            if use["name"] not in AGENT_TOOL_NAMES:
                continue
            reply = self.child_return_of(use)
            if not reply or reply is self.result_of(use["id"]):
                continue
            key = ("completion", use["id"], reply["position"])
            if key not in seen:
                seen.add(key)
                parts.append(reply["text"])
        return "\n".join(parts)

    def metrics(self):
        ptxt = self.parent_added_text()
        parent_usages = [e.get("usage") if isinstance(e.get("usage"), dict) else {}
                         for e in self.parent_results]
        usage = dict(parent_usages[0]) if len(parent_usages) == 1 else {}
        for key in ("input_tokens", "cache_read_input_tokens",
                    "cache_creation_input_tokens", "output_tokens"):
            if not parent_usages or (len(parent_usages) == 1 and key not in usage):
                continue
            values = [u.get(key) for u in parent_usages]
            usage[key] = (sum(values) if values and all(token_count(v) for v in values)
                          else None)
        parent_input = {
            "uncached": usage.get("input_tokens"),
            "cache_read": usage.get("cache_read_input_tokens"),
            "cache_creation": usage.get("cache_creation_input_tokens"),
        }
        if all(v is None for v in parent_input.values()):
            parent_input = None
        models = sorted({a["model"] for a in self.assistant_msgs
                         if a.get("model") and a["model"] != "<synthetic>"})
        return {
            "worker_attempts": [dict(
                tool_use_id=u["id"], agent_type=self.agent_type_of(u),
                launch_rejected=rejected_model_launch(self, u),
                requested_model=u["input"].get("model"),
                **{**reader_fields((self.child_return_of(u) or {}).get("text", "")),
                   "retry_reason": reader_fields(u["input"].get("prompt", ""))["retry_reason"]})
                for u in self.parent_tool_uses() if u["name"] in AGENT_TOOL_NAMES],
            "fallback_reason": reader_fields(self.final_text())["fallback_reason"],
            "stop_reason": reader_fields(self.final_text())["stop_reason"],
            "parent_added_chars": len(ptxt),
            "parent_added_utf8_bytes": len(ptxt.encode("utf-8")),
            "parent_added_tokens_est": len(ptxt.encode("utf-8")) // 4,
            "parent_input_tokens": parent_input,
            "parent_output_tokens": usage.get("output_tokens"),
            "usage_parent": usage or None,
            "usage_tree": self.result.get("modelUsage"),
            "models": models,
            "wall_ms": self.result.get("duration_ms"),
            "total_cost_usd": self.result.get("total_cost_usd"),
        }


def reader_fields(text):
    """Only explicit, unambiguous fields are evidence; never infer a reason."""
    text = plain_report(text)
    result = {}
    for key in ("status", "stop_reason", "fallback_reason", "retry_reason"):
        values = re.findall(r"(?m)^[ \t]*(?:[-*+][ \t]+)?" + key + r":[ \t]*([^\n]+)$", text or "")
        result[key] = values[0].strip() if len(values) == 1 else None
    return result


def norm_path(p, cwd=None):
    """File identity without borrowing the evaluator's working directory.

    Resolve absolute paths before lexical normalization: symlink/.. follows
    the symlink target, not its lexical parent. Unknown relative paths stay
    relative until the recorded tool working directory is available.
    """
    if not isinstance(p, str) or not p:
        return p
    if not os.path.isabs(p) and isinstance(cwd, str) and os.path.isabs(cwd):
        p = os.path.join(cwd, p)
    return os.path.realpath(p) if os.path.isabs(p) else os.path.normpath(p)


def resolve_fixture_path(fp, spec=None):
    """Resolve a fixture path: absolute, fixtures_abs, or compare/fixtures/."""
    if not fp or not isinstance(fp, str):
        return fp
    if os.path.isabs(fp):
        return fp  # Missing absolute paths must not alias another file.
    spec = spec or {}
    rel = os.path.normpath(fp)
    if rel.startswith("fixtures/"):
        rel = rel[len("fixtures/"):]
    if spec.get("fixture_root"):
        return os.path.normpath(os.path.join(spec["fixture_root"], rel))
    aliases = {os.path.realpath(a) for a in spec.get("fixtures_abs") or []
               if isinstance(a, str) and os.path.isabs(a)
               and os.path.normpath(a).endswith("/" + rel)}
    if len(aliases) == 1:
        return aliases.pop()
    if len(aliases) > 1:
        return None  # Ambiguous suffixes are not evidence for either file.
    cand = os.path.join(FIXTURES_DIR, rel)
    if os.path.isfile(cand):
        return cand
    if os.path.isfile(fp):
        return fp
    return fp


def fixture_text(fp, spec=None, cache=None):
    if cache is not None and fp in cache:
        return cache[fp]
    path = resolve_fixture_path(fp, spec)
    canonical = ("file", os.path.realpath(path)) if isinstance(path, str) else None
    body = None
    if cache is not None and canonical in cache:
        body = cache[canonical]
    elif isinstance(path, str):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                body = f.read()
        except (OSError, ValueError):
            body = None
    if cache is not None:
        cache[fp] = body
        if canonical is not None:
            cache[canonical] = body
    return body


def file_nlines(body):
    if not body:
        return 0
    n = body.count("\n")
    if not body.endswith("\n"):
        n += 1
    return n


def is_full_parent_read(use, path, spec=None):
    """No limit (offset-only included) or a limit covering the whole file."""
    inp = use.get("input") or {}
    limit = inp.get("limit")
    if limit in (None, "", 0, "0"):
        return True
    try:
        lim = int(limit)
    except (TypeError, ValueError):
        return True
    body = fixture_text(path, spec)
    if body is None:
        return False
    nlines = file_nlines(body)
    off = inp.get("offset") or 1
    try:
        off = int(off)
    except (TypeError, ValueError):
        off = 1
    if nlines and off <= 1 and lim >= nlines:
        return True
    return False


def deny_bypass_paths(exp):
    paths = []
    db = exp.get("deny_bypass")
    if db is True:
        paths.extend(exp.get("parent_no_full_read") or [])
        dr = exp.get("deny_route") or {}
        if isinstance(dr, dict) and dr.get("path"):
            paths.append(dr["path"])
        if not paths:
            paths.extend(exp.get("child_reads_once") or [])
    elif isinstance(db, dict) and db.get("path"):
        paths.append(db["path"])
    elif isinstance(db, (list, tuple)):
        paths.extend(db)
    dr = exp.get("deny_route") or {}
    if isinstance(dr, dict) and dr.get("path"):
        paths.append(dr["path"])
    out = []
    for p in paths:
        if p and p not in out:
            out.append(p)
    return out


def confirmed_items(text):
    items = []
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"(?i)^[ \t]*[-*]?\s*confirmed:\s*(.*)$", lines[i])
        if m:
            chunk = [m.group(1)]
            i += 1
            while i < len(lines) and lines[i].strip() \
                    and not re.match(
                        r"(?i)^[ \t]*[-*]?\s*(confirmed|inferred|unconfirmed):",
                        lines[i]):
                chunk.append(lines[i])
                i += 1
            items.append("\n".join(chunk))
            continue
        i += 1
    if not items:
        for m in re.finditer(
                r"\bconfirmed:\s*(.+?)(?=\b(?:confirmed|inferred|unconfirmed):|$)",
                text or "", re.I | re.S):
            items.append(m.group(1).strip())
    return items


def gold_path_needles(gold, spec):
    """Only absolute, canonical source paths can establish evidence identity."""
    declared = (spec.get("gold_paths") or {}).get(gold)
    if declared is not None:
        candidates = declared if isinstance(declared, list) else [declared]
    else:
        cache = {}
        candidates = [fp for fp in spec.get("fixtures") or []
                      if (body := fixture_text(fp, spec, cache)) is None or gold in body]
    return list(dict.fromkeys(norm_path(resolve_fixture_path(fp, spec))
                             for fp in candidates if resolve_fixture_path(fp, spec)))


def item_citations(item):
    """The absolute paths an answer item offers as its evidence."""
    citations = re.findall(r"(?<![\w./-])(/[^\s`\"'<>]+)", item)
    citations.extend(re.findall(r"[`\"'](/[^`\"']+)[`\"']", item))
    leading = re.match(r"\s*(/.*?)\s+[—–]\s+", item)
    if leading:
        citations.append(leading[1])
    return {norm_path(re.sub(r":\d+(?::\d+)?$", "", p.rstrip('.,;:)')))
            for p in citations}


def gold_confirmed_ok(final, golds, spec):
    """A gold must have an absolute source citation in the same confirmed item."""
    missing = []
    for gold in golds:
        expected = set(gold_path_needles(gold, spec))
        for item in confirmed_items(final):
            if gold in item and item_citations(item) & expected:
                break
        else:
            missing.append(gold)
    return missing


def gold_confirmed_source(gold, worker_texts, spec):
    """Say where a missing gold was lost: the parent, the worker, or neither.

    One failure name covered three different causes at 9346d19 - the parent
    abbreviating the worker's absolute paths, the worker citing relative ones,
    and the worker leaving the gold in prose
    (reviews/a-suite-failures-9346d19-2026-09-16.md section 1). The reason
    text has to distinguish them, because only the first is a parent defect.
    """
    if not worker_texts:
        return "no worker return"
    expected = set(gold_path_needles(gold, spec))
    named = False
    for text in worker_texts:
        for item in confirmed_items(text):
            if gold not in item:
                continue
            named = True
            if item_citations(item) & expected:
                return "parent dropped the worker's path"
    if named:
        return "worker cited no matching absolute path"
    return "worker never confirmed it"


def artifact_has_level(final, artifact, want):
    names = [artifact, os.path.basename(artifact)]
    idx = -1
    hit = artifact
    for n in names:
        if not n:
            continue
        idx = final.find(n)
        if idx >= 0:
            hit = n
            break
    if idx < 0:
        return False
    window = final[max(0, idx - 220): idx + len(hit) + 220]
    found = re.findall(r"\b(minimal|syntax|requirements)\b", window)
    return want in found


def agent_resolved_models(tr, u):
    models = []
    r = tr.result_of(u["id"]) or {}
    for key in ("resolvedModel", "resolved_model"):
        val = r.get(key)
        if isinstance(val, str) and val:
            models.append(val)
    for key in ("modelsUsed", "models_used"):
        val = r.get(key)
        if isinstance(val, str) and val:
            models.append(val)
        elif isinstance(val, list):
            models.extend(x for x in val if isinstance(x, str))
    raw = r.get("raw") or {}
    for key in ("resolvedModel", "resolved_model"):
        val = raw.get(key)
        if isinstance(val, str) and val:
            models.append(val)
    txt = r.get("text") or ""
    try:
        j = json.loads(txt)
        if isinstance(j, dict):
            rm = j.get("resolvedModel") or j.get("resolved_model")
            if isinstance(rm, str) and rm:
                models.append(rm)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    if not models:
        for a in tr.assistant_msgs:
            if a.get("parent_tool_use_id") == u["id"] and a.get("model") \
                    and a["model"] != "<synthetic>":
                models.append(a["model"])
    out = []
    for m in models:
        if m not in out:
            out.append(m)
    return out


def prompt_of_agent(use):
    inp = use.get("input") or {}
    return json.dumps(inp, ensure_ascii=False)


def use_targets_path(use, path, spec=None):
    """True/False for known identity, None when relative identity lacks cwd."""
    inp = use["input"]
    cwd = (spec or {}).get("tool_cwd")
    absolute_cwd = isinstance(cwd, str) and os.path.isabs(cwd)
    unresolved = False
    for k in ("file_path", "path", "notebook_path"):
        v = inp.get(k)
        if not isinstance(v, str) or not v:
            continue
        if not absolute_cwd and (not os.path.isabs(v)
                                 or not isinstance(path, str) or not os.path.isabs(path)):
            unresolved = True
        elif norm_path(v, cwd) == norm_path(path, cwd):
            return True
    return None if unresolved else False


def writer_reference_paths(spec):
    """Resolve declared references without guessing from a matching basename."""
    refs = list(spec.get("fixtures") or [])
    refs = [p for p in refs if "greeter" in os.path.basename(p)] or refs
    absolute = [p for p in spec.get("fixtures_abs", []) if isinstance(p, str)
                and os.path.isabs(p)]
    resolved = []
    for ref in refs:
        if os.path.isabs(ref):
            resolved.append(norm_path(ref))
            continue
        rel = os.path.normpath(ref)
        if rel.startswith("fixtures/"):
            rel = rel[len("fixtures/"):]
        if spec.get("fixture_root"):
            resolved.append(norm_path(os.path.join(spec["fixture_root"], rel)))
        else:
            matches = [p for p in absolute if os.path.normpath(p).endswith("/" + rel)]
            resolved.append(norm_path(matches[0]) if len(matches) == 1
                            else norm_path(os.path.join(FIXTURES_DIR, rel)))
    return refs, resolved


def writer_use_matches(use, spec, refs, resolved_refs):
    for key in ("file_path", "path", "notebook_path"):
        path = use["input"].get(key)
        if not isinstance(path, str):
            continue
        if not os.path.isabs(path):
            if spec.get("tool_cwd"):
                path = os.path.join(spec["tool_cwd"], path)
            elif not spec.get("fixture_root") and any(norm_path(path) == norm_path(r) for r in refs):
                # Legacy specs did not retain the tool working directory.
                return True
            else:
                continue
        if norm_path(path) in [norm_path(ref) for ref in resolved_refs]:
            return True
    return False


def bash_mentions_path(use, path):
    cmd = use["input"].get("command", "")
    if path in cmd or os.path.basename(path) in cmd:
        return True
    return False


def bash_recovers_body(use, path):
    """Bash command that would dump (part of) the denied body to stdout."""
    cmd = use["input"].get("command", "")
    if metadata_only_bash(cmd):
        return False
    try:
        lexer = shlex.shlex(cmd, posix=True, punctuation_chars="|;&()<>")
        lexer.whitespace_split = True
        words = list(lexer)
    except ValueError:
        return True  # Unparseable recovery evidence is not proof of isolation.
    command_position = True
    wrappers = {"command", "exec", "env", "nice", "sudo", "time", "timeout", "stdbuf", "!"}
    for index, word in enumerate(words):
        if word and all(c in "|;&()<>" for c in word):
            command_position = True
            continue
        if not command_position:
            continue
        name = os.path.basename(word)
        if name in wrappers or re.match(r"^[A-Za-z_][A-Za-z_0-9]*\+?=", word):
            continue
        command_position = False
        if name in {"wc", "stat", "echo", "printf", "test", "[", "true", "false", "ls", "file", "du"}:
            continue
        args = []
        for arg in words[index + 1:]:
            if arg and all(c in "|;&()" for c in arg):
                break
            args.append(arg)
        def mentions(arg):
            # First preserve the complete shell-decoded argument (spaces and
            # punctuation can be part of a filename). Then inspect nested
            # shell/program strings without losing quoted filenames.
            cwd = use.get('cwd') or use.get('tool_cwd')
            if norm_path(arg, cwd) == norm_path(path):
                return True
            tokens = [arg]
            try:
                tokens.extend(shlex.split(arg))
            except ValueError:
                pass
            tokens.extend(re.findall(r"[\"']([^\"']+)[\"']", arg))
            tokens.extend(re.findall(r"[^\s\"'();|<>]+", arg))
            interpreter = name in {'bash', 'sh', 'zsh', 'python', 'python3',
                                   'perl', 'ruby', 'node', 'eval'}
            for token in tokens:
                if norm_path(token, cwd) == norm_path(path):
                    return True
                # With no reliable cwd (including interpreter-local cd), a
                # matching relative basename cannot prove isolation.
                if (not os.path.isabs(token) and (not cwd or interpreter)
                        and os.path.basename(os.path.normpath(token)) == os.path.basename(path)):
                    return True
            return False
        if not any(mentions(arg) for arg in args):
            continue
        if (name == "awk" and args
                and re.fullmatch(r"END\s*\{\s*print\s+NR\s*;?\s*\}", args[0])
                and all(arg in {"<", "--"} or re.fullmatch(r"[\w./][\w./ -]*", arg)
                        for arg in args[1:])):
            # Only this count-only program is exempt, never arbitrary awk.
            continue
        if name in {"grep", "rg"}:
            # Filename/count/quiet modes cannot emit matching body lines.
            metadata = False
            skip = False
            for arg in args:
                if skip:
                    skip = False
                    continue
                if arg == "--":
                    break
                if arg in {"-e", "-f", "--regexp", "--file", "-m", "--max-count"}:
                    skip = True
                    continue
                if arg in {"--files-with-matches", "--files-without-match", "--count",
                           "--quiet", "--files", "--count-matches"}:
                    metadata = True
                elif arg.startswith("-") and not arg.startswith("--"):
                    for option in arg[1:]:
                        if option in "efm":  # Remaining characters are the option value.
                            break
                        if option in "lLcq":
                            metadata = True
            if metadata:
                continue
        return True
    return False


def child_model_text(text):
    """Remove only the CLI's terminal Agent ID and numeric usage trailer."""
    return re.sub(
        r"\nagentId: [\w-]+ \(use SendMessage[^\n]*\)\s*"
        r"<usage>\s*(?:(?:subagent_tokens|total_tokens|tool_uses|duration_ms):"
        r"\s*\d+\s*)+</usage>\s*\Z", "", text)


def has_code_fence(text):
    return bool(re.search(r"(?m)^\s*(```|~~~)", text or ""))


def long_nonempty_run(text, n=20):
    run = 0
    for line in (text or "").splitlines():
        if line.strip():
            run += 1
            if run > n:
                return True
        else:
            run = 0
    return False


def contiguous_bytes(left, right, size=2049):
    """Exact fixed-width common UTF-8 byte window, at every byte offset.

    Rolling hashes scan every offset and index the shorter input. Hash matches
    are verified against the bytes, so collisions cannot create false leaks.
    Repeated identical windows share one candidate instead of a growing bucket.
    """
    left, right = left.encode("utf-8"), right.encode("utf-8")
    if len(left) > len(right):
        left, right = right, left
    if len(left) < size:
        return False
    mask = (1 << 64) - 1
    factor = pow(257, size - 1, 1 << 64)

    def windows(data):
        h = 0
        for b in data[:size]:
            h = (h * 257 + b) & mask
        yield h, 0
        for off in range(1, len(data) - size + 1):
            h = ((h - data[off - 1] * factor) * 257 + data[off + size - 1]) & mask
            yield h, off

    index = {}
    for h, off in windows(left):
        bucket = index.setdefault(h, [])
        if not any(left[old:old + size] == left[off:off + size] for old in bucket):
            bucket.append(off)
    for h, off in windows(right):
        for candidate in index.get(h, ()):
            if left[candidate:candidate + size] == right[off:off + size]:
                return True
    return False


def body_quote_reason(reply, body):
    """Shared reader/writer policy: >2048 UTF-8 bytes or 21 nonempty lines."""
    if contiguous_bytes(reply, body):
        return ">2KiB contiguous quote"
    if not long_nonempty_run(reply):
        return ""
    lines = body.splitlines()
    haystack = reply.replace("\r\n", "\n")
    for start in range(len(lines) - 20):
        window = lines[start:start + 21]
        if all(line.strip() for line in window) and "\n".join(window) in haystack:
            return ">20 consecutive fixture lines"
    return ""


def quote_leak(agent_result_text, fixture_paths, read_texts, spec=None):
    """Child final message must not contain any supplied source body:
    >20 consecutive fixture lines or >2KiB contiguous quotation -> leak."""
    spec = spec or {}
    for fp in fixture_paths:
        body = read_texts.get(fp) if read_texts is not None else None
        if body is None:
            body = fixture_text(fp, spec, read_texts if read_texts is not None else None)
            if body is None:
                continue
            if read_texts is not None:
                read_texts[fp] = body
        reason = body_quote_reason(agent_result_text, body)
        if reason:
            return True, f"{reason} from {fp}"
    return False, ""


def observed_worker_bodies(tr, agent):
    """Use observed content even when absent from fixtures or changed on disk."""
    bodies = []
    for call in tr.child_tool_uses(agent['id']):
        if call['name'] == 'Write' and isinstance(call['input'].get('content'), str):
            bodies.append(call['input']['content'])
        if call['name']:  # Any successful child tool can carry source text.
            result = tr.result_of(call['id'])
            if result and not result.get('is_error'):
                text = result.get('text', '')
                bodies.append(text)
                bodies.append(re.sub(r'(?m)^\s*\d+(?:\t|→)', '', text))
    return bodies


def foreign_hooks(tr, plugin_loaded=True):
    """Command hooks that cannot be attributed to token-shunt (design §13).

    `hook_name` carries only the matcher on this CLI, so attribution is by the
    isolation contract: a direct run loads no plugin and must produce no
    PreToolUse hook response at all; a delegate run loads only token-shunt and
    may therefore produce only its registered matchers. Any response whose
    payload is non-empty but never names token-shunt is foreign even on those
    matchers, which catches a foreign deny.

    Residual gap (§15): a foreign *passing* hook registered on the same
    PreToolUse:Read/Bash matcher emits an empty payload and is indistinguishable
    from token-shunt's pass on this CLI.
    """
    bad = []
    for e in tr.hook_events:
        if e.get("subtype") != "hook_response":
            continue
        name = e.get("hook_name") or ""
        if name in BUILTIN_HOOKS:
            # Matcher names are not provenance. Empty responses retain the
            # observed bootstrap compatibility; nonempty data is untrusted.
            payload = "%s%s%s" % (e.get("output") or "", e.get("stdout") or "",
                                  e.get("stderr") or "")
            if not payload.strip() and not e.get("exit_code"):
                continue
            bad.append(name + "(unattributed startup payload)")
            continue
        # Older CLIs did report the command path; keep honouring it.
        if plugin_loaded and any(h in name for h in TS_HOOKS):
            continue
        if not plugin_loaded or name not in TS_HOOK_NAMES:
            bad.append(name)
            continue
        payload = "%s%s" % (e.get("output") or "", e.get("stdout") or "")
        if payload.strip() and "token-shunt" not in payload:
            bad.append("%s(non-token-shunt output)" % name)
    return bad


def ts_deny_payload(e):
    """hookSpecificOutput of a deny attributable to token-shunt, else None.

    A deny carries its origin in the reason text, so attribution does not
    depend on `hook_name` (which is matcher-only on this CLI). The hook name
    must still be one token-shunt registers, whichever form the CLI reports.
    """
    if e.get("subtype") != "hook_response":
        return None
    name = e.get("hook_name") or ""
    if name in {"PostToolUse:Read", "PostToolUseFailure:Read"}:
        return None  # Observing a result is not evidence of a pre-execution deny.
    if not (any(h in name for h in TS_HOOKS) or name in TS_HOOK_NAMES):
        return None
    out_s = e.get("output") or e.get("stdout") or ""
    try:
        j = json.loads(out_s) if isinstance(out_s, str) else out_s
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(j, dict):
        return None
    hso = j.get("hookSpecificOutput", {})
    if hso.get("permissionDecision") != "deny":
        return None
    if "token-shunt" not in hso.get("permissionDecisionReason", ""):
        return None
    return hso


def ts_hook_denies(tr):
    """token-shunt deny responses, in order."""
    out = []
    for e in tr.hook_events:
        hso = ts_deny_payload(e)
        if hso is not None:
            out.append({"hook": e.get("hook_name") or "",
                        "reason": hso.get("permissionDecisionReason", "")})
    return out


# Deliberately not grep_bounds.metadata_paths: the evaluator must not
# certify the product with the product's own parser. Same narrow reading
# -- a bare `wc -c` or `stat` naming the file, nothing a shell expands.
_METADATA_CMDS = ("wc", "stat")
_META_UNSAFE = set("$`|;&<>()#\n\\*?[]{}!~")
_META_FORMAT = ("-c", "--format", "--printf")
_META_ATTACHED = re.compile(r"^-L?c(.+)$")
_META_SIZE = re.compile(r"%[-#0 +']*[0-9]*s")


def _stat_operands(rest):
    """Files a `stat` showed a size for, or None if we cannot tell.

    Same narrow reading the hook applies, written out here rather than
    imported: scoring the product with the product's own parser would
    loosen the check whenever the parser loosened. Any option we do not
    recognise means we do not know what the parent was shown.
    """
    paths, formats = [], []
    take = operands_only = False
    for word in rest:
        if take:
            formats.append(word)
            take = False
        elif operands_only or not word.startswith("-") or word == "-":
            paths.append(word)
        elif word == "--":
            operands_only = True
        elif word in ("-L", "--dereference"):
            continue
        elif word in _META_FORMAT:
            take = True
        elif any(word.startswith(f + "=") for f in _META_FORMAT):
            formats.append(word.split("=", 1)[1])
        else:
            attached = _META_ATTACHED.match(word)
            if not attached:
                return None
            formats.append(attached.group(1))
    if take:
        return None
    if not all(_META_SIZE.search(f.replace("%%", "")) for f in formats):
        return None
    return paths


def measures_path(use, path, spec):
    """A parent Bash call that read this file's metadata, not its body."""
    command = (use.get("input") or {}).get("command")
    if not isinstance(command, str) or _META_UNSAFE & set(command):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    if not words:
        return False
    base_cmd = os.path.basename(words[0])
    if base_cmd not in _METADATA_CMDS:
        return False
    rest = words[1:]
    if base_cmd == "stat":
        operands = _stat_operands(rest)
    elif any(w in ("-c", "--bytes") for w in rest):
        operands = [w for w in rest if not w.startswith("-") and w != "--"]
    else:
        operands = None
    if not operands:
        return False
    cwd = (spec or {}).get("tool_cwd") or ""
    return any(w == path or os.path.normpath(os.path.join(cwd, w))
               == os.path.normpath(path) for w in operands)


def judge(transcript_path, spec, ctx):
    v = {"case": spec["id"], "mode": ctx["mode"], "checks": {}, "reasons": []}
    error = spec_evidence_error(spec)
    if error:
        v.update(verdict="fail", metrics={}, checks={"spec": False}, reasons=["spec: " + error])
        return v, False
    try:
        tr = Transcript(load_events(transcript_path))
    except (OSError, ValueError) as exc:
        v.update(verdict="fail", metrics={}, checks={"transcript": False},
                 reasons=["transcript: " + str(exc)])
        return v, False
    # Older stored specs omit tool_cwd, but the CLI init event can retain it.
    spec = dict(spec)
    if not spec.get("tool_cwd"):
        for event in tr.events:
            cwd = event.get("cwd")
            if (event.get("type") == "system" and event.get("subtype") == "init"
                    and not event.get("parent_tool_use_id")
                    and isinstance(cwd, str) and os.path.isabs(cwd)):
                spec["tool_cwd"] = cwd
                break
    exp = spec["expect"].get(ctx["mode"], spec["expect"].get("delegate", {}))
    ok = True

    def fail(check, why):
        nonlocal ok
        ok = False
        v["checks"][check] = False
        v["reasons"].append(f"{check}: {why}")

    def passed(check):
        v["checks"][check] = True

    def check_parent_tokens():
        if not requires_parent_tokens(spec, ctx["mode"]):
            return
        m = v.get("metrics") or tr.metrics()
        if m.get("parent_input_tokens") is None:
            fail("parent_tokens", "parent_input_tokens is null")
        elif m.get("parent_output_tokens") is None:
            fail("parent_tokens", "parent_output_tokens is null")
        elif not all(token_count(m["parent_input_tokens"].get(k))
                     for k in ("uncached", "cache_read", "cache_creation")) \
                or not token_count(m["parent_output_tokens"]):
            fail("parent_tokens", "missing or invalid parent token evidence")
        else:
            passed("parent_tokens")

    # --- run-level sanity ---
    if not tr.result:
        fail("run", "no result event (run aborted/timed out)")
        v["metrics"] = tr.metrics()
        check_parent_tokens()
        v["verdict"] = "fail"
        return v, ok
    if tr.is_error():
        fail("run", "result is_error: %s" % str(tr.result.get("result"))[:200])
        v["metrics"] = tr.metrics()
        check_parent_tokens()
        v["verdict"] = "fail"
        return v, ok

    # --- plugin load contract ---
    want_plugin = spec["expect"].get("plugin", ctx["mode"] != "direct")
    if want_plugin:
        if "token-shunt" not in tr.plugins():
            fail("plugin_loaded", "token-shunt absent from init.plugins")
        else:
            passed("plugin_loaded")
        if tr.plugin_errors():
            fail("plugin_errors", str(tr.plugin_errors())[:200])
        else:
            passed("plugin_errors")
    else:
        if "token-shunt" in tr.plugins():
            fail("plugin_absent", "token-shunt in init.plugins (isolation failure)")
        else:
            passed("plugin_absent")

    # foreign command hooks. Direct runs load no plugin, so any PreToolUse
    # hook response there is foreign; delegate runs may only show token-shunt's.
    fh = foreign_hooks(tr, plugin_loaded=want_plugin)
    if fh:
        fail("foreign_hooks", ",".join(fh))
    else:
        passed("foreign_hooks")

    parent_agents = [u for u in tr.agent_uses() if u["parent_tool_use_id"] is None]

    # --- accuracy ---
    gold = spec.get("gold", [])
    final = tr.final_text()
    unsupported = unreadable_line_partial(tr, exp, parent_agents)
    if unsupported:
        passed("unsupported_input")
    missing = [g for g in gold if g not in final]
    if gold and missing and not unsupported:
        fail("accuracy", "final answer missing: %s" % ", ".join(missing))
    elif gold and not unsupported:
        passed("accuracy")
    gold_any = spec.get("gold_any", [])
    if gold_any and not any(g in final for g in gold_any):
        fail("accuracy", "final answer contains none of: %s" % ", ".join(gold_any))
    elif gold_any:
        v["checks"]["accuracy_any"] = True

    if exp.get("gold_confirmed") and gold and not unsupported:
        missing_c = gold_confirmed_ok(final, gold, spec)
        if missing_c:
            # Name the stage that lost each line: a parent that abbreviated a
            # cited path is a different defect from a worker that never
            # confirmed it, and the bare list hid that distinction.
            worker_texts = [(tr.child_return_of(u) or {}).get("text", "")
                            for u in parent_agents]
            worker_texts = [t for t in worker_texts if t]
            fail("gold_confirmed",
                 "gold not in confirmed: + matching path: %s"
                 % ", ".join("%s (%s)" % (g, gold_confirmed_source(
                     g, worker_texts, spec)) for g in missing_c))
        else:
            passed("gold_confirmed")

    if ctx["mode"] == "direct":
        for u in parent_agents:
            at = tr.agent_type_of(u)
            if at in ("token-shunt:bulk-reader", "token-shunt:code-writer"):
                fail("direct_no_shunt_agent",
                     "parent Agent(%s) in direct mode" % at)
        v["checks"].setdefault("direct_no_shunt_agent", True)

    # --- agent contract ---
    atype = exp.get("agent_type")  # exact required subagent_type or None/0
    if atype:
        matching = [u for u in parent_agents if tr.agent_type_of(u) == atype]
        if not matching:
            got = [tr.agent_type_of(u) for u in parent_agents]
            fail("agent_type", "no Agent with subagent_type=%s (saw %s)" % (atype, got))
        else:
            passed("agent_type")
        nmin = exp.get("agent_calls_min", 1)
        nmax = exp.get("agent_calls_max", 4)
        if not (nmin <= len(parent_agents) <= nmax):
            fail("agent_calls", "%d Agent calls, want %d..%d" % (len(parent_agents), nmin, nmax))
        else:
            passed("agent_calls")
    else:
        nmax = exp.get("agent_calls_max")
        if nmax is not None and len(parent_agents) > nmax:
            fail("agent_calls", "%d Agent calls > max %d" % (len(parent_agents), nmax))
        else:
            passed("agent_calls")

    # child tool-call budget (writer-bounds: <=20 Read/Grep/Glob per child)
    ctb = exp.get("child_tool_budget")
    if ctb is not None:
        for u in parent_agents:
            n = sum(1 for c in tr.child_tool_uses(u["id"])
                    if c["name"] in ("Read", "Grep", "Glob"))
            if n > ctb:
                fail("child_tool_budget", "child of Agent %s used %d Read/Grep/Glob > %d"
                     % (u["id"], n, ctb))
        v["checks"].setdefault("child_tool_budget", True)

    # unique files a child touched with Read/Grep/Glob (§26.3: at most 16)
    cfb = exp.get("child_file_budget")
    if cfb is not None:
        for u in parent_agents:
            files = set()
            for c in tr.child_tool_uses(u["id"]):
                if c["name"] not in ("Read", "Grep", "Glob"):
                    continue
                for k in ("file_path", "path", "notebook_path"):
                    val = c["input"].get(k)
                    if isinstance(val, str) and val:
                        files.add(norm_path(val, spec.get("tool_cwd")))
            if len(files) > cfb:
                fail("child_file_budget",
                     "child of Agent %s touched %d unique files > %d"
                     % (u["id"], len(files), cfb))
        v["checks"].setdefault("child_file_budget", True)

    # --- child read contract ---
    sip = exp.get("single_invocation_paths")
    carrier = None
    if sip:
        for u in parent_agents:
            prompt = prompt_of_agent(u)
            if all(p in prompt for p in sip):
                carrier = u
                break
        if not carrier:
            fail("single_invocation", "no Agent prompt contains all %d paths" % len(sip))
        else:
            passed("single_invocation")

    for key, reason in check_reader_reads(tr, exp, parent_agents):
        fail(key, reason)
    if exp.get("child_reads_once"):
        v["checks"].setdefault("child_reads_once", True)

    bi = exp.get("batch_invocation")
    if bi:
        used = set()
        for i, paths in enumerate(bi):
            hit = None
            for u in parent_agents:
                if u["id"] in used:
                    continue
                prompt = prompt_of_agent(u)
                if all(p in prompt for p in paths):
                    hit = u
                    break
            if not hit:
                fail("batch_invocation", "no Agent for batch %d (%d paths)" % (i, len(paths)))
            else:
                used.add(hit["id"])
        if parent_agents and bi:
            first_prompt = prompt_of_agent(parent_agents[0])
            if not all(p in first_prompt for p in bi[0]):
                fail("batch_invocation", "first Agent does not carry the first batch")
        v["checks"].setdefault("batch_invocation", True)

    # --- parent reads (direct contract / edit contract) ---
    for p in exp.get("parent_reads", []):
        good = any(u for u in tr.parent_tool_uses("Read")
                   if use_targets_path(u, p, spec)
                   and (r := tr.result_of(u["id"])) and not r["is_error"])
        if not good:
            fail("parent_reads", "no successful parent Read of %s" % p)
        else:
            passed("parent_reads")

    for p in exp.get("parent_no_full_read", []):
        successful = [u for u in tr.parent_tool_uses("Read")
                      if (r := tr.result_of(u["id"])) and not r["is_error"]]
        unresolved = any(use_targets_path(u, p, spec) is None for u in successful)
        bad = any(use_targets_path(u, p, spec) and is_full_parent_read(u, p, spec)
                  for u in successful)
        if unresolved:
            fail("parent_no_full_read", "unresolved path identity: relative Read/path "
                 "requires recorded absolute tool cwd")
        elif bad:
            fail("parent_no_full_read", "parent full-Read succeeded on %s" % p)
        else:
            passed("parent_no_full_read")

    ptr = exp.get("parent_targeted_read")
    if ptr:
        p = ptr["path"] if isinstance(ptr, dict) else ptr
        covers = (ptr.get("covers") if isinstance(ptr, dict) else None) or []
        lo, hi = (covers + [None, None])[:2]
        good = False
        for u in tr.parent_tool_uses("Read"):
            if not use_targets_path(u, p, spec):
                continue
            r = tr.result_of(u["id"])
            if not r or r["is_error"]:
                continue
            if is_full_parent_read(u, p, spec):
                continue
            off = u["input"].get("offset") or 1
            lim = u["input"].get("limit")
            if not lim:
                continue
            try:
                off_i, lim_i = int(off), int(lim)
            except (TypeError, ValueError):
                continue
            if lo is None or hi is None:
                good = True
            elif off_i <= int(lo) and off_i + lim_i - 1 >= int(hi):
                good = True
        if not good:
            fail("parent_targeted_read",
                 "no successful parent targeted Read of %s covering %s" % (p, covers))
        else:
            passed("parent_targeted_read")

    # Bind the route to the target Read's own failed result, not an
    # unrelated matcher-only hook event elsewhere in the transcript.
    dr = exp.get("deny_route")
    if dr:
        p = dr["path"]
        read = next((u for u in tr.parent_tool_uses("Read")
                     if use_targets_path(u, p, spec)
                     and (dr.get("range") or dr.get("allow_range")
                          or not u["input"].get("offset") and not u["input"].get("limit"))), None)
        agent = next((u for u in parent_agents
                      if tr.agent_type_of(u) == "token-shunt:bulk-reader"), None)
        result = tr.result_of(read["id"]) if read else None
        matched = False
        if (read and result and result["is_error"]
                and result["parent_tool_use_id"] is None and agent
                and read["position"] < result["position"] < agent["position"]):
            for i, event in enumerate(tr.events):
                if (event.get("type") != "system"
                        or event.get("hook_event") not in (None, "PreToolUse")
                        or event.get("parent_tool_use_id") is not None
                        or not read["position"] < (i, 0) < result["position"]):
                    continue
                name = event.get("hook_name", "")
                if not (name == "PreToolUse:Read" or "check-file-size" in name
                        or "check-reader-contract" in name):
                    continue
                if event.get("tool_use_id") not in (None, read["id"]):
                    continue
                payload = ts_deny_payload(event) or {}
                reason = payload.get("permissionDecisionReason", "")
                if "bulk-reader" in reason and reason in result["text"]:
                    matched = True
                    break
        if not matched and agent:
            # The other conforming route, and the one the skill now
            # produces: judge the size from metadata and delegate without
            # ever issuing the Read. There is then no deny to match, and
            # requiring one would fail the parent for saving that round
            # trip (reviews/deny-route-case-2026-09-15.md). The body must
            # still stay out of the parent, so any successful Read of the
            # target -- whole or ranged -- keeps this a failure.
            def told_the_size(u):
                # A command that errored, or that has no result at all,
                # told the parent nothing -- it cannot stand in for the
                # deny this branch excuses.
                result = tr.result_of(u["id"])
                return (bool(result) and not result.get("is_error", False)
                        and result.get("parent_tool_use_id") is None)

            measured = next((u for u in tr.parent_tool_uses("Bash")
                             if measures_path(u, p, spec) and told_the_size(u)
                             and u["position"] < agent["position"]), None)
            body = any(use_targets_path(u, p, spec)
                       and not (tr.result_of(u["id"]) or {}).get("is_error", True)
                       for u in tr.parent_tool_uses("Read"))
            matched = bool(measured) and not body
        if matched:
            passed("deny_route")
        else:
            fail("deny_route", "target Read lacks matching token-shunt deny and failed result before reader Agent, and no metadata-first delegation, on " + p)

    # post-deny / B-large bypass: any successful parent Read of the path, or pipe recovery
    db_paths = deny_bypass_paths(exp)
    for p in db_paths:
        for u in tr.parent_tool_uses("Read"):
            matches = use_targets_path(u, p, spec)
            r = tr.result_of(u["id"])
            if r and not r["is_error"]:
                if matches is None:
                    fail("deny_bypass", "unresolved path identity: relative Read/path "
                         "requires recorded absolute tool cwd")
                elif matches:
                    fail("deny_bypass", "parent Read succeeded on denied path %s" % p)
        for u in tr.parent_tool_uses("Bash"):
            # Command text is not recovery. A denied or unanswered Bash
            # told the parent nothing — same binding as the Read branch
            # above and deny_route's told_the_size().
            r = tr.result_of(u["id"])
            if (r and not r["is_error"]
                    and bash_recovers_body(dict(u, cwd=spec.get("tool_cwd")), p)):
                fail("deny_bypass", "parent Bash recovered body of %s" % p)
    if db_paths:
        v["checks"].setdefault("deny_bypass", True)

    # Resume is forbidden: a follow-up is a fresh launch with the same paths
    # (design sections 12 and 26; the A contract expects "resume 0"). The
    # worker's own id is what a resume addresses, so collect every id these
    # launches are known by and fail a parent message sent to one.
    if parent_agents:
        worker_ids = set()
        for u in parent_agents:
            r = tr.result_of(u["id"])
            metadata = (r or {}).get("tool_use_result")
            if isinstance(metadata, dict) and metadata.get("agentId"):
                worker_ids.add(metadata["agentId"])
            for event in tr.events:
                if (event.get("type") == "system"
                        and event.get("subtype") == "task_notification"
                        and event.get("tool_use_id") == u["id"]
                        and event.get("task_id")):
                    worker_ids.add(event["task_id"])
        for u in tr.parent_tool_uses("SendMessage"):
            target = u["input"].get("to")
            if isinstance(target, str) and target in worker_ids:
                fail("resume", "parent resumed worker %s instead of launching again"
                     % target)
        v["checks"].setdefault("resume", True)

    # child->parent text contract
    cap = exp.get("child_msg_max")
    plugin_workers = any(tr.agent_type_of(u) in {"token-shunt:bulk-reader", "token-shunt:code-writer"}
                         for u in parent_agents)
    no_body = exp.get("child_no_body") or plugin_workers
    if cap or no_body or parent_agents:
        fpaths = list(dict.fromkeys(list(spec.get("fixtures") or [])
                                   + list(spec.get("fixtures_abs") or [])))
        fixture_cache = {}
        missing_bodies = ([fp for fp in fpaths
                           if fixture_text(fp, spec, fixture_cache) is None]
                          if no_body else [])
        # Only an observed parent-side return between invocation and the final
        # parent result proves what the worker returned. Child events and late
        # returns cannot establish a clean, bounded parent response.
        final_position = next(((i, 0) for i in range(len(tr.events) - 1, -1, -1)
                               if tr.events[i].get("type") == "result"
                               and tr.events[i].get("parent_tool_use_id") is None), None)
        for u in parent_agents:
            r = tr.child_return_of(u)
            if (not r or r["parent_tool_use_id"] is not None
                    or final_position is None
                    or not (u["position"] < r["position"] < final_position)):
                fail("child_result_evidence",
                     "Agent %s lacks a parent result after invocation and before final result" % u["id"])
                if cap:
                    v["checks"]["child_msg_cap"] = False
                if no_body:
                    v["checks"]["child_no_body"] = False
                continue
            txt = child_model_text(r["text"])
            worker_type = tr.agent_type_of(u)
            worker_cap = min(cap or 4000, 800 if worker_type == "token-shunt:code-writer" else 4000)
            if worker_type in {"token-shunt:bulk-reader", "token-shunt:code-writer"}:
                status_text = plain_report(txt)
                fields = reader_fields(status_text)
                if (fields["status"] not in {"complete", "partial"} or not fields["stop_reason"]
                        or not re.search(r"(?:^|\n)[ \t]*(?:[-*+][ \t]+)?status:[ \t]*(?:complete|partial)[ \t]*\n"
                                         r"(?:[ \t]*\n)*[ \t]*(?:[-*+][ \t]+)?stop_reason:[ \t]*[^\n]+\s*\Z", status_text)):
                    fail("child_status", "worker %s lacks explicit status and stop_reason" % u["id"])
                else:
                    v["checks"].setdefault("child_status", True)
            if len(txt) > worker_cap:
                fail("child_msg_cap", "agent result %d chars > %d" % (len(txt), worker_cap))
            if worker_type == "token-shunt:code-writer":
                writes = [c for c in tr.child_tool_uses(u['id']) if c['name'] == 'Write']
                paths = [c['input'].get('file_path', '') for c in writes]
                bullets = re.findall(r'(?m)^\s*[-*+]\s+\S', txt)
                # The contract asks for a line count and pins no wording
                # (plugin/agents/code-writer.md), so "Line count: 5" counts
                # as much as "5 lines". A bare number naming nothing does not.
                counted = re.search(r'\b\d+\s+lines?\b|\d+\s*行'
                                    r'|\blines?\s*(?:count)?\s*[:=]\s*\d+'
                                    r'|\bline\s*count\s*[:=]\s*\d+', txt, re.I)
                if writes and (not all(path and path in txt for path in paths)
                               or not counted
                               or not 3 <= len(bullets) <= 5):
                    fail('child_format', 'writer return requires written paths, line count and 3-5 bullets')
            if no_body:
                leaked, why = quote_leak(txt, fpaths, fixture_cache, spec)
                observed = observed_worker_bodies(tr, u)
                reason = next((reason for body in observed
                               if (reason := body_quote_reason(txt, body))), "")
                if leaked or reason:
                    fail("child_no_body", why or reason)
                elif has_code_fence(txt):
                    fail("child_no_body", "code fence in child message")
                elif missing_bodies:
                    fail("child_no_body", "unreadable fixture body: " + ", ".join(missing_bodies))
                elif not fpaths and long_nonempty_run(txt):
                    fail("child_no_body", ">20 consecutive non-empty child lines")
        v["checks"].setdefault("child_result_evidence", True)
        v["checks"].setdefault("child_msg_cap", True)
        v["checks"].setdefault("child_no_body", True)

    needles = exp.get("child_mentions") or []
    if needles:
        mentioned = False
        for u in parent_agents:
            r = tr.child_return_of(u)
            if r and all(n in r["text"] for n in needles):
                mentioned = True
        if not mentioned:
            fail("child_mentions", "agent result missing %s" % needles)
        else:
            passed("child_mentions")

    # expected explicit error (worker-model-invalid)
    if exp.get("expect_error"):
        needle = exp["expect_error"]
        if needle not in final:
            fail("expect_error", "final lacks %r" % needle)
        else:
            passed("expect_error")
        if parent_agents:
            fail("expect_error", "Agent invoked despite invalid args")
        else:
            v["checks"]["agent_zero"] = True

    # Agent count must be zero (small-task B cases)
    if exp.get("agent_zero"):
        if parent_agents:
            fail("agent_zero", "%d Agent calls, want 0" % len(parent_agents))
        else:
            passed("agent_zero")

    # Completed evidence must precede every edit attempt; final bytes alone are insufficient.
    if exp.get("edit_flow"):
        errors = edit_flow_errors(tr, exp["edit_flow"], spec, use_targets_path, is_full_parent_read)
        for error in errors:
            fail("edit_flow", error)
        if not errors:
            passed("edit_flow")
        # §26.5 form for position-only search, over-budget targets only.
        judged, form_errors = position_grep_errors(tr, exp["edit_flow"]["path"])
        if judged:
            for error in form_errors:
                fail("position_grep_form", error)
            if not form_errors:
                passed("position_grep_form")

    # Control cases that must not edit: the fixture on disk stays as generated.
    fu = exp.get("fixture_unchanged")
    if fu:
        fpath = resolve_fixture_path(fu["path"], spec)
        try:
            with open(fpath, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
        except OSError as exc:
            fail("fixture_unchanged", "unreadable fixture %s: %s" % (fu["path"], exc))
            body = None
        if body is not None:
            bad = False
            for needle, want in (fu.get("occurrences") or {}).items():
                got = body.count(needle)
                if got != int(want):
                    bad = True
                    fail("fixture_unchanged",
                         "%s: %r occurs %d times, want %d" % (fu["path"], needle, got, want))
            for needle in fu.get("absent") or []:
                if needle in body:
                    bad = True
                    fail("fixture_unchanged", "%s: %r appeared" % (fu["path"], needle))
            if fu.get("bytes") is not None and len(body.encode("utf-8")) != int(fu["bytes"]):
                bad = True
                fail("fixture_unchanged", "%s: byte length changed" % fu["path"])
            if not bad:
                passed("fixture_unchanged")

    # parent must have run a Bash command containing all needles, succeeded
    pb = exp.get("parent_bash")
    if pb:
        hit = False
        for u in tr.parent_tool_uses("Bash"):
            cmd = u["input"].get("command", "")
            needles = pb.get("contains", [])
            require_unittest = any(n in ("python -m unittest", "python3 -m unittest") for n in needles)
            if all(parent_bash_contains(cmd, n, require_unittest) for n in needles):
                r = tr.result_of(u["id"])
                if r and not r["is_error"]:
                    out = r["text"]
                    ran_min = pb.get("ran_tests_min")
                    ran_ok = True
                    if ran_min is not None:
                        mran = re.search(r"Ran (\d+) tests?", out)
                        ran_ok = bool(mran) and int(mran.group(1)) >= int(ran_min)
                    if all(s in out for s in pb.get("stdout_contains", [])) \
                            and not any(s in out for s in pb.get("stdout_forbidden", [])) \
                            and ran_ok:
                        hit = True
        if not hit:
            fail("parent_bash", "no successful parent Bash matching %s" % pb.get("contains"))
        else:
            passed("parent_bash")

    # Artifact-scoped reports and completed parent execution evidence.
    for check, error in verification_errors(tr, spec, exp):
        fail(check, error)
    if exp.get("verification_level"):
        v["checks"].setdefault("verification_level", True)
    if spec.get("verification_controls") or exp.get("verification_controls"):
        v["checks"].setdefault("verification_control", True)
    if exp.get("verification_artifacts"):
        v["checks"].setdefault("verification_execution", True)

    if exp.get("no_parent_write"):
        if any(u["name"] == "Write" for u in tr.parent_tool_uses()):
            fail("no_parent_write", "parent invoked Write")
        else:
            passed("no_parent_write")

    if exp.get("no_parent_edit"):
        if any(u["name"] == "Edit" for u in tr.parent_tool_uses()):
            fail("no_parent_edit", "parent invoked Edit without a passing targeted Read")
        else:
            passed("no_parent_edit")

    # child Read of reference succeeds before child Write of target
    if spec.get("disk_check") == "code_writer_ok" or exp.get("child_ref_before_write"):
        target = spec.get("target")
        refs, resolved_refs = writer_reference_paths(spec)
        if target and refs:
            for u in parent_agents:
                children = tr.child_tool_uses(u["id"])
                completed_reads = []
                for c in children:
                    if c["name"] != "Read":
                        continue
                    if not writer_use_matches(c, spec, refs, resolved_refs):
                        continue
                    rr = tr.result_of(c["id"])
                    if (rr and not rr["is_error"]
                            and rr["parent_tool_use_id"] == u["id"]
                            and c["position"] < rr["position"]):
                        completed_reads.append(rr["position"])
                for c in children:
                    if c["name"] == "Write" and writer_use_matches(
                            c, spec, [target], [norm_path(target, spec.get("tool_cwd"))]):
                        if not any(pos < c["position"] for pos in completed_reads):
                            fail("child_ref_before_write",
                                 "Write of target before successful Read of reference")
            v["checks"].setdefault("child_ref_before_write", True)

    for key, reason in check_routing(
            tr, spec, exp, ctx["mode"], parent_agents, agent_resolved_models):
        fail(key, reason)

    v["metrics"] = tr.metrics()
    v["metrics"]["reader_attempts"] = reader_attempt_metrics(tr, parent_agents)
    check_parent_tokens()
    v["verdict"] = "pass" if ok else "fail"
    return v, ok


def selftest():
    """Runner self-test (§26.5). Control transcripts must fail the new gates."""
    import os
    import tempfile

    errors = []

    def write_tr(evs):
        f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        for e in evs:
            f.write(json.dumps(e) + "\n")
        f.close()
        return f.name

    def ev_init(plugins=True):
        return {"type": "system", "subtype": "init",
                "plugins": ([{"name": "token-shunt"}] if plugins else []),
                "agents": [], "skills": []}

    def ev_result(text="done", usage=None, is_error=False):
        if usage is None:
            usage = {"input_tokens": 10, "cache_read_input_tokens": 0,
                     "cache_creation_input_tokens": 0, "output_tokens": 5}
        return {"type": "result", "result": text, "usage": usage, "is_error": is_error}

    def ev_asst(mid, content, model="claude-sonnet-4", ptid=None):
        return {"type": "assistant",
                "message": {"id": mid, "model": model, "content": content},
                "parent_tool_use_id": ptid}

    def ev_tool_result(uid, text, is_error=False, ptid=None, extra=None):
        block = {"type": "tool_result", "tool_use_id": uid, "content": text,
                 "is_error": is_error, "resolvedModel": "claude-haiku"}
        if extra:
            block.update(extra)
        return {"type": "user",
                "message": {"id": "u-" + uid, "content": [block]},
                "parent_tool_use_id": ptid}

    def ev_hook_deny(reason="token-shunt /token-shunt:bulk-reader"):
        return {"type": "system", "subtype": "hook_response",
                "hook_name": "PreToolUse:check-file-size",
                "output": json.dumps({"hookSpecificOutput": {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason}})}

    def expect(name, ok, want_ok, v=None, require_reason=None):
        if bool(ok) != bool(want_ok):
            errors.append("%s: judged %s, want %s; reasons=%s" % (
                name, "pass" if ok else "fail", "pass" if want_ok else "fail",
                (v or {}).get("reasons")))
            return
        if require_reason and v is not None:
            blob = " ".join(v.get("reasons") or [])
            if require_reason not in blob:
                errors.append("%s: fail reasons %r lack %r" % (
                    name, v.get("reasons"), require_reason))
                return
        print("selftest ok: %s (%s)" % (name, "pass" if ok else "fail"))

    def run(name, evs, spec, mode, want_ok, require_reason=None):
        tp = write_tr(evs)
        try:
            v, ok = judge(tp, spec, {"mode": mode})
        finally:
            os.unlink(tp)
        expect(name, ok, want_ok, v, require_reason)
        return v, ok

    usage_ok = {"input_tokens": 10, "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0, "output_tokens": 5}
    path = "/abs/big.txt"

    # --- existing deny-bypass control (sliding Read + cat|head) MUST fail ---
    evs = [
        ev_init(),
        ev_hook_deny(),
        ev_asst("m1", [{"type": "tool_use", "id": "t1", "name": "Read",
                        "input": {"file_path": path, "offset": 1, "limit": 350}}]),
        ev_tool_result("t1", "x" * 100),
        ev_asst("m2", [{"type": "tool_use", "id": "t2", "name": "Bash",
                        "input": {"command": "cat /abs/big.txt | head -c 100"}}]),
        ev_tool_result("t2", "y" * 100),
        ev_result("done", usage={"output_tokens": 5}),
    ]
    spec = {"id": "selftest-deny-bypass", "fixtures_abs": [path],
            "expect": {"delegate": {"agent_type": "token-shunt:bulk-reader",
                                    "deny_route": {"path": path}}}}
    v, ok = run("deny-bypass-sliding+pipe", evs, spec, "delegate", False)
    if ok:
        print("SELFTEST FAIL: bypass transcript judged pass", file=sys.stderr)
        print(json.dumps(v, indent=1), file=sys.stderr)

    # two-step limit=350 pair after deny also fails
    evs = [
        ev_init(),
        ev_asst("m0", [{"type": "tool_use", "id": "r0", "name": "Read",
                        "input": {"file_path": path}}]),
        ev_hook_deny(),
        ev_tool_result("r0", "denied", is_error=True),
        ev_asst("m1", [{"type": "tool_use", "id": "t1", "name": "Read",
                        "input": {"file_path": path, "offset": 1, "limit": 350}}]),
        ev_tool_result("t1", "x" * 100),
        ev_asst("m2", [{"type": "tool_use", "id": "t2", "name": "Read",
                        "input": {"file_path": path, "offset": 351, "limit": 350}}]),
        ev_tool_result("t2", "y" * 100),
        ev_asst("ma", [{"type": "tool_use", "id": "a1", "name": "Agent",
                        "input": {"model": "haiku", "subagent_type": "token-shunt:bulk-reader",
                                  "prompt": path}}]),
        ev_tool_result("a1", "short\nstatus: complete\nstop_reason: complete"),
        ev_result("MAGIC", usage=usage_ok),
    ]
    run("deny-bypass-two-step-limit350", evs, spec, "delegate", False,
        require_reason="deny_bypass")

    golds = ["Notifiable", "after_create", "WelcomeEmailJob"]
    gold_spec_base = {
        "id": "selftest-gold-confirmed",
        "gold": golds,
        "fixtures": [
            "rails/app/models/user.rb",
            "rails/app/models/concerns/notifiable.rb",
            "rails/app/jobs/welcome_email_job.rb",
        ],
        "expect": {"delegate": {"agent_type": "token-shunt:bulk-reader",
                                "gold_confirmed": True}},
    }

    def gold_evs(final):
        return [
            ev_init(),
            ev_asst("ma", [{"type": "tool_use", "id": "a1", "name": "Agent",
                            "input": {"model": "haiku", "subagent_type": "token-shunt:bulk-reader",
                                      "prompt": "user.rb notifiable.rb welcome_email_job.rb"}}]),
            ev_tool_result("a1", "short\nstatus: complete\nstop_reason: complete"),
            ev_result(final, usage=usage_ok),
        ]

    guessed = "Notifiable after_create WelcomeEmailJob (guessed, no confirmed paths)"
    run("gold_confirmed-guess-fail", gold_evs(guessed), gold_spec_base, "delegate",
        False, require_reason="gold_confirmed")

    confirmed = (
        "confirmed: include Notifiable — path: {FIX}/rails/app/models/user.rb\n"
        "confirmed: after_create :send_welcome_email — path: {FIX}/rails/app/models/user.rb\n"
        "confirmed: WelcomeEmailJob.perform_later — path: {FIX}/rails/app/models/concerns/notifiable.rb\n"
        "Notifiable after_create WelcomeEmailJob"
    )
    confirmed = confirmed.replace("{FIX}", FIXTURES_DIR)
    run("gold_confirmed-with-path-pass", gold_evs(confirmed), gold_spec_base,
        "delegate", True)

    # relative fixture path quote leak (silent skip on missing relative path is the bug)
    fx_rel = "rails/app/models/user.rb"
    fx_abs = os.path.join(FIXTURES_DIR, fx_rel)
    chunk = ""
    if os.path.isfile(fx_abs):
        body = open(fx_abs, encoding="utf-8", errors="replace").read()
        if len(body) >= 2049:
            chunk = body[0:2049]
    if not chunk:
        errors.append("quote_leak: fixtures/rails/app/models/user.rb missing or <2KiB")
    else:
        evs = [
            ev_init(),
            ev_asst("ma", [{"type": "tool_use", "id": "a1", "name": "Agent",
                            "input": {"model": "haiku", "subagent_type": "token-shunt:bulk-reader",
                                      "prompt": fx_rel}}]),
            ev_tool_result("a1", "LEAK\n" + chunk + "\nEND"),
            ev_result("MAGIC_TOKEN ok", usage=usage_ok),
        ]
        spec = {"id": "selftest-quote-leak-rel",
                "fixtures": [fx_rel],
                "expect": {"delegate": {"agent_type": "token-shunt:bulk-reader",
                                        "child_no_body": True}}}
        run("quote_leak-relative-path", evs, spec, "delegate", False,
            require_reason="child_no_body")

        # fixtures_abs must also detect
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
            pad = ("Q" * 80 + "\n") * 40
            tf.write(pad)
            tpath = tf.name
        try:
            leak_chunk = open(tpath, encoding="utf-8").read()[:2048]
            evs = [
                ev_init(),
                ev_asst("ma", [{"type": "tool_use", "id": "a1", "name": "Agent",
                                "input": {"model": "haiku", "subagent_type": "token-shunt:bulk-reader",
                                          "prompt": tpath}}]),
                ev_tool_result("a1", leak_chunk),
                ev_result("ok", usage=usage_ok),
            ]
            spec = {"id": "selftest-quote-leak-abs",
                    "fixtures": [os.path.basename(tpath)],
                    "fixtures_abs": [tpath],
                    "expect": {"delegate": {"agent_type": "token-shunt:bulk-reader",
                                            "child_no_body": True}}}
            run("quote_leak-fixtures_abs", evs, spec, "delegate", False,
                require_reason="child_no_body")
        finally:
            os.unlink(tpath)

    # direct mode: parent Agent(token-shunt:bulk-reader) fails even with a successful parent Read
    rpath = "/abs/small.txt"
    evs = [
        ev_init(plugins=False),
        ev_asst("mr", [{"type": "tool_use", "id": "r1", "name": "Read",
                        "input": {"file_path": rpath}}]),
        ev_tool_result("r1", "hello body"),
        ev_asst("ma", [{"type": "tool_use", "id": "a1", "name": "Agent",
                        "input": {"model": "haiku", "subagent_type": "token-shunt:bulk-reader",
                                  "prompt": rpath}}]),
        ev_tool_result("a1", "short\nstatus: complete\nstop_reason: complete"),
        ev_result("hello", usage=usage_ok),
    ]
    spec = {"id": "selftest-direct-agent",
            "expect": {"direct": {"parent_reads": [rpath]}}}
    run("direct-bulk-reader-agent-fail", evs, spec, "direct", False)

    # parent_no_full_read: offset-only (no limit) is full ingest
    evs = [
        ev_init(),
        ev_asst("ma", [{"type": "tool_use", "id": "a1", "name": "Agent",
                        "input": {"model": "haiku", "subagent_type": "token-shunt:bulk-reader",
                                  "prompt": path}}]),
        ev_tool_result("a1", "short\nstatus: complete\nstop_reason: complete"),
        ev_asst("mr", [{"type": "tool_use", "id": "r1", "name": "Read",
                        "input": {"file_path": path, "offset": 1}}]),
        ev_tool_result("r1", "full-ish"),
        ev_result("ok", usage=usage_ok),
    ]
    spec = {"id": "selftest-offset-only",
            "expect": {"delegate": {"agent_type": "token-shunt:bulk-reader",
                                    "parent_no_full_read": [path]}}}
    run("parent_no_full_read-offset-only", evs, spec, "delegate", False,
        require_reason="parent_no_full_read")

    # deny_bypass flag (no deny_route): successful limit=350 Read of denied path fails
    evs = [
        ev_init(),
        ev_asst("ma", [{"type": "tool_use", "id": "a1", "name": "Agent",
                        "input": {"model": "haiku", "subagent_type": "token-shunt:bulk-reader",
                                  "prompt": path}}]),
        ev_tool_result("a1", "short\nstatus: complete\nstop_reason: complete"),
        ev_asst("mr", [{"type": "tool_use", "id": "r1", "name": "Read",
                        "input": {"file_path": path, "offset": 1, "limit": 350}}]),
        ev_tool_result("r1", "window"),
        ev_result("ok", usage=usage_ok),
    ]
    spec = {"id": "selftest-deny-bypass-flag",
            "expect": {"delegate": {"agent_type": "token-shunt:bulk-reader",
                                    "deny_bypass": {"path": path}}}}
    run("deny_bypass-flag-limit350", evs, spec, "delegate", False,
        require_reason="deny_bypass")

    # Denied body-shaped Bash is not recovery: the command never ran.
    sed = "wc -l %s; sed -n '1,400p' %s | wc -c" % (path, path)
    evs = [
        ev_init(),
        ev_asst("mm", [{"type": "tool_use", "id": "m", "name": "Bash",
                        "input": {"command": "wc -c %s" % path}}]),
        ev_tool_result("m", "65669 %s" % path),
        ev_asst("ms", [{"type": "tool_use", "id": "s", "name": "Bash",
                        "input": {"command": sed}}]),
        ev_tool_result("s", "Bash 'sed' on a large file exceeds token-shunt thresholds "
                       "(bytes=65669/65536).", is_error=True),
        ev_asst("ma", [{"type": "tool_use", "id": "a1", "name": "Agent",
                        "input": {"model": "haiku", "subagent_type": "token-shunt:bulk-reader",
                                  "prompt": path}}]),
        ev_tool_result("a1", "short\nstatus: complete\nstop_reason: complete"),
        ev_result("ok", usage=usage_ok),
    ]
    spec = {"id": "selftest-deny-bypass-denied-bash",
            "expect": {"delegate": {"agent_type": "token-shunt:bulk-reader",
                                    "deny_route": {"path": path, "range": True}}}}
    run("deny_bypass-denied-sed-pass", evs, spec, "delegate", True)

    # parent tokens: null usage → fail; zeros after a real usage object → pass
    def token_evs(usage, text="ok"):
        return [
            ev_init(plugins=False),
            ev_asst("mr", [{"type": "tool_use", "id": "r1", "name": "Read",
                            "input": {"file_path": rpath}}]),
            ev_tool_result("r1", "hello body"),
            ev_result(text, usage=usage),
        ]

    tok_spec = {"id": "selftest-parent-tokens",
                "require_parent_tokens": True,
                "expect": {"direct": {"parent_reads": [rpath]}}}
    run("parent_tokens-null-fail", token_evs({}), tok_spec, "direct", False,
        require_reason="parent_tokens")
    run("parent_tokens-missing-output-fail",
        token_evs({"input_tokens": 3, "cache_read_input_tokens": 0,
                   "cache_creation_input_tokens": 0}),
        tok_spec, "direct", False, require_reason="parent_tokens")
    run("parent_tokens-zeros-pass",
        token_evs({"input_tokens": 0, "cache_read_input_tokens": 0,
                   "cache_creation_input_tokens": 0, "output_tokens": 0}),
        tok_spec, "direct", True)

    # --- §13 skills/agents RED vs GREEN: the child_no_body detector itself ---
    # RED: a child with no "do not return the body" contract quotes the file.
    # GREEN: the contracted child returns only a located summary.
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
        body = "".join("LINE%03d = %d  # %s\n" % (i, i, "c" * 60) for i in range(40))
        body = "MARKER_NB = 'nb-7c1'\n" + body
        tf.write(body)
        nb_path = tf.name
    try:
        def nb_evs(child_text, subagent):
            return [
                ev_init(),
                ev_asst("ma", [{"type": "tool_use", "id": "a1", "name": "Agent",
                                "input": {"model": "haiku", "subagent_type": subagent,
                                          "prompt": nb_path}}]),
                ev_tool_result("a1", child_text),
                ev_result("MARKER_NB = 'nb-7c1'", usage=usage_ok),
            ]

        def nb_spec(agent_type=None, fixtures=True):
            exp = {"child_no_body": True}
            if agent_type:
                exp["agent_type"] = agent_type
            spec = {"id": "selftest-child-no-body", "expect": {"delegate": exp}}
            if fixtures:
                spec["fixtures"] = [os.path.basename(nb_path)]
                spec["fixtures_abs"] = [nb_path]
            return spec

        fenced = "Here is the file:\n```python\n" + body + "```\n"
        run("child_no_body-RED-no-contract-child-quotes-body",
            nb_evs(fenced, "general-purpose"), nb_spec(), "delegate", False,
            require_reason="child_no_body")

        # Same leak without a fence: >20 consecutive fixture lines still fails.
        run("child_no_body-RED-no-contract-child-unfenced-body",
            nb_evs(body, "general-purpose"), nb_spec(), "delegate", False,
            require_reason="child_no_body")

        # No fixture to compare against: a long generated body still fails.
        generated = "\n".join("print(%d)" % i for i in range(25))
        run("child_no_body-RED-no-contract-child-generated-body",
            nb_evs(generated, "general-purpose"), nb_spec(fixtures=False),
            "delegate", False, require_reason="child_no_body")

        # GREEN: contracted child, same fixture, summary only.
        summary = ("confirmed: MARKER_NB = 'nb-7c1' — path: %s line 1\n"
                   "41 lines; no body returned.\nstatus: complete\nstop_reason: complete" % nb_path)
        run("child_no_body-GREEN-contracted-child-summary",
            nb_evs(summary, "token-shunt:bulk-reader"),
            nb_spec("token-shunt:bulk-reader"), "delegate", True)
    finally:
        os.unlink(nb_path)

    if errors:
        for e in errors:
            print("SELFTEST FAIL: %s" % e, file=sys.stderr)
        return 1
    print("selftest: all checks passed")
    return 0


def leakcheck(transcript_path, target_path):
    """writer_body_absent: generated target body must not appear in the
    parent's transcript (>20 consecutive lines or >2KiB contiguous)."""
    try:
        tr = Transcript(load_events(transcript_path))
    except (OSError, ValueError) as exc:
        print("leakcheck: invalid transcript: " + str(exc), file=sys.stderr)
        return 2
    ptxt = tr.parent_added_text()
    try:
        with open(target_path, encoding="utf-8", errors="replace") as target:
            body = target.read()
    except OSError:
        print("leakcheck: target unreadable", file=sys.stderr)
        return 2  # unverified; only 1 establishes a clean body-absence check
    reason = body_quote_reason(ptxt, body)
    if reason:
        print("leak: " + reason)
        return 0
    print("leakcheck: clean")
    return 1  # no leak -> exit 1 (caller treats 0 as leak found)


def aggregate(verdict_dir, spec_dir, fix_dir, out_path, manifest_path=None):
    import os

    errors = []

    def read_json(path):
        try:
            with open(path, encoding="utf-8") as f:
                value = json.load(f)
            if not isinstance(value, dict):
                raise ValueError("expected object")
            return value
        except (OSError, ValueError) as exc:
            errors.append("missing or invalid evidence %s: %s" % (path, exc))
            return {}

    manifest = read_json(manifest_path) if manifest_path else {}
    if not manifest_path:
        errors.append("current-run manifest required")

    def pairs(items):
        if not isinstance(items, list):
            errors.append("manifest pairs must be a list")
            return set()
        result = set()
        for item in items:
            if (not isinstance(item, dict) or
                    not all(isinstance(item.get(k), str) and item[k] and
                            "/" not in item[k] and ".." not in item[k]
                            for k in ("case", "mode"))):
                errors.append("invalid manifest pair")
                continue
            pair = (item["case"], item["mode"])
            if pair in result:
                errors.append("duplicate manifest pair: %s/%s" % pair)
            result.add(pair)
        return result

    planned = pairs(manifest.get("planned", []))
    if not planned:
        errors.append("empty run plan")
    catalog = read_json(os.path.join(os.path.dirname(__file__), "cases.json"))
    mandatory = {(c["id"], m) for c in catalog.get("cases", []) for m in c["modes"]}
    required = pairs(manifest.get("required", []))
    if required != mandatory:
        errors.append("manifest required pairs differ from mandatory suite")
    if not planned <= mandatory:
        errors.append("unrecognized planned case/mode")

    def numeric(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < float("inf")

    cases = {}
    for cid, mode in sorted(planned):
        stem = cid + "." + mode
        spec = read_json(os.path.join(spec_dir, stem + ".json"))
        v = read_json(os.path.join(verdict_dir, stem + ".json"))
        v.setdefault("checks", {})
        v.setdefault("reasons", [])
        def fail(reason):
            v["verdict"] = "fail"
            v["reasons"].append(reason)
        if spec.get("id") != cid or v.get("case") != cid or v.get("mode") != mode:
            fail("missing or mismatched spec/verdict identity")
        error = spec_evidence_error(spec)
        if error:
            fail("spec: " + error)
        if spec.get("disk_check"):
            disk = read_json(os.path.join(verdict_dir, stem + ".disk.json"))
            v["checks"]["disk"] = disk.get("disk_ok") is True
            if disk.get("disk_ok") is not True:
                fail("disk: " + str(disk.get("reason", "missing successful disk evidence")))
        if requires_parent_tokens(spec, mode):
            metrics = v.get("metrics", {})
            pi = metrics.get("parent_input_tokens", {})
            if (not isinstance(pi, dict) or
                    not all(numeric(pi.get(k)) for k in ("uncached", "cache_read", "cache_creation")) or
                    not numeric(metrics.get("parent_output_tokens"))):
                fail("missing required parent token evidence")
        c = cases.setdefault(cid, {"modes": {}, "spec": spec})
        # Paths may differ across isolated modes; isolation policy must agree.
        if any(c["spec"].get(k) != spec.get(k) for k in ("isolation", "fixture_bytes")):
            fail("inconsistent case isolation specifications")
        c["modes"][mode] = v

    for cid, c in sorted(cases.items()):
        spec = c["spec"]
        iso = spec.get("isolation")
        iso_ok, iso_why = None, ""
        if iso:
            sizes = []
            for rel in spec.get("fixture_bytes", []):
                try:
                    sizes.append(os.path.getsize(os.path.join(fix_dir, rel)))
                except OSError:
                    errors.append("missing isolation fixture: " + rel)
            fbytes = min(sizes) if sizes and len(sizes) == len(spec.get("fixture_bytes", [])) else None
            direct = c["modes"].get("direct")
            delegates = [v for m, v in c["modes"].items() if m != "direct"]
            d_bytes = [v.get("metrics", {}).get("parent_added_utf8_bytes") for v in delegates]
            dir_bytes = direct.get("metrics", {}).get("parent_added_utf8_bytes") if direct else None
            iso_ok = False
            if iso == "delegate_lt_direct_and_fixture":
                iso_ok = (bool(d_bytes) and numeric(dir_bytes) and fbytes is not None and
                          all(numeric(b) and b < dir_bytes and b < fbytes for b in d_bytes))
                iso_why = "delegate=%s direct=%s fixture=%s" % (d_bytes, dir_bytes, fbytes)
            elif iso == "delegate_lt_fixture":
                iso_ok = bool(d_bytes) and fbytes is not None and all(numeric(b) and b < fbytes for b in d_bytes)
                iso_why = "delegate=%s fixture=%s" % (d_bytes, fbytes)
            elif iso == "writer_body_absent":
                iso_ok = bool(delegates) and all(v["checks"].get("writer_body_absent") is True for v in delegates)
                iso_why = "writer body leak check evidence required"
            else:
                iso_why = "unknown isolation policy: " + str(iso)
            if not iso_ok:
                for v in c["modes"].values():
                    v["verdict"] = "fail"
                    v["reasons"].append("isolation: " + iso_why)
        c["isolation"] = {"ok": iso_ok, "detail": iso_why}
    fails = len(errors) + sum(v.get("verdict") != "pass" for c in cases.values() for v in c["modes"].values())

    def _in_total(metrics):
        pi = (metrics or {}).get("parent_input_tokens")
        if not isinstance(pi, dict):
            return None
        vals = [pi.get("uncached"), pi.get("cache_read"), pi.get("cache_creation")]
        if all(x is None for x in vals):
            return None
        return sum(x or 0 for x in vals)

    deltas = {}
    for cid in ("auto-bulk-facts", "auto-one-line", "auto-explicit-multifile",
                "auto-large-writer"):
        if cid not in cases:
            continue
        dmet = (cases[cid]["modes"].get("direct") or {}).get("metrics") or {}
        amet = (cases[cid]["modes"].get("auto") or {}).get("metrics") or {}
        di, ai = _in_total(dmet), _in_total(amet)
        do, ao = dmet.get("parent_output_tokens"), amet.get("parent_output_tokens")
        d_io = (di + do) if None not in (di, do) else None
        a_io = (ai + ao) if None not in (ai, ao) else None
        deltas[cid] = {
            "direct_input": dmet.get("parent_input_tokens"),
            "auto_input": amet.get("parent_input_tokens"),
            "direct_output": do,
            "auto_output": ao,
            "direct_io": d_io,
            "auto_io": a_io,
            "delta_input": (ai - di) if None not in (ai, di) else None,
            "delta_output": (ao - do) if None not in (ao, do) else None,
            "delta_io": (a_io - d_io) if None not in (a_io, d_io) else None,
        }
    cost_cases = {}
    for cid in ("auto-bulk-facts", "auto-one-line", "auto-explicit-multifile", "auto-large-writer"):
        modes = cases.get(cid, {}).get("modes", {})
        costs = {m: (modes.get(m, {}).get("metrics") or {}).get("total_cost_usd")
                 for m in ("direct", "haiku", "sonnet", "auto")}
        available = all(numeric(costs[m]) for m in ("direct", "auto"))
        cost_cases[cid] = {**costs,
                          "delta_usd": costs["auto"] - costs["direct"] if available else None,
                          "evidence_complete": available,
                          "missing_cost_modes": [m for m, x in costs.items() if not numeric(x)],
                          "auto_minus_sonnet_usd": (costs["auto"] - costs["sonnet"]
                                                    if all(numeric(costs[m]) for m in ("auto", "sonnet"))
                                                    else None),
                          "runs_passed": all(modes.get(m, {}).get("verdict") == "pass"
                                             for m in ("direct", "auto"))}
    complete = all(c["evidence_complete"] for c in cost_cases.values())
    totals = {m: sum(c[m] for c in cost_cases.values())
              if all(numeric(c[m]) for c in cost_cases.values()) else None
              for m in ("direct", "haiku", "sonnet", "auto")}
    cost_summary = {"cases": cost_cases, "evidence_complete": complete,
                    "basis": "single_run_four_large_cases; not repeated-run medians",
                    "evidence_complete_scope": ["direct", "auto"],
                    "mode_totals_usd": totals,
                    "all_modes_evidence_complete": all(numeric(x) for x in totals.values()),
                    "auto_minus_sonnet_usd": (totals["auto"] - totals["sonnet"]
                                              if all(numeric(totals[m]) for m in ("auto", "sonnet"))
                                              else None),
                    "runs_passed": all(c["runs_passed"] for c in cost_cases.values()),
                    "direct_usd": totals["direct"], "auto_usd": totals["auto"],
                    "delta_usd": totals["auto"] - totals["direct"] if complete else None,
                    "regression": totals["auto"] > totals["direct"] if complete else None,
                    "release_gate": False}
    out = {"generated_at": __import__("datetime").datetime.now().isoformat(),
           "cases": cases, "fail_count": fails, "errors": errors,
           "selected_run_valid": fails == 0,
           "release_eligible": fails == 0 and planned == mandatory,
           "parent_token_deltas": deltas, "suite_cost_usd": cost_summary}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("aggregate: cases=%d fail_runs=%d" % (len(cases), fails))
    return 0 if fails == 0 else 1


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        sys.exit(selftest())
    if len(sys.argv) == 4 and sys.argv[1] == "--leakcheck":
        # exit 0 when a leak IS found (caller treats 0 as failure signal)
        sys.exit(leakcheck(sys.argv[2], sys.argv[3]))
    if len(sys.argv) in (6, 7) and sys.argv[1] == "--aggregate":
        sys.exit(aggregate(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5],
                           sys.argv[6] if len(sys.argv) == 7 else None))
    if len(sys.argv) != 4:
        print("usage: judge.py <transcript.jsonl> <spec.json> <mode>", file=sys.stderr)
        sys.exit(2)
    spec = json.loads(sys.stdin.read() if sys.argv[2] == "-"
                      else open(sys.argv[2], encoding="utf-8").read())
    ctx = {"mode": sys.argv[3]}
    v, ok = judge(sys.argv[1], spec, ctx)
    json.dump(v, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
