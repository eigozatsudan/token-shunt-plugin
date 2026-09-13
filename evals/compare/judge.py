#!/usr/bin/env python3
"""token-shunt compare-eval transcript judge (design §13, §26.5).

Reads one stream-json transcript plus a case spec and emits a verdict JSON:
accuracy / path_ok / isolation_ok + metrics. Exits non-zero on contract
failures so the runner can stop the release.
"""
import json
import os
import re
import sys

from routing_checks import check_reader_reads, check_routing
from flow_checks import edit_flow_errors, verification_errors

COMPARE_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURES_DIR = os.environ.get("TOKEN_SHUNT_EVAL_FIXTURES", os.path.join(COMPARE_DIR, "fixtures"))

READ_TOOLS = {"Read"}
BODY_TOOLS = {"cat", "head", "tail", "less", "more"}
TS_HOOKS = ("check-file-size", "check-bash-read", "check-jq")
# CLI-internal bootstrap hook that fires in every session; not a settings hook.
BUILTIN_HOOKS = {"SessionStart:startup"}
AGENT_TOOL_NAMES = {"Agent", "Task"}


def load_events(path):
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
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


class Transcript:
    def __init__(self, events):
        self.events = events
        self.init = next((e for e in events if e.get("type") == "system"
                          and e.get("subtype") == "init"), {})
        self.result = next((e for e in reversed(events)
                            if e.get("type") == "result"), {})
        self.tool_uses = []      # {id,name,input,parent_tool_use_id,msg_id,model}
        self.tool_results = {}   # tool_use_id -> {content_text,is_error,parent_tool_use_id}
        self.hook_events = []    # hook_started/hook_response
        self.assistant_msgs = [] # {id,model,text,parent_tool_use_id}
        self.user_msgs = []      # parent-level user/tool_result messages
        for e in events:
            t = e.get("type")
            ptid = e.get("parent_tool_use_id")
            if t == "system" and e.get("subtype") in ("hook_started", "hook_response"):
                self.hook_events.append(e)
            elif t == "assistant":
                m = e.get("message", {})
                mid = m.get("id")
                text_parts = []
                for b in m.get("content", []) or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        self.tool_uses.append({
                            "id": b.get("id"),
                            "name": b.get("name"),
                            "input": b.get("input", {}),
                            "parent_tool_use_id": ptid,
                            "msg_id": mid,
                            "model": m.get("model"),
                        })
                    elif b.get("type") == "text":
                        text_parts.append(b.get("text", ""))
                self.assistant_msgs.append({
                    "id": mid, "model": m.get("model"),
                    "text": "\n".join(text_parts), "parent_tool_use_id": ptid,
                })
            elif t == "user":
                m = e.get("message", {})
                self.user_msgs.append({"id": m.get("id"), "parent_tool_use_id": ptid,
                                       "message": m})
                for b in m.get("content", []) or []:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        rec = {
                            "text": text_of(b.get("content")),
                            "is_error": bool(b.get("is_error")),
                            "parent_tool_use_id": ptid,
                            "raw": b,
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

    def agent_uses(self):
        return [u for u in self.all_tool_uses()
                if u["name"] in AGENT_TOOL_NAMES]

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
            key = ("a", a["id"])
            if a["id"] and key in seen:
                continue
            seen.add(key)
            parts.append(a["text"])
        for u in self.user_msgs:
            if u["parent_tool_use_id"] is not None:
                continue
            m = u["message"]
            key = ("u", m.get("id"))
            if m.get("id") and key in seen:
                continue
            seen.add(key)
            parts.append(text_of(m.get("content")))
        return "\n".join(parts)

    def metrics(self):
        ptxt = self.parent_added_text()
        usage = self.result.get("usage", {}) or {}
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


def norm_path(p):
    return p.rstrip("/") if isinstance(p, str) else p


def resolve_fixture_path(fp, spec=None):
    """Resolve a fixture path: absolute, fixtures_abs, or compare/fixtures/."""
    if not fp or not isinstance(fp, str):
        return fp
    if os.path.isabs(fp) and os.path.isfile(fp):
        return fp
    spec = spec or {}
    for a in spec.get("fixtures_abs") or []:
        if not isinstance(a, str):
            continue
        if a == fp or a.endswith("/" + fp.lstrip("./")) \
                or os.path.basename(a) == os.path.basename(fp):
            if os.path.isfile(a):
                return a
        if os.path.isfile(a) and fp in a:
            return a
    rel = fp
    if rel.startswith("fixtures/"):
        rel = rel[len("fixtures/"):]
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
    body = None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            body = f.read()
    except OSError:
        body = None
    if cache is not None:
        cache[fp] = body
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
                r"confirmed:\s*(.+?)(?=confirmed:|inferred:|unconfirmed:|$)",
                text or "", re.I | re.S):
            items.append(m.group(1).strip())
    return items


def gold_path_needles(gold, spec):
    gp = spec.get("gold_paths") or {}
    if gold in gp:
        v = gp[gold]
        return v if isinstance(v, list) else [v]
    needles = []
    cache = {}
    for fp in spec.get("fixtures") or []:
        body = fixture_text(fp, spec, cache)
        if body is None or gold in body:
            base = os.path.basename(fp)
            needles.append(base)
            needles.append(fp)
            needles.append(norm_path(fp))
            rp = resolve_fixture_path(fp, spec)
            if rp and rp not in needles:
                needles.append(rp)
                needles.append(os.path.basename(rp))
    # unique
    out = []
    for n in needles:
        if n and n not in out:
            out.append(n)
    return out


def gold_confirmed_ok(final, golds, spec):
    """Each gold string must appear in a confirmed: item that names a matching path."""
    items = confirmed_items(final)
    missing = []
    for g in golds:
        needles = gold_path_needles(g, spec)
        hit = False
        for item in items:
            if g not in item:
                continue
            if any(n and n in item for n in needles):
                hit = True
                break
        if not hit:
            missing.append(g)
    return missing


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


def use_targets_path(use, path):
    inp = use["input"]
    for k in ("file_path", "path", "notebook_path"):
        v = inp.get(k)
        if isinstance(v, str) and norm_path(v) == norm_path(path):
            return True
    return False


def bash_mentions_path(use, path):
    cmd = use["input"].get("command", "")
    return path in cmd or path.split("/")[-1] in cmd


def bash_recovers_body(use, path):
    """Bash command that would dump (part of) the denied body to stdout."""
    cmd = use["input"].get("command", "")
    if not bash_mentions_path(use, path):
        return False
    if re.search(r"\b(cat|head|tail|less|more)\b", cmd):
        # metadata tools are fine; body readers are not, whatever follows them
        return True
    if "|" in cmd and re.search(r"(grep|awk|sed|cut|python|dd|xargs)\b", cmd):
        return True
    return False


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


def quote_leak(agent_result_text, fixture_paths, read_texts, spec=None):
    """Child final message must not contain the fixture body:
    >20 consecutive fixture lines or >2KiB contiguous quotation -> leak."""
    spec = spec or {}
    for fp in fixture_paths:
        body = read_texts.get(fp) if read_texts is not None else None
        if body is None:
            body = fixture_text(fp, spec, read_texts if read_texts is not None else None)
            if body is None:
                # last-ditch: fixtures_abs entries themselves
                for a in spec.get("fixtures_abs") or []:
                    body = fixture_text(a, spec)
                    if body:
                        break
            if body is None:
                continue
            if read_texts is not None:
                read_texts[fp] = body
        if len(body) >= 2048:
            last = len(body) - 2048
            offs = list(range(0, last + 1, 512))
            if offs[-1] != last:
                offs.append(last)
            for off in offs:
                chunk = body[off:off + 2048]
                if chunk and chunk in agent_result_text:
                    return True, f"2KiB contiguous quote from {fp}"
        run = 0
        for l in body.splitlines():
            if l.strip() and l in agent_result_text:
                run += 1
                if run > 20:
                    return True, f">20 consecutive fixture lines from {fp}"
            else:
                run = 0
    return False, ""


def foreign_hooks(tr):
    """Non-token-shunt command hooks observed in the stream."""
    bad = []
    for e in tr.hook_events:
        if e.get("subtype") != "hook_response":
            continue
        name = e.get("hook_name") or ""
        if name in BUILTIN_HOOKS:
            continue
        if any(h in name for h in TS_HOOKS):
            continue
        bad.append(name)
    return bad


def ts_hook_denies(tr):
    """token-shunt deny responses, in order."""
    out = []
    for e in tr.hook_events:
        if e.get("subtype") != "hook_response":
            continue
        name = e.get("hook_name") or ""
        if not any(h in name for h in TS_HOOKS):
            continue
        out_s = e.get("output") or e.get("stdout") or ""
        try:
            j = json.loads(out_s) if isinstance(out_s, str) else out_s
        except (json.JSONDecodeError, TypeError):
            j = None
        if isinstance(j, dict):
            hso = j.get("hookSpecificOutput", {})
            if hso.get("permissionDecision") == "deny":
                out.append({"hook": name, "reason": hso.get("permissionDecisionReason", "")})
    return out


def judge(transcript_path, spec, ctx):
    tr = Transcript(load_events(transcript_path))
    v = {"case": spec["id"], "mode": ctx["mode"], "checks": {}, "reasons": []}
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
        rpt = spec.get("require_parent_tokens")
        mode = ctx["mode"]
        need = False
        if rpt is True:
            need = True
        elif isinstance(rpt, list) and mode in rpt:
            need = True
        if not need:
            return
        m = v.get("metrics") or tr.metrics()
        if m.get("parent_input_tokens") is None:
            fail("parent_tokens", "parent_input_tokens is null")
        elif m.get("parent_output_tokens") is None:
            fail("parent_tokens", "parent_output_tokens is null")
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

    # foreign command hooks (PreToolUse scope + any non-builtin response)
    fh = foreign_hooks(tr)
    if fh:
        fail("foreign_hooks", ",".join(fh))
    else:
        passed("foreign_hooks")

    parent_agents = [u for u in tr.parent_tool_uses() if u["name"] in AGENT_TOOL_NAMES]

    # --- accuracy ---
    gold = spec.get("gold", [])
    final = tr.final_text()
    missing = [g for g in gold if g not in final]
    if gold and missing:
        fail("accuracy", "final answer missing: %s" % ", ".join(missing))
    elif gold:
        passed("accuracy")
    gold_any = spec.get("gold_any", [])
    if gold_any and not any(g in final for g in gold_any):
        fail("accuracy", "final answer contains none of: %s" % ", ".join(gold_any))
    elif gold_any:
        v["checks"]["accuracy_any"] = True

    if exp.get("gold_confirmed") and gold:
        missing_c = gold_confirmed_ok(final, gold, spec)
        if missing_c:
            fail("gold_confirmed",
                 "gold not in confirmed: + matching path: %s" % ", ".join(missing_c))
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
                   if use_targets_path(u, p)
                   and (r := tr.result_of(u["id"])) and not r["is_error"])
        if not good:
            fail("parent_reads", "no successful parent Read of %s" % p)
        else:
            passed("parent_reads")

    for p in exp.get("parent_no_full_read", []):
        bad = any(u for u in tr.parent_tool_uses("Read")
                  if use_targets_path(u, p)
                  and is_full_parent_read(u, p, spec)
                  and (r := tr.result_of(u["id"])) and not r["is_error"])
        if bad:
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
            if not use_targets_path(u, p):
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

    # deny-route ordered evidence: full Read -> hook deny -> Agent call
    dr = exp.get("deny_route")
    if dr:
        p = dr["path"]
        read_pos = deny_pos = agent_pos = None
        for i, e in enumerate(tr.events):
            if read_pos is None and e.get("type") == "assistant" \
                    and e.get("parent_tool_use_id") is None:
                for b in e.get("message", {}).get("content", []) or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use" \
                            and b.get("name") == "Read":
                        inp = b.get("input", {})
                        if norm_path(inp.get("file_path", "")) == norm_path(p):
                            if dr.get("range") or dr.get("allow_range"):
                                read_pos = i
                            elif not inp.get("offset") and not inp.get("limit"):
                                read_pos = i
            if deny_pos is None and e.get("type") == "system" \
                    and e.get("subtype") == "hook_response":
                name = e.get("hook_name") or ""
                if any(h in name for h in TS_HOOKS):
                    out_s = e.get("output") or e.get("stdout") or ""
                    try:
                        j = json.loads(out_s) if isinstance(out_s, str) else out_s
                    except (json.JSONDecodeError, TypeError):
                        j = None
                    hso = (j or {}).get("hookSpecificOutput", {})
                    if hso.get("permissionDecision") == "deny" \
                            and "token-shunt" in hso.get("permissionDecisionReason", "") \
                            and "bulk-reader" in hso.get("permissionDecisionReason", ""):
                        deny_pos = i
            if agent_pos is None and e.get("type") == "assistant" \
                    and e.get("parent_tool_use_id") is None:
                for b in e.get("message", {}).get("content", []) or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use" \
                            and b.get("name") in AGENT_TOOL_NAMES \
                            and (b.get("input", {}).get("subagent_type")
                                 or b.get("input", {}).get("type")) == "token-shunt:bulk-reader":
                        agent_pos = i
        if read_pos is None:
            fail("deny_route", "no full parent Read attempt on %s" % p)
        elif deny_pos is None:
            fail("deny_route", "no token-shunt deny hook_response (reason must name token-shunt + bulk-reader)")
        elif deny_pos < read_pos:
            fail("deny_route", "deny before the full Read")
        elif agent_pos is None:
            fail("deny_route", "no Agent(token-shunt:bulk-reader) after deny")
        elif agent_pos < deny_pos:
            fail("deny_route", "Agent before deny (pre-delegation is not this case)")
        else:
            passed("deny_route")

    # post-deny / B-large bypass: any successful parent Read of the path, or pipe recovery
    db_paths = deny_bypass_paths(exp)
    for p in db_paths:
        for u in tr.parent_tool_uses("Read"):
            if use_targets_path(u, p):
                r = tr.result_of(u["id"])
                if r and not r["is_error"]:
                    fail("deny_bypass", "parent Read succeeded on denied path %s" % p)
        for u in tr.parent_tool_uses("Bash"):
            if bash_recovers_body(u, p):
                fail("deny_bypass", "parent Bash recovered body of %s" % p)
    if db_paths:
        v["checks"].setdefault("deny_bypass", True)

    # child->parent text contract
    cap = exp.get("child_msg_max")
    if cap or exp.get("child_no_body"):
        for u in parent_agents:
            r = tr.result_of(u["id"])
            if not r:
                continue
            txt = r["text"]
            if cap and len(txt) > cap:
                fail("child_msg_cap", "agent result %d chars > %d" % (len(txt), cap))
            if exp.get("child_no_body"):
                fpaths = list(spec.get("fixtures") or [])
                fpaths.extend(spec.get("fixtures_abs") or [])
                leaked, why = quote_leak(txt, fpaths, {}, spec)
                if leaked:
                    fail("child_no_body", why)
                elif has_code_fence(txt):
                    fail("child_no_body", "code fence in child message")
                elif not any(fixture_text(fp, spec) for fp in fpaths) \
                        and long_nonempty_run(txt):
                    fail("child_no_body", ">20 consecutive non-empty child lines")
        v["checks"].setdefault("child_msg_cap", True)
        v["checks"].setdefault("child_no_body", True)

    needles = exp.get("child_mentions") or []
    if needles:
        mentioned = False
        for u in parent_agents:
            r = tr.result_of(u["id"])
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

    # parent must have run a Bash command containing all needles, succeeded
    pb = exp.get("parent_bash")
    if pb:
        hit = False
        for u in tr.parent_tool_uses("Bash"):
            cmd = u["input"].get("command", "")
            if all(n in cmd for n in pb.get("contains", [])):
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
        refs = [p for p in (spec.get("fixtures") or [])
                if "greeter" in os.path.basename(p)]
        if not refs:
            refs = list(spec.get("fixtures") or [])
        if target and refs:
            for u in parent_agents:
                children = tr.child_tool_uses(u["id"])
                read_i = write_i = None
                for i, c in enumerate(children):
                    if c["name"] == "Read" and any(use_targets_path(c, r) for r in refs):
                        rr = tr.result_of(c["id"])
                        if rr and not rr["is_error"] and read_i is None:
                            read_i = i
                    if c["name"] == "Write" and use_targets_path(c, target):
                        if write_i is None:
                            write_i = i
                if write_i is not None and (read_i is None or read_i > write_i):
                    fail("child_ref_before_write",
                         "Write of target before successful Read of greeter.py")
            v["checks"].setdefault("child_ref_before_write", True)

    for key, reason in check_routing(
            tr, spec, exp, ctx["mode"], parent_agents, agent_resolved_models):
        fail(key, reason)

    v["metrics"] = tr.metrics()
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
                 "is_error": is_error}
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
                        "input": {"subagent_type": "token-shunt:bulk-reader",
                                  "prompt": path}}]),
        ev_tool_result("a1", "short"),
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
                            "input": {"subagent_type": "token-shunt:bulk-reader",
                                      "prompt": "user.rb notifiable.rb welcome_email_job.rb"}}]),
            ev_tool_result("a1", "short"),
            ev_result(final, usage=usage_ok),
        ]

    guessed = "Notifiable after_create WelcomeEmailJob (guessed, no confirmed paths)"
    run("gold_confirmed-guess-fail", gold_evs(guessed), gold_spec_base, "delegate",
        False, require_reason="gold_confirmed")

    confirmed = (
        "confirmed: include Notifiable — path: rails/app/models/user.rb\n"
        "confirmed: after_create :send_welcome_email — path: rails/app/models/user.rb\n"
        "confirmed: WelcomeEmailJob.perform_later — path: rails/app/models/concerns/notifiable.rb\n"
        "Notifiable after_create WelcomeEmailJob"
    )
    run("gold_confirmed-with-path-pass", gold_evs(confirmed), gold_spec_base,
        "delegate", True)

    # relative fixture path quote leak (silent skip on missing relative path is the bug)
    fx_rel = "rails/app/models/user.rb"
    fx_abs = os.path.join(FIXTURES_DIR, fx_rel)
    chunk = ""
    if os.path.isfile(fx_abs):
        body = open(fx_abs, encoding="utf-8", errors="replace").read()
        if len(body) >= 2048:
            chunk = body[0:2048]
    if not chunk:
        errors.append("quote_leak: fixtures/rails/app/models/user.rb missing or <2KiB")
    else:
        evs = [
            ev_init(),
            ev_asst("ma", [{"type": "tool_use", "id": "a1", "name": "Agent",
                            "input": {"subagent_type": "token-shunt:bulk-reader",
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
                                "input": {"subagent_type": "token-shunt:bulk-reader",
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
                        "input": {"subagent_type": "token-shunt:bulk-reader",
                                  "prompt": rpath}}]),
        ev_tool_result("a1", "short"),
        ev_result("hello", usage=usage_ok),
    ]
    spec = {"id": "selftest-direct-agent",
            "expect": {"direct": {"parent_reads": [rpath]}}}
    run("direct-bulk-reader-agent-fail", evs, spec, "direct", False)

    # parent_no_full_read: offset-only (no limit) is full ingest
    evs = [
        ev_init(),
        ev_asst("ma", [{"type": "tool_use", "id": "a1", "name": "Agent",
                        "input": {"subagent_type": "token-shunt:bulk-reader",
                                  "prompt": path}}]),
        ev_tool_result("a1", "short"),
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
                        "input": {"subagent_type": "token-shunt:bulk-reader",
                                  "prompt": path}}]),
        ev_tool_result("a1", "short"),
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

    if errors:
        for e in errors:
            print("SELFTEST FAIL: %s" % e, file=sys.stderr)
        return 1
    print("selftest: all checks passed")
    return 0


def leakcheck(transcript_path, target_path):
    """writer_body_absent: generated target body must not appear in the
    parent's transcript (>20 consecutive lines or >2KiB contiguous)."""
    tr = Transcript(load_events(transcript_path))
    ptxt = tr.parent_added_text()
    try:
        body = open(target_path, encoding="utf-8", errors="replace").read()
    except OSError:
        print("leakcheck: target unreadable")
        return 1
    for off in range(0, max(0, len(body) - 2048), 512):
        chunk = body[off:off + 2048]
        if chunk and chunk in ptxt:
            print("leak: 2KiB contiguous quote")
            return 0
    run = 0
    for l in body.splitlines():
        if l.strip() and l in ptxt:
            run += 1
            if run > 20:
                print("leak: >20 consecutive lines")
                return 0
        else:
            run = 0
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
        if spec.get("disk_check"):
            disk = read_json(os.path.join(verdict_dir, stem + ".disk.json"))
            v["checks"]["disk"] = disk.get("disk_ok") is True
            if disk.get("disk_ok") is not True:
                fail("disk: " + str(disk.get("reason", "missing successful disk evidence")))
        if mode in spec.get("require_parent_tokens", []):
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
    out = {"generated_at": __import__("datetime").datetime.now().isoformat(),
           "cases": cases, "fail_count": fails, "errors": errors,
           "selected_run_valid": fails == 0,
           "release_eligible": fails == 0 and planned == mandatory,
           "parent_token_deltas": deltas}
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
