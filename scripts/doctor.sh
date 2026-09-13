#!/usr/bin/env bash
# token-shunt doctor (design §14): install-time sanity checks.
#   - jq on PATH (required; hooks fail-closed without it)
#   - CLAUDE_CODE_SUBAGENT_MODEL_FORCE warning (overrides worker model choice)
#   - claude --version when present (record the probed CLI; no numeric pin)
#   - plugin load probe: note whether token-shunt agents registered
#   - hook-stdin dump: how-to only; a live delegated session is not a
#     doctor fail (org auth may be off)
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$PWD
fail=0
have_claude=0
command -v claude >/dev/null 2>&1 && have_claude=1

printf '== jq ==\n'
if command -v jq >/dev/null 2>&1; then
  printf 'jq: %s\n' "$(command -v jq)"
else
  printf 'MISSING jq — hooks will exit 2 on every Read/Bash\n'; fail=1
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
  python3 - "$tmp/stream.jsonl" <<'PY'
import json, os, sys
path = sys.argv[1]
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
if "token-shunt" in plugs and not init.get("plugin_errors"):
    print("plugin loaded")
else:
    print("PLUGIN LOAD FAIL plugins=%s errors=%s" % (plugs, init.get("plugin_errors")))
for a in ("token-shunt:bulk-reader", "token-shunt:code-writer"):
    print(("agent ok: " if a in agents else "AGENT MISSING: ") + a)
PY
  rm -rf "$tmp"
else
  printf 'skipped — claude CLI missing\n'
fi

printf '== hook stdin (needs auth) ==\n'
cat <<'EOF'
To confirm your Claude Code puts `agent_type` on the PreToolUse hook stdin,
run a delegated session once and inspect a captured hook payload, e.g.:

  TOKEN_SHUNT_HOOK_LOG=/tmp/ts-hooks.jsonl \
  claude --plugin-dir plugin/ -p "use /token-shunt:bulk-reader on a large file"

then check the captured stdin (or add a temporary debug hook that does
`cat > /tmp/hook-stdin.json`) and confirm a top-level "agent_type" field
appears on worker invocations.

A missing dump is not a doctor failure (org auth may be off). Do not treat
an incomplete live Agent session as a hard fail.
EOF

exit $fail
