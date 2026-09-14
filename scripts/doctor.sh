#!/usr/bin/env bash
# token-shunt doctor (design §14): install-time sanity checks.
#   - jq on PATH (required; hooks fail-closed without it)
#   - CLAUDE_CODE_SUBAGENT_MODEL_FORCE warning (overrides worker model choice)
#   - claude --version when present (record the probed CLI; no numeric pin)
#   - plugin load probe: note whether token-shunt agents registered
#   - worker probes: requested vs actual model (haiku/sonnet), effort,
#     maxTurns partial termination
#   - records the probed CLI version (design §7); never a pin in plugin.json
#   - hook-stdin dump: how-to only; a live delegated session is not a
#     doctor fail (org auth may be off)
# Live checks print "unconfirmed" and do NOT change the exit code: only a
# missing jq, Bash < 4, or failure to save a confirmed probe is a hard fail.
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$PWD
fail=0
plugin_probe_ok=0
have_claude=0
command -v claude >/dev/null 2>&1 && have_claude=1

printf '== Bash ==\n'
if (( BASH_VERSINFO[0] < 4 )); then
  printf 'Bash >= 4 required; found %s\n' "$BASH_VERSION"; fail=1
else
  printf 'Bash: %s\n' "$BASH_VERSION"
fi

printf '== jq ==\n'
if command -v jq >/dev/null 2>&1; then
  printf 'jq: %s\n' "$(command -v jq)"
else
  printf 'MISSING jq — hooks will exit 2 on every Read/Bash/Agent\n'; fail=1
fi

printf '== claude ==\n'
if [[ $have_claude -eq 1 ]]; then
  claude --version 2>/dev/null || printf 'claude present; --version failed\n'
else
  printf 'claude CLI missing — compare evals will skip, release blocked\n'
fi

printf '== model force ==\n'
if [[ ${CLAUDE_CODE_SUBAGENT_MODEL_FORCE:-0} == 1 ]]; then
  printf 'CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1 — worker model selection is overridden\n'
else
  printf 'ok\n'
fi

printf '== plugin load probe ==\n'
if [[ $have_claude -eq 1 ]]; then
  tmp=$(mktemp -d)
  (cd "$tmp" && printf 'Reply with just OK' | timeout 120 claude -p \
      --output-format stream-json --verbose --setting-sources "" \
      --plugin-dir "$ROOT/plugin" >"$tmp/stream.jsonl" 2>/dev/null)
  python3 - "$tmp/stream.jsonl" "$tmp/verdict" <<'PY'
import json, os, sys
path, verdict = sys.argv[1], sys.argv[2]
init = {}
if not os.path.exists(path) or os.path.getsize(path) == 0:
    print("plugin-load stream empty — agents not confirmed (auth may be off)")
    raise SystemExit(0)
for line in open(path):
    try:
        e = json.loads(line)
    except json.JSONDecodeError:
        continue
    if e.get("type") == "system" and e.get("subtype") == "init":
        init = e
if not init:
    print("no system/init in stream — agents not confirmed (auth may be off)")
    raise SystemExit(0)
plugs = [p.get("name") for p in init.get("plugins", []) or []]
agents = init.get("agents", []) or []
loaded = "token-shunt" in plugs and not init.get("plugin_errors")
if loaded:
    print("plugin loaded")
else:
    print("PLUGIN LOAD FAIL plugins=%s errors=%s" % (plugs, init.get("plugin_errors")))
missing = [a for a in ("token-shunt:bulk-reader", "token-shunt:code-writer") if a not in agents]
for a in ("token-shunt:bulk-reader", "token-shunt:code-writer"):
    print(("agent ok: " if a in agents else "AGENT MISSING: ") + a)
if loaded and not missing:
    open(verdict, "w").write("ok\n")
PY
  [[ -s "$tmp/verdict" ]] && plugin_probe_ok=1
  rm -rf "$tmp"
else
  printf 'skipped — claude CLI missing\n'
fi

printf '== model resolution / effort / maxTurns (needs auth) ==\n'
model_probe_ok=0
if [[ $have_claude -eq 1 ]]; then
  if [[ ${CLAUDE_CODE_SUBAGENT_MODEL_FORCE:-0} == 1 ]]; then
    printf 'CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1 — requested/actual model comparison is INVALID (forced override); probes below are informational only\n'
  fi
  ptmp=$(mktemp -d)
  printf 'alpha\nbeta\ngamma\n' > "$ptmp/sample.txt"
  probe_verdicts="$ptmp/verdicts"
  : > "$probe_verdicts"
  for alias in haiku sonnet; do
    printf -- '-- requested worker model: %s --\n' "$alias"
    (cd "$ptmp" && printf 'Use the Agent/Task tool exactly once with subagent_type "token-shunt:bulk-reader" and model "%s" to read %s and report the three words it contains. Then reply DONE.' \
        "$alias" "$ptmp/sample.txt" \
      | timeout 80 claude -p --output-format stream-json --verbose --setting-sources "" \
          --plugin-dir "$ROOT/plugin" --allowedTools "Task" \
          >"$ptmp/$alias.jsonl" 2>/dev/null)
    python3 - "$ptmp/$alias.jsonl" "$alias" "$probe_verdicts" <<'PY'
import json, os, sys
path, alias, verdicts = sys.argv[1], sys.argv[2], sys.argv[3]

def note(ok, text):
    print(text)
    with open(verdicts, "a") as fh:
        fh.write("%s %s\n" % ("ok" if ok else "unconfirmed", alias))

if not os.path.exists(path) or os.path.getsize(path) == 0:
    note(False, "unconfirmed — empty stream (auth/model access may be off); not a doctor failure")
    raise SystemExit(0)

raw = open(path, encoding="utf-8", errors="replace").read()
events = []
for line in raw.splitlines():
    try:
        events.append(json.loads(line))
    except json.JSONDecodeError:
        continue

def find_key(node, key, out):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                out.append(v)
            find_key(v, key, out)
    elif isinstance(node, list):
        for v in node:
            find_key(v, key, out)

# 1. requested vs actual worker model
resolved = []
for e in events:
    find_key(e, "resolvedModel", resolved)
    find_key(e, "modelsUsed", resolved)
child_ids = set()
for e in events:
    if e.get("type") == "assistant" and e.get("parent_tool_use_id"):
        m = (e.get("message") or {}).get("model")
        if m:
            child_ids.add(m)
result = next((e for e in events if e.get("type") == "result"), {})
usage_models = sorted((result.get("modelUsage") or {}).keys())
spawned = ((result.get("subagent_stats") or {}).get("by_type") or {})

if resolved:
    print("resolvedModel/modelsUsed: %s" % json.dumps(resolved)[:300])
if not spawned.get("token-shunt:bulk-reader"):
    note(False, "unconfirmed — no token-shunt:bulk-reader subagent was spawned (parent may have refused or model is not available)")
    raise SystemExit(0)
if not child_ids:
    note(False, "unconfirmed — subagent spawned but no child assistant model observed")
    raise SystemExit(0)

actual = sorted(child_ids)
print("worker model actually used: %s" % ", ".join(actual))
if usage_models:
    print("result.modelUsage models: %s" % ", ".join(usage_models))
match = all(alias in m for m in actual)
if os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE") == "1":
    print("requested %s vs actual %s — comparison INVALID under FORCE=1" % (alias, ", ".join(actual)))
elif match:
    print("model resolution ok: requested %s -> %s" % (alias, ", ".join(actual)))
else:
    print("MODEL MISMATCH: requested %s but worker ran %s" % (alias, ", ".join(actual)))

# 2. effort
efforts = []
for e in events:
    find_key(e, "effort", efforts)
if efforts:
    print("effort observed in stream: %s" % json.dumps(efforts)[:200])
else:
    print("effort: not observable on this CLI (no effort field in the stream)")

# 3. maxTurns / partial termination
statuses = [e.get("patch", {}).get("status") for e in events
            if e.get("subtype") == "task_updated" and isinstance(e.get("patch"), dict)]
summaries = [e.get("summary", "") for e in events if e.get("subtype") == "task_notification"]
final_child = summaries[-1] if summaries else ""
low = final_child.lower()
print("subagent task status: %s" % (", ".join(s for s in statuses if s) or "not reported"))
if "status:" in low or "stop_reason" in low:
    keep = [ln for ln in final_child.splitlines()
            if "status:" in ln.lower() or "stop_reason" in ln.lower()]
    print("child reported turn contract: %s" % " | ".join(k.strip() for k in keep)[:200])
else:
    print("child final message carried no status/stop_reason line")
if any(s in ("failed", "killed") for s in statuses if s):
    print("maxTurns: subagent stopped early — check the line above for partial/stop_reason")
else:
    print("maxTurns: turn limit not reached by this probe; partial-on-turn-limit stays unconfirmed here")
note(True, "probe completed")
PY
  done
  if [[ -s $probe_verdicts ]] && ! grep -q '^unconfirmed' "$probe_verdicts" \
     && [[ $(grep -c '^ok' "$probe_verdicts") -eq 2 ]]; then
    model_probe_ok=1
  fi
  rm -rf "$ptmp"
else
  printf 'skipped — claude CLI missing\n'
fi

printf '== minimum supported version record ==\n'
record="$ROOT/docs/distribution/doctor-last-probe.txt"
if [[ $have_claude -eq 1 && $plugin_probe_ok -eq 1 ]]; then
  ver=$(claude --version 2>/dev/null | head -1)
  [[ -n ${ver:-} ]] || ver="unknown"
  if [[ ${CLAUDE_CODE_SUBAGENT_MODEL_FORCE:-0} == 1 ]]; then
    model_record='worker model resolution (haiku/sonnet): not comparable (CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1)'
  elif [[ $model_probe_ok -eq 1 ]]; then
    model_record='worker model resolution (haiku/sonnet): probed — see doctor output for match/mismatch'
  else
    model_record='worker model resolution (haiku/sonnet): unconfirmed on this run'
  fi
  record_tmp=""
  if mkdir -p "$(dirname "$record")" && record_tmp=$(mktemp "${record}.XXXXXX"); then
    if printf '%s\n' \
      'token-shunt doctor probe record (design §7: record the minimum supported version at implementation time)' \
      "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      "claude --version: $ver" \
      'plugin + agent registration: confirmed' \
      "$model_record" \
      'agent_type on PreToolUse stdin: confirm manually (see the hook stdin section)' \
      'This file is a probe log, not a version pin. Do not copy a numeric floor into plugin.json.' \
      > "$record_tmp" && [[ ! -d $record ]] && mv -f -- "$record_tmp" "$record"; then
      printf 'recorded probed CLI version in %s\n' "$record"
    else
      printf 'ERROR: could not save probe record in %s\n' "$record" >&2
      rm -f -- "$record_tmp"
      fail=1
    fi
  else
    printf 'ERROR: could not prepare probe record in %s\n' "$record" >&2
    fail=1
  fi
else
  printf 'unconfirmed — no successful plugin-load probe, nothing recorded\n'
fi

printf '== hook stdin (needs auth) ==\n'
cat <<'EOF'
To confirm the bulk-reader runtime contract, add temporary Read debug hooks
for PreToolUse, PostToolUse, and PostToolUseFailure that capture stdin to
private files (for example `umask 077; cat > /tmp/ts-hook-stdin.json`, using
a distinct file per event). Run a delegated session and confirm top-level
agent_type is exactly "token-shunt:bulk-reader" and session_id, agent_id,
tool_use_id, hook_event_name, and object tool_input are present. Matching
Pre/Post/Failure events must use the same tool_use_id. Successful text Reads
must include tool_response.type="text" and integer fields in
 tool_response.file: startLine, numLines, totalLines.
The reader contract needs session_id and agent_id only for this exact worker
agent_type. Missing worker identity cannot establish compatibility; missing
required IDs for a recognized worker cause fail-closed exit 2.
Remove the debug hook and captured payload afterward.

TOKEN_SHUNT_HOOK_LOG records decisions only, not stdin; it cannot verify
these stdin fields. Payloads may contain source paths and tool arguments.

A missing dump is not a doctor failure (org auth may be off). Do not treat
an incomplete live Agent session as a hard fail.
EOF

exit $fail
