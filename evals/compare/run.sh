#!/usr/bin/env bash
# token-shunt real-machine compare eval (design §13, §26.5).
# Direct mode never loads token-shunt; delegate modes load --plugin-dir.
# Isolation on this CLI: --setting-sources "" + clean cwd (NOT --bare: 2.1.x
# keeps enabled marketplace plugins and skips plugin-agent registration).
set -u
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
CMP=$PWD
ROOT=$(cd ../.. && pwd)
SOURCE_FIX=$CMP/fixtures
RUN_ROOT=''
LASTRUN=$CMP/last-run.json
TIMEOUT=${TOKEN_SHUNT_CASE_TIMEOUT:-600}
ONLY=${1:-}
SUITE=${SUITE:-}

say() { printf '%s\n' "$*"; }
record() { # id ok detail
  if [[ $2 == 0 ]]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); FAILED+=("$1: $3"); fi
}
PASS=0; FAIL=0; FAILED=()

write_skip() { # reason
  jq -nc --arg r "$1" '{skip_reason:$r,selected_run_valid:false,release_eligible:false,generated_at:(now|todate)}' >"$LASTRUN"
  say "skip: $1"; exit 0
}

# ---------- runtime fixtures (generated, not committed) ----------
setup_run() {
  mkdir -p "$CMP/tmp/runs"
  RUN_ROOT=$(mktemp -d "$CMP/tmp/runs/run.XXXXXXXX") || return 1
  TMP=$RUN_ROOT/work
  FIX=$TMP/fixtures
  export TOKEN_SHUNT_EVAL_FIXTURES=$FIX
  GEN=$FIX/gen
  CWD0=$TMP/cwd
  VRD=$RUN_ROOT/verdicts
  SPD=$RUN_ROOT/specs
  TRD=$RUN_ROOT/transcripts
  SNAP=$RUN_ROOT/snap
  MANIFEST=$RUN_ROOT/manifest.json
  mkdir -p "$VRD" "$SPD" "$TRD" "$SNAP"
  jq --arg only "$ONLY" --arg suite "$SUITE" '
    def pairs: [.[] | .id as $id | .modes[] | {case:$id,mode:.}];
    {planned:(.cases | map(select(($only == "" or .id == $only)
      and ($suite == "" or .suite == $suite))) | pairs),
     required:(.cases | pairs)}' "$CMP/cases.json" >"$MANIFEST" || return 1
  if ! jq -e '.planned | length > 0' "$MANIFEST" >/dev/null; then
    say "FAIL: no cases match case='$ONLY' suite='$SUITE'"
    return 1
  fi
}

fresh_cwd() {
  rm -rf "$CWD0"
  mkdir -p "$CWD0"
}

gen_fixtures() {
  # This directory is owned exclusively by setup_run. Keep evidence outside it,
  # but reset ALL model-visible inputs and targets between modes.
  [[ -n $RUN_ROOT && $TMP == "$RUN_ROOT/work" ]] || return 1
  rm -rf "$TMP"
  mkdir -p "$FIX"
  cp -a "$SOURCE_FIX/rails" "$SOURCE_FIX/codegen" "$FIX/" || return 1
  # Source-tree generated outputs must not become a baseline either.
  python3 - "$FIX/codegen/out" <<'PY'
import pathlib, shutil, sys
p = pathlib.Path(sys.argv[1])
p.mkdir(parents=True, exist_ok=True)
for child in p.iterdir():
    if child.name == '.gitkeep':
        continue
    if child.is_dir() and not child.is_symlink():
        shutil.rmtree(child)
    else:
        child.unlink()
PY
  mkdir -p "$GEN/bounds" "$GEN/small3" "$GEN/verify" "$GEN/collide" "$VRD" "$SPD" "$TRD" "$SNAP"
  fresh_cwd
  python3 - "$GEN" <<'PY'
import json, os, sys
g = sys.argv[1]

# bulk_facts.py: >400 lines AND st_size > 65536; MAGIC_TOKEN fn ~line 20, xref ~line 380
val = "mgt_9f2e1c77ab"
fn = "compute_magic_token"
lines = ["import hashlib", "", "", "# module padding follows."]
# pad to line 18
while len(lines) < 17:
    lines.append("# pad %d" % len(lines))
lines.append("")                       # line 18
lines.append("")                       # line 19
lines.append("def %s():" % fn)         # line 20
lines.append('    return "%s"' % val)  # line 21
lines.append("")
i = 0
while len(lines) < 378:
    lines.append("PAD%04d = %d  # %s" % (i, i, "x" * 90)); i += 1
lines.append("")
lines.append("def report_token():")          # ~line 380, references fn
lines.append("    return %s()" % fn)
lines.append("")
# pad more/longer after the xref so we exceed 400 lines AND 64KiB
while len(lines) < 450:
    lines.append("TAIL%04d = %d  # %s" % (i, i, "y" * 180)); i += 1
src = "\n".join(lines) + "\n"
while len(src.encode()) <= 65536:
    src += "TAIL%04d = %d  # %s\n" % (i, i, "y" * 180)
    i += 1
open(os.path.join(g, "bulk_facts.py"), "w").write(src)
line_no = next(i for i, l in enumerate(lines, 1) if l.startswith("def " + fn))
json.dump([val, fn, str(line_no)], open(os.path.join(g, "gold-bulk-facts.json"), "w"))

# oneline.json: single line ~70KiB containing payload_sha
sha = "sha256:0a1b2c3d4e5f" + "6" * 40
doc = '{"payload_sha":"%s","pad":"%s"}' % (sha, "p" * 69800)
open(os.path.join(g, "oneline.json"), "w").write(doc)
json.dump([sha], open(os.path.join(g, "gold-oneline.json"), "w"))

# dense_edit.txt: 'a\n' x 40000 with EDIT_MARK / KEEP_MARK mid-file
em = "EM-9z8x7"; km = "KM-4w5v6"
buf = []
for i in range(40000):
    if i == 20000:
        buf.append("EDIT_MARK=%s" % em)
    elif i == 21000:
        buf.append("KEEP_MARK=%s" % km)
    else:
        buf.append("a")
open(os.path.join(g, "dense_edit.txt"), "w").write("\n".join(buf) + "\n")
json.dump([em, "EDITED", km], open(os.path.join(g, "gold-edit.json"), "w"))

# known_range.txt: 400 lines, marker near line 205 (targeted-read case)
rv = "KR-77x"
buf = ["# filler %04d %s" % (i, "y" * 50) for i in range(1, 401)]
buf[204] = "RANGE_MARK=%s" % rv
open(os.path.join(g, "known_range.txt"), "w").write("\n".join(buf) + "\n")
json.dump([rv], open(os.path.join(g, "gold-known-range.json"), "w"))

# small3: three tiny files (total <= 16KiB)
for name, mark in (("a", "ALPHA-111"), ("b", "BRAVO-222"), ("c", "CHARLIE-333")):
    open(os.path.join(g, "small3", name + ".txt"), "w").write(
        "marker=%s\n" % mark + "note: %s\n" % ("z" * 40))

# bounds: 16KiB-1 / +1 byte files (few long lines, <350 lines), 50-line py
def sized(path, n, mark):
    body = "# %s\n" % mark
    while len(body.encode()) < n - 1:
        body += "b" * 100 + "\n"
    body = body.encode()[: n - 1].decode()
    open(path, "w").write(body + "\n")
sized(os.path.join(g, "bounds", "b16383.txt"), 16383, "KITE-7f3a91")
sized(os.path.join(g, "bounds", "b16384.txt"), 16384, "LUMEN-b21c04")
sized(os.path.join(g, "bounds", "b16385.txt"), 16385, "ORBIT-9e04d2")
py = ["def task_%d():\n    return %d" % (i, i) for i in range(1, 50)]
src = "\n\n".join(py) + "\n\ndef task_fifty():\n    return 50\n"
open(os.path.join(g, "bounds", "l50.py"), "w").write(src)

# 49-line generation reference (small; parent should write 49-line output)
open(os.path.join(g, "bounds", "w49_ref.py"), "w").write(
    "def greet(name):\n    return 'Hello, %s!' % name\n")

# collide: same-name symbols across two files (batch-evidence control)
os.makedirs(os.path.join(g, "collide"), exist_ok=True)
open(os.path.join(g, "collide", "alpha.py"), "w").write(
    "TOKEN = 'ALPHA-TOKEN'\n# unique_alpha_id\n")
open(os.path.join(g, "collide", "beta.py"), "w").write(
    "TOKEN = 'BETA-TOKEN'\n# unique_beta_id\n")

# verify refs (small) + YAML + control samples to classify
open(os.path.join(g, "verify", "config_ref.json"), "w").write(
    '{\n  "host": "example.internal",\n  "port": 8443,\n  "required_key": "rk-1"\n}\n')
open(os.path.join(g, "verify", "notes_ref.md"), "w").write(
    "# Notes\n\n- short heading\n- a few bullets\n- closing line\n")
open(os.path.join(g, "verify", "notes_ref.yaml"), "w").write(
    "title: Notes\nitems:\n  - short heading\n  - a few bullets\n")
# syntactically valid JSON missing required_key
open(os.path.join(g, "verify", "control_missing_key.json"), "w").write(
    '{\n  "host": "example.internal",\n  "port": 8443\n}\n')
# similar-length mid-truncation (invalid JSON)
full = '{\n  "host": "example.internal",\n  "port": 8443,\n  "required_key": "rk-1"\n}\n'
open(os.path.join(g, "verify", "control_trunc.json"), "w").write(full[: len(full)//2])
# Markdown whose trailing fence is a legitimate code block (not wrapping the whole file)
open(os.path.join(g, "verify", "control_fence.md"), "w").write(
    "# Notes\n\n- bullets\n\n```python\nprint(1)\n```\n")

# edit_hint.py: ~400 padded lines; decoy comment near line 12; render_header
# (with unique HDR_MODE=off) near line 300; similar render_footer present.
buf = ["# module header", "", ""]
for i in range(9, 290):
    if i == 12:
        buf.append("# see render_header for the header path")  # decoy
    else:
        buf.append("PADH%03d = %d" % (i, i))
buf += ["", "def render_footer():", "    return 'footer'", "",
        "def render_header():", "    HDR_MODE = 'off'", "    return HDR_MODE",
        ""]
while len(buf) < 400:
    buf.append("# tail pad %d" % len(buf))
open(os.path.join(g, "edit_hint.py"), "w").write("\n".join(buf) + "\n")
json.dump(["HDR_MODE=on"], open(os.path.join(g, "gold-edit-hint.json"), "w"))

# edit_ambiguous.py: same shape, but render_header (and its HDR_MODE marker)
# occurs three times with identical bodies, so no Grep pattern isolates one.
# Expected outcome is NO edit at all; the file must stay byte-identical.
buf = ["# module header", "", ""]
for i in range(9, 290):
    if i == 12:
        buf.append("# see render_header for the header path")  # decoy
    else:
        buf.append("PADA%03d = %d" % (i, i))
for cls in ("AlphaView", "BetaView", "GammaView"):
    buf += ["", "class %s:" % cls, "    def render_footer(self):",
            "        return 'footer'", "", "    def render_header(self):",
            "        HDR_MODE = 'off'", "        return HDR_MODE", ""]
while len(buf) < 400:
    buf.append("# tail pad %d" % len(buf))
open(os.path.join(g, "edit_ambiguous.py"), "w").write("\n".join(buf) + "\n")
PY
}

# ---------- claude invocation ----------
CLAUDE_COMMON=(-p --output-format stream-json --verbose --include-hook-events
               --forward-subagent-text --model sonnet --permission-mode acceptEdits
               --allowedTools Read,Edit,Grep,Glob,Agent,Task,Write,Bash)

run_claude() { # prompt transcript extra-args...
  local prompt=$1 out=$2; shift 2
  fresh_cwd
  (cd "$CWD0" && printf '%s' "$prompt" | timeout "$TIMEOUT" claude \
      "${CLAUDE_COMMON[@]}" --setting-sources "" --add-dir "$FIX" --add-dir "$TMP" "$@" \
      >"$out" 2>"$out.err")
}

# ---------- disk checks (runner-side, §13 編集/生成ディスク検証) ----------
disk_check() { # spec_json mode -> writes $VRD/<id>.<mode>.disk.json
  local spec=$1 mode=$2 id dc ok=0 reason=""
  id=$(jq -r .id <<<"$spec")
  dc=$(jq -r '.disk_check // empty' <<<"$spec")
  [[ -z $dc ]] && { jq -nc '{disk_ok:null}' >"$VRD/$id.$mode.disk.json"; return; }
  case ${dc%%:*} in
    target_absent)
      local t=${dc#target_absent:}; t=${t//\{TMP\}/$TMP}; t=${t//\{FIX\}/$FIX}
      [[ $dc == target_absent ]] && t=$(jq -r .target <<<"$spec" | sed "s|{TMP}|$TMP|g;s|{FIX}|$FIX|g")
      if [[ -e $t ]]; then reason="target exists: $t"; else ok=1; fi ;;
    target_exists|target_exists_json)
      local t=${dc#*:}; t=${t//\{TMP\}/$TMP}; t=${t//\{FIX\}/$FIX}
      if [[ ! -f $t ]]; then reason="missing target: $t"
      elif [[ ${dc%%:*} == target_exists_json ]] && ! jq empty "$t" 2>/dev/null; then reason="invalid json: $t"
      else ok=1; fi ;;
    code_writer_ok)
      local t; t=$(jq -r .target <<<"$spec" | sed "s|{TMP}|$TMP|g;s|{FIX}|$FIX|g")
      local vc; vc=$(jq -r .verify_cmd <<<"$spec" | sed "s|{TMP}|$TMP|g;s|{FIX}|$FIX|g")
      if [[ ! -f $t ]]; then reason="target missing"
      elif head -1 "$t" | grep -q '^```'; then reason="fenced output"
      elif ! (cd "$CWD0" && eval "$vc" >"$TMP/vc.out" 2>&1); then reason="verify_cmd failed: $(tail -2 "$TMP/vc.out")"
      elif ! python3 - "$TMP/vc.out" <<'PY'
import re, sys
out = open(sys.argv[1], encoding="utf-8", errors="replace").read()
m = re.search(r"Ran (\d+) tests?", out)
sys.exit(0 if m and int(m.group(1)) >= 1 and not re.search(r"FAIL|ERROR", out) else 1)
PY
      then reason="verify output bad (need Ran N tests, N>=1, no FAIL/ERROR)"
      else
        # mutation: break greeter.greet, unittest must fail, then restore
        local mf find repl; mf=$(jq -r .mutation.file <<<"$spec"); mf=$FIX/$mf
        find=$(jq -r .mutation.find <<<"$spec"); repl=$(jq -r .mutation.replace <<<"$spec")
        cp "$mf" "$SNAP/mutation.bak"
        python3 - "$mf" "$find" "$repl" <<'PY'
import sys
p, a, b = sys.argv[1:4]
s = open(p).read()
assert a in s, "mutation needle absent"
open(p, "w").write(s.replace(a, b, 1))
PY
        if (cd "$CWD0" && eval "$vc" >"$TMP/vc-mut.out" 2>&1) && grep -q 'OK' "$TMP/vc-mut.out"; then
          reason="mutation not detected (test passed on broken greet)"
        else ok=1; fi
        mv "$SNAP/mutation.bak" "$mf"
      fi ;;
    edit_marks)
      local t=$FIX/gen/dense_edit.txt
      python3 - "$t" "$SNAP/$id.pre" >"$TMP/edit-ck.json" <<'PY'
import json, sys
post = open(sys.argv[1], 'rb').read()
pre = open(sys.argv[2], 'rb').read()
em = b"EDIT_MARK="; 
# expected: pre with the EDIT_MARK line's value replaced by EDITED
lines = pre.split(b"\n"); exp = []
for l in lines:
    exp.append(em + b"EDITED" if l.startswith(em) else l)
expb = b"\n".join(exp)
keep_pre = [l for l in pre.split(b"\n") if l.startswith(b"KEEP_MARK=")]
keep_post = [l for l in post.split(b"\n") if l.startswith(b"KEEP_MARK=")]
ok = post == expb and keep_pre == keep_post and len(keep_pre) == 1
print(json.dumps({"ok": ok}))
PY
      if jq -e .ok "$TMP/edit-ck.json" >/dev/null; then ok=1; else reason="expected-bytes mismatch or KEEP_MARK changed"; fi ;;
    edit_hint)
      local t=$FIX/gen/edit_hint.py
      python3 - "$t" "$SNAP/$id.edit_hint.pre" >"$TMP/edit-ck.json" <<'PY'
import json, sys
post = open(sys.argv[1], 'rb').read()
pre = open(sys.argv[2], 'rb').read()
expb = pre.replace(b"HDR_MODE = 'off'", b"HDR_MODE = 'on'")
print(json.dumps({"ok": post == expb}))
PY
      if jq -e .ok "$TMP/edit-ck.json" >/dev/null; then ok=1; else reason="expected-bytes mismatch"; fi ;;
    edit_unchanged)
      local t=${dc#*:}; t=${t//\{TMP\}/$TMP}; t=${t//\{FIX\}/$FIX}
      local pre=$SNAP/$id.$(basename "$t").pre
      if [[ ! -f $t || ! -f $pre ]]; then reason="missing fixture or pre-run snapshot"
      elif ! cmp -s "$pre" "$t"; then reason="fixture bytes changed; control case must not edit"
      else ok=1; fi ;;
    verify_levels)
      if python3 "$CMP/flow_checks.py" --verify syntax "$TMP/vl_config.json" >/dev/null \
        && python3 "$CMP/flow_checks.py" --verify minimal "$TMP/vl_notes.md" --expected-lines 30 >/dev/null \
        && python3 "$CMP/flow_checks.py" --verify minimal "$TMP/vl_notes.yaml" >/dev/null \
        && python3 "$CMP/flow_checks.py" --verify requirements "$TMP/vl_req.json" --require-key required_key=rk-1 >/dev/null; then ok=1
      else reason="generated verification-level artifacts failed syntax/minimal/requirements checks"; fi ;;
    *) reason="unknown disk_check $dc" ;;
  esac
  jq -nc --argjson ok "$ok" --arg r "$reason" '{disk_ok:($ok==1),reason:$r}' >"$VRD/$id.$mode.disk.json"
  [[ $ok == 1 ]]
}

# ---------- snapshot / restore of committed fixtures ----------
snap_fixtures() { (cd "$FIX" && tar cf "$SNAP/fx.tar" rails codegen 2>/dev/null) || true; }
restore_fixtures() { [[ -f $SNAP/fx.tar ]] && (cd "$FIX" && tar xf "$SNAP/fx.tar"); rm -rf "$FIX/codegen/out/"* 2>/dev/null || true; }

# ---------- main ----------
[[ ${BASH_SOURCE[0]} != "$0" ]] && return 0
if ! setup_run; then
  jq -nc '{selected_run_valid:false,release_eligible:false,errors:["invalid run plan"]}' >"$LASTRUN"
  exit 1
fi
command -v claude >/dev/null 2>&1 || write_skip claude_missing

say "== fixtures =="
gen_fixtures || exit 1
snap_fixtures
say "== judge selftest =="
python3 "$CMP/judge.py" --selftest || { say "judge selftest failed"; exit 1; }

say "== probes =="
# judge.py needs a spec file arg; probes bypass it with inline checks
load_out=$TRD/_probe_load.jsonl
run_claude "Reply with just OK" "$load_out" --plugin-dir "$ROOT/plugin"
load_ok=$(python3 - "$load_out" <<'PY'
import json, sys
init = {}
for line in open(sys.argv[1], encoding="utf-8"):
    try: e = json.loads(line)
    except json.JSONDecodeError: continue
    if e.get("type") == "system" and e.get("subtype") == "init":
        init = e
plugins = [p.get("name") for p in init.get("plugins", []) or []]
agents = init.get("agents", []) or []
errs = init.get("plugin_errors")
ok = ("token-shunt" in plugins and not errs
      and "token-shunt:bulk-reader" in agents and "token-shunt:code-writer" in agents)
print("ok" if ok else "fail:%s agents=%s errs=%s" % (plugins, agents, errs))
PY
)
[[ $load_ok == ok ]] && record probe-load 0 "" || record probe-load 1 "$load_ok"

iso_out=$TRD/_probe_iso.jsonl
run_claude "Reply with just OK" "$iso_out"
iso_ok=$(python3 - "$iso_out" <<'PY'
import json, sys
# Match judge.py foreign_hooks(): subtype==hook_response + hook_name.
# Direct mode: any non-builtin PreToolUse hook_response fails (token-shunt
# hooks are also foreign here because the plugin must not be loaded).
BUILTIN = {"SessionStart:startup"}
init = {}; foreign = []
for line in open(sys.argv[1], encoding="utf-8"):
    try: e = json.loads(line)
    except json.JSONDecodeError: continue
    if e.get("type") == "system" and e.get("subtype") == "init":
        init = e
    if e.get("type") != "system" or e.get("subtype") != "hook_response":
        continue
    name = e.get("hook_name") or ""
    if name in BUILTIN:
        continue
    he = e.get("hook_event") or ""
    # live events may only have subtype + hook_name (no hook_event)
    if he == "PreToolUse" or "PreToolUse" in name or (
            not he and name and not name.startswith("SessionStart")):
        foreign.append(name or he or "unnamed")
plugins = [p.get("name") for p in init.get("plugins", []) or []]
if "token-shunt" in plugins:
    print("fail:token-shunt in direct plugins")
elif foreign:
    print("fail:foreign PreToolUse hooks %s" % foreign)
else:
    print("ok")
PY
)
[[ $iso_ok == ok ]] && record probe-isolation 0 "" || record probe-isolation 1 "$iso_ok"

if (cd "$ROOT" && claude plugin validate . >/dev/null 2>&1); then
  record plugin-validate 0 ""
else
  record plugin-validate 1 "claude plugin validate failed"
fi

if (( FAIL > 0 )); then
  say "probes failed; aborting case runs"
  for f in "${FAILED[@]}"; do say "FAIL $f"; done
  jq -nc --argjson fails "$FAIL" '{probe_failure:true,fail_count:$fails,selected_run_valid:false,release_eligible:false,generated_at:(now|todate)}' >"$LASTRUN"
  restore_fixtures; exit 1
fi

say "== cases =="
CASE_N=0
while IFS= read -r case; do
  id=$(jq -r .id <<<"$case")
  suite=$(jq -r .suite <<<"$case")
  [[ -n $ONLY && $id != "$ONLY" ]] && continue
  [[ -n $SUITE && $suite != "$SUITE" ]] && continue
  for mode in $(jq -r '.modes[]' <<<"$case"); do
    CASE_N=$((CASE_N+1))
    # build prompt
    if [[ $mode == direct ]]; then
      prompt=$(jq -r '.prompt_direct // .prompt_delegate' <<<"$case")
    else
      prompt=$(jq -r '.prompt_delegate // .prompt_direct' <<<"$case")
      hint=$(jq -r '.wm_hint // empty' <<<"$case")
      hint=${hint//\{WM\}/$mode}
      prompt=${prompt//\{WMHINT\}/$hint}
      prompt=${prompt//\{WM\}/$mode}
    fi
    # static guard on the UNSUBSTITUTED prompt: fixture paths contain
    # "token-shunt" after {FIX} replacement and must not skip the case.
    if jq -e '.expect.delegate.deny_route' <<<"$case" >/dev/null 2>&1 \
       && grep -qiE 'token-shunt|bulk-reader|Agent' <<<"$prompt"; then
      say "FAIL $id/$mode: user prompt mentions mechanism"
      jq -nc --arg id "$id" --arg m "$mode" \
        '{case:$id,mode:$m,verdict:"fail",checks:{prompt_mechanism:false},reasons:["user prompt mentions token-shunt/bulk-reader/Agent"]}' \
        >"$VRD/$id.$mode.json"
      record "$id/$mode" 1 "prompt mentions mechanism"
      continue
    fi
    prompt=${prompt//\{FIX\}/$FIX}
    prompt=${prompt//\{TMP\}/$TMP}
    prompt=${prompt//\{JUDGE_DIR\}/$CMP}
    # resolved spec: substitute placeholders in the raw JSON (paths are clean)
    spec=${case//\{FIX\}/$FIX}
    spec=${spec//\{TMP\}/$TMP}
    spec=${spec//\{JUDGE_DIR\}/$CMP}
    gf=$(jq -r '.gold_file // empty' <<<"$spec")
    if [[ -n $gf && -f $FIX/$gf ]]; then
      spec=$(jq -c --slurpfile g "$FIX/$gf" '.gold = ((.gold // []) + $g[0])' <<<"$spec")
    fi
    printf '%s' "$spec" >"$SPD/$id.$mode.json"
    # regenerate runtime fixtures -> same initial state for every mode run
    gen_fixtures || exit 1
    # snapshot files this case may mutate (for expected-bytes comparison)
    [[ -f $FIX/gen/dense_edit.txt ]] && cp "$FIX/gen/dense_edit.txt" "$SNAP/$id.pre"
    [[ -f $FIX/gen/edit_hint.py ]] && cp "$FIX/gen/edit_hint.py" "$SNAP/$id.edit_hint.pre"
    [[ -f $FIX/gen/edit_ambiguous.py ]] && cp "$FIX/gen/edit_ambiguous.py" "$SNAP/$id.edit_ambiguous.py.pre"
    # run claude
    transcript=$TRD/$id.$mode.jsonl
    say "RUN $id/$mode"
    if [[ $mode == direct ]]; then
      run_claude "$prompt" "$transcript"
    else
      run_claude "$prompt" "$transcript" --plugin-dir "$ROOT/plugin"
    fi
    rc=$?
    if (( rc != 0 )) && [[ ! -s $transcript ]]; then
      jq -nc --arg id "$id" --arg m "$mode" --argjson rc "$rc" \
        '{case:$id,mode:$m,verdict:"fail",checks:{run:false},reasons:["claude exit "+($rc|tostring)+" with empty transcript"]}' \
        >"$VRD/$id.$mode.json"
      record "$id/$mode" 1 "claude exit $rc"
      disk_check "$spec" "$mode" || true
      continue
    fi
    # judge transcript (nonzero exit still yields a judgeable stream, e.g. api_error)
    if python3 "$CMP/judge.py" "$transcript" "$SPD/$id.$mode.json" "$mode" \
        >"$VRD/$id.$mode.json" 2>"$VRD/$id.$mode.judge-err"; then
      record "$id/$mode" 0 ""
    else
      record "$id/$mode" 1 "$(head -c 200 "$VRD/$id.$mode.judge-err" 2>/dev/null; jq -r '.reasons[0] // empty' "$VRD/$id.$mode.json" 2>/dev/null)"
    fi
    # disk-side verification (runner-side)
    disk_check "$spec" "$mode" || true
    # writer body-absence check (isolation: generated body must not enter parent)
    if [[ $mode != direct && $(jq -r '.isolation // empty' <<<"$case") == writer_body_absent ]]; then
      tgt=$(jq -r '.target // empty' <<<"$spec" | sed "s|{TMP}|$TMP|g;s|{FIX}|$FIX|g")
      [[ -z $tgt ]] && tgt=$TMP/large_test.py
      leak_rc=2
      if [[ -f $tgt ]]; then
        python3 "$CMP/judge.py" --leakcheck "$transcript" "$tgt" >/dev/null 2>&1
        leak_rc=$?
      fi
      if [[ $leak_rc == 1 ]]; then
        jq '.checks.writer_body_absent=true' "$VRD/$id.$mode.json" >"$VRD/$id.$mode.json.tmp"
      else
        jq '.checks.writer_body_absent=false | .verdict="fail" | .reasons += ["writer body leak or missing leak-check evidence"]' \
          "$VRD/$id.$mode.json" >"$VRD/$id.$mode.json.tmp"
      fi
      mv "$VRD/$id.$mode.json.tmp" "$VRD/$id.$mode.json"
    fi
    restore_fixtures
  done
done < <(jq -c '.cases[]' cases.json)

# ---------- aggregate ----------
say "== aggregate =="
python3 "$CMP/judge.py" --aggregate "$VRD" "$SPD" "$FIX" "$LASTRUN" "$MANIFEST" \
  && agg=0 || agg=$?
say "last-run: $LASTRUN"
say "done: pass=$PASS fail=$FAIL runs=$CASE_N"
for f in ${FAILED[@]+"${FAILED[@]}"}; do say "FAIL $f"; done
restore_fixtures
(( FAIL > 0 )) && exit 1
exit $agg
