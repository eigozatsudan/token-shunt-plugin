#!/usr/bin/env python3
"""Cost-structure probe (not part of the release gate).

Three conditions on the same fixtures and the same parent model:
  direct  - no plugin; the parent reads and answers itself
  bare    - plugin loaded for agent registration only; exactly one Agent call,
            no skill, no metadata probing
  skill   - the shipped skill protocol with an explicit worker model

Separates "cost of delegating at all" from "cost of the skill's protocol".
Writes tmp/cost-probe/<stamp>/{transcripts,report.json}.
"""
import json, os, shutil, subprocess, sys, time

CMP = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(CMP))
WM = "haiku"

COMMON = ["-p", "--output-format", "stream-json", "--verbose",
          "--include-hook-events", "--forward-subagent-text",
          "--model", "sonnet", "--permission-mode", "acceptEdits",
          "--allowedTools", "Read,Edit,Grep,Glob,Agent,Task,Write,Bash"]

BARE_READER = (
    " Do not read, Grep or open the files yourself and do not use the"
    " token-shunt:bulk-reader skill. Do not run any metadata commands"
    " (no stat, wc, awk, ls). Make exactly one Agent call with"
    " subagent_type=\"token-shunt:bulk-reader\" and model=\"%s\", passing the"
    " listed paths and the question in its prompt, then answer from the"
    " worker's reply." % WM)
BARE_WRITER = (
    " Do not write the module yourself and do not use the token-shunt:code-writer"
    " skill. Do not run any metadata commands (no stat, wc, awk, ls). Make exactly"
    " one Agent call with subagent_type=\"token-shunt:code-writer\" and"
    " model=\"%s\", passing the reference path, the target path and the spec in its"
    " prompt. Then run the verification command yourself and report the result."
    % WM)

CASES = ["auto-bulk-facts", "auto-one-line", "auto-explicit-multifile",
         "auto-large-writer"]


def load_cases(selected=CASES):
    with open(os.path.join(CMP, "cases.json"), encoding="utf-8") as fh:
        catalog = json.load(fh)
    return {c["id"]: c for c in catalog["cases"] if c["id"] in selected}


def newest_fixture_dir():
    runs = os.path.join(CMP, "tmp", "runs")
    best = None
    for name in os.listdir(runs):
        fix = os.path.join(runs, name, "work", "fixtures")
        if os.path.isdir(fix) and os.path.isdir(os.path.join(fix, "gen")):
            mtime = os.path.getmtime(fix)
            if best is None or mtime > best[0]:
                best = (mtime, fix)
    if best is None:
        sys.exit("no retained fixture tree under tmp/runs/*/work/fixtures; run run.sh first")
    return best[1]


def prompt_for(case, cond, fix, tmp):
    if cond == "direct":
        text = case["prompt_direct"]
    elif cond == "skill":
        text = case["prompt_delegate"].replace(
            "{WMHINT}", case.get("wm_hint", "").replace("{WM}", WM))
    else:
        base = case["prompt_delegate"].replace("{WMHINT}", "")
        text = base + (BARE_WRITER if "writer" in case["id"] else BARE_READER)
    return text.replace("{FIX}", fix).replace("{TMP}", tmp).replace("{JUDGE_DIR}", CMP)


def run_one(case, cond, fix, tmp, cwd, out_path):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("TOKEN_SHUNT_") and k != "CDPATH"}
    env["TOKEN_SHUNT_EVAL_FIXTURES"] = fix
    env["CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS"] = str(
        case.get("read_max_output_tokens", 25000))
    argv = ["claude"] + COMMON + ["--setting-sources", "", "--add-dir", fix,
                                  "--add-dir", tmp]
    if cond != "direct":
        argv += ["--plugin-dir", os.path.join(ROOT, "plugin")]
        env["TOKEN_SHUNT_HOOK_LOG"] = out_path + ".hooklog"
    started = time.time()
    with open(out_path, "wb") as out, open(out_path + ".err", "wb") as err:
        rc = subprocess.run(argv, input=prompt_for(case, cond, fix, tmp).encode(),
                            stdout=out, stderr=err, cwd=cwd, env=env,
                            timeout=900).returncode
    return rc, time.time() - started


def metrics(path, hooklog=None):
    turns = child_turns = agent_calls = parent_reads = parent_bash = 0
    skill_loads = 0
    result = None
    # None = not measured. Only an existing log can assert "no denies".
    deny_count = deny_bytes = None
    hooklog_status = "not_applicable" if not hooklog else "missing"
    if hooklog and os.path.exists(hooklog):
        hooklog_status = "ok"
        deny_count = deny_bytes = 0
        with open(hooklog, encoding="utf-8") as fh:
            for line in fh:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("decision") == "deny":
                    deny_count += 1
                    deny_bytes += len((record.get("reason") or "").encode("utf-8"))
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "assistant":
                # Subagent messages carry parent_tool_use_id; only count the parent.
                if event.get("parent_tool_use_id"):
                    child_turns += 1
                    continue
                turns += 1
                for block in event.get("message", {}).get("content", []) or []:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    name = block.get("name")
                    if name in ("Agent", "Task"):
                        agent_calls += 1
                    elif name == "Skill":
                        skill_loads += 1
                    elif name == "Read":
                        parent_reads += 1
                        args = block.get("input") or {}
                        if str(args.get("file_path", "")).endswith(
                                "skills/bulk-reader/SKILL.md"):
                            skill_loads += 1
                    elif name == "Bash":
                        parent_bash += 1
            elif event.get("type") == "result":
                result = event
    if result is None:
        return {"ok": False, "reason": "missing final result",
                "skill_loads": 0, "deny_count": deny_count,
                "deny_bytes": deny_bytes, "hooklog": hooklog_status}
    usage = result.get("usage") or {}
    by_model = {}
    for model, u in (result.get("modelUsage") or {}).items():
        by_model[model] = round(u.get("costUSD", 0), 6)
    return {"ok": result.get("is_error") is False,
            "cost_usd": result.get("total_cost_usd"),
            "cost_by_model": by_model,
            "parent_turns": turns, "child_turns": child_turns,
            "agent_calls": agent_calls,
            "parent_reads": parent_reads, "parent_bash": parent_bash,
            "skill_loads": skill_loads,
            "deny_count": deny_count, "deny_bytes": deny_bytes,
            "hooklog": hooklog_status,
            "parent_uncached": usage.get("input_tokens"),
            "parent_cache_read": usage.get("cache_read_input_tokens"),
            "parent_cache_creation": usage.get("cache_creation_input_tokens"),
            "parent_output": usage.get("output_tokens"),
            "num_turns": result.get("num_turns"),
            "stop_reason": result.get("stop_reason"),
            "answer": (result.get("result") or "")[-400:]}


def main():
    repeats = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    selected = sys.argv[2:] or CASES
    unknown = [c for c in selected if c not in CASES]
    if unknown:
        sys.exit("unknown case ids: %s" % ", ".join(unknown))
    cases = load_cases(selected)
    source_fix = newest_fixture_dir()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    root = os.path.join(CMP, "tmp", "cost-probe", stamp)
    tdir = os.path.join(root, "transcripts")
    os.makedirs(tdir)
    fix = os.path.join(root, "fixtures")
    shutil.copytree(source_fix, fix)
    print("fixtures copied from", source_fix)
    rows = []
    for rep in range(1, repeats + 1):
        for cid in selected:
            for cond in ("direct", "bare", "skill"):
                tmp = os.path.join(root, "work", "%s.%s.%d" % (cid, cond, rep))
                cwd = os.path.join(tmp, "cwd")
                os.makedirs(cwd)
                out = os.path.join(tdir, "%s.%s.%d.jsonl" % (cid, cond, rep))
                rc, secs = run_one(cases[cid], cond, fix, tmp, cwd, out)
                row = {"case": cid, "cond": cond, "rep": rep, "cli_exit": rc,
                       "wall_s": round(secs, 1)}
                hooklog = None if cond == "direct" else out + ".hooklog"
                row.update(metrics(out, hooklog))
                rows.append(row)
                print("%-26s %-6s rep%d exit=%d %5.1fs cost=%s pturns=%s/%s agents=%s reads=%s bash=%s "
                      "skill=%s deny=%s/%sB(%s) ok=%s"
                      % (cid, cond, rep, rc, secs, row.get("cost_usd"),
                         row.get("parent_turns"), row.get("child_turns"), row.get("agent_calls"),
                         row.get("parent_reads"), row.get("parent_bash"),
                         row.get("skill_loads"), row.get("deny_count"), row.get("deny_bytes"),
                         row.get("hooklog"),
                         row.get("ok")))
                with open(os.path.join(root, "report.json"), "w", encoding="utf-8") as fh:
                    json.dump({"stamp": stamp, "worker_model": WM,
                               "source_fixtures": source_fix, "rows": rows}, fh, indent=2)
    print("report:", os.path.join(root, "report.json"))


if __name__ == "__main__":
    main()
