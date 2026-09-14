#!/usr/bin/env bash
# token-shunt hook evals (design §13). No Claude CLI required:
# stdin JSON -> hook stdout decision / exit code.
set -u
export LC_ALL=C
unset CDPATH
cd "$(dirname "$0")" || exit 1
if ! jq -e 'type == "array" and length > 0' hook-evals.json >/dev/null; then
  echo "error: hook-evals.json must be a non-empty JSON array catalog" >&2
  exit 1
fi
if ! jq -e 'type == "array" and length > 0' bash-hook-evals.json >/dev/null; then
  echo "error: bash-hook-evals.json must be a non-empty JSON array catalog" >&2
  exit 1
fi
ROOT=$(cd .. && pwd)
FIX=$PWD/fixtures
HOOKS=$ROOT/plugin/hooks
PASS=0; FAIL=0
FAILED=()

mkdir -p "$FIX"

gen_fixtures() {
  awk 'BEGIN{for(i=0;i<349;i++)print "abcdefghijklmnop"}'                  >"$FIX/small-349.txt"
  awk 'BEGIN{for(i=0;i<351;i++)print "abcdefghijklmnop"}'                  >"$FIX/over-351.txt"
  awk 'BEGIN{for(i=0;i<10;i++)printf "%099d\n",i}'                         >"$FIX/small-10.txt"
  awk 'BEGIN{for(i=0;i<400;i++)printf "%049d\n",i}'                        >"$FIX/f400-20k.txt"
  awk 'BEGIN{printf "%070000d",0}'                                         >"$FIX/oneline-70k.txt"
  awk 'BEGIN{for(i=0;i<100;i++)printf "%01000d\n",i; for(i=0;i<900;i++)print ""}' >"$FIX/skew-deny.txt"
  awk 'BEGIN{for(i=0;i<100;i++)print "x"; for(i=0;i<900;i++)printf "%01000d\n",i}' >"$FIX/skew-pass.txt"
  awk 'BEGIN{for(i=0;i<4096;i++)print "a"}'                                >"$FIX/dense-4096.txt"
  awk 'BEGIN{for(i=0;i<820;i++)printf "%099d\n",i}'                        >"$FIX/large-80k.txt"
  cp "$FIX/large-80k.txt" "$FIX/large|name.txt"
  cp "$FIX/large-80k.txt" "$FIX/space name large.txt"
  cp -- "$FIX/large-80k.txt" "$FIX/-weird.txt"
  { printf '\211PNG\r\n\032\n'; head -c 210000 /dev/zero; }                >"$FIX/img-200k.png"
  { printf '%%PDF-1.4\n'; head -c 209900 /dev/zero | tr '\0' ' '; }        >"$FIX/doc-200k.pdf"
  awk 'BEGIN{printf "{\"cells\":[],\"metadata\":{}}"; for(i=0;i<209930;i++)printf " "}' >"$FIX/nb-200k.ipynb"
  # >9MiB of short lines; restore the tracked fixture if missing/undersized.
  if [[ ! -f $FIX/big-scan.txt ]] || (( $(wc -c <"$FIX/big-scan.txt") < 9000000 )); then
    awk 'BEGIN{for(i=0;i<4700000;i++)print "x"}'                           >"$FIX/big-scan.txt"
  fi
}

record() { # id ok detail
  if [[ $2 == 0 ]]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); FAILED+=("$1: $3"); fi
}

run_hook() { # hook input [JSON env object] -> OUT EC
  local envs=() name
  if [[ -n ${3-} ]]; then
    while IFS= read -r -d '' entry; do envs+=("$entry"); done < <(
      jq -j 'to_entries[] | "\(.key)=\(.value)\u0000"' <<<"$3")
  fi
  OUT=$(
    # Preserve PATH/authentication, but apply only the catalog's hook settings.
    while IFS= read -r name; do
      [[ $name == TOKEN_SHUNT_* || $name == CDPATH ]] && unset "$name"
    done < <(compgen -e)
    printf '%s' "$2" | env "${envs[@]+"${envs[@]}"}" "$HOOKS/$1" 2>/dev/null); EC=$?
}

check_expect() { # expect out ec
  local expect=$1 out=$2 ec=$3
  case $expect in
    pass)  [[ $ec == 0 && -z $out ]] ;;
    deny_safety)
      # Non-routing parser safety denials still need plugin attribution.
      [[ $ec == 0 ]] \
        && jq -e '.hookSpecificOutput.permissionDecision == "deny"
                   and (.hookSpecificOutput.permissionDecisionReason | type == "string")
                   and (.hookSpecificOutput.permissionDecisionReason | test("token-shunt"))' \
             <<<"$out" >/dev/null 2>&1 ;;
    deny|deny_budget)
      # deny JSON + reason must route to /token-shunt:bulk-reader (§3-1);
      # deny_budget additionally requires the scan-budget detail (§8.6)
      [[ $ec == 0 ]] \
        && jq -e '.hookSpecificOutput.permissionDecision == "deny"
                   and (.hookSpecificOutput.permissionDecisionReason | test("bulk-reader"))' \
             <<<"$out" >/dev/null 2>&1 \
        && { [[ $expect == deny ]] || grep -qi 'scan budget' <<<"$out"; } ;;
    *) return 1 ;;
  esac
}

echo "== fixtures =="
gen_fixtures
echo "fixtures ready: $FIX"

# --- check-file-size cases ---
echo "== check-file-size =="
while IFS= read -r case; do
  id=$(jq -r '.id' <<<"$case")
  expect=$(jq -r '.expect' <<<"$case")
  inp=$(jq -c '.input' <<<"$case")
  envs=$(jq -c '.env // {}' <<<"$case")
  inp=$(jq -c --arg fix "$FIX" 'walk(if type == "string" then split("@FIX@") | join($fix) else . end)' <<<"$inp")
  run_hook check-file-size "$inp" "$envs"
  if check_expect "$expect" "$OUT" "$EC"; then record "$id" 0 ""; else record "$id" 1 "expect=$expect ec=$EC out=$(head -c 200 <<<"$OUT")"; fi
done < <(jq -c '.[]' hook-evals.json)

# --- check-bash-read cases ---
echo "== check-bash-read =="
while IFS= read -r case; do
  id=$(jq -r '.id' <<<"$case")
  expect=$(jq -r '.expect' <<<"$case")
  cmd=$(jq -r '.cmd' <<<"$case")
  agent=$(jq -r '.agent_type // ""' <<<"$case")
  envs=$(jq -c '.env // {}' <<<"$case")
  cmd=$(python3 "$ROOT/evals/render_command.py" "$cmd" "$FIX")
  inp=$(jq -nc --arg c "$cmd" --arg a "$agent" \
        '{tool_input:{command:$c}} + (if $a == "" then {} else {agent_type:$a} end)')
  run_hook check-bash-read "$inp" "$envs"
  if check_expect "$expect" "$OUT" "$EC"; then record "$id" 0 ""; else record "$id" 1 "expect=$expect ec=$EC out=$(head -c 200 <<<"$OUT")"; fi
done < <(jq -c '.[]' bash-hook-evals.json)

# --- special: agent_type inside tool_input is model-controlled; must not allowlist ---
inp=$(jq -nc --arg f "$FIX/large-80k.txt" '{tool_input:{file_path:$f,agent_type:"token-shunt:bulk-reader"}}')
run_hook check-file-size "$inp"
check_expect deny "$OUT" "$EC" && record read-worker-spoof 0 "" || record read-worker-spoof 1 "ec=$EC out=$OUT"
printf -v quoted_file %q "$FIX/large-80k.txt"
inp=$(jq -nc --arg f "$quoted_file" '{tool_input:{command:("cat "+$f),agent_type:"token-shunt:bulk-reader"}}')
run_hook check-bash-read "$inp"
check_expect deny "$OUT" "$EC" && record bash-worker-spoof 0 "" || record bash-worker-spoof 1 "ec=$EC out=$OUT"

# --- special: jq missing -> fail-closed exit 2 (both hooks) ---
echo "== jq-missing / sessionstart =="
STUB=$PWD/.stubbin
mkdir -p "$STUB"
ln -sf "$(command -v bash)" "$STUB/bash"

inp=$(jq -nc --arg f "$FIX/large-80k.txt" '{tool_input:{file_path:$f}}')
OUT=$(printf '%s' "$inp" | env PATH="$STUB" "$HOOKS/check-file-size" 2>/dev/null); EC=$?
{ [[ $EC == 2 ]] && ! grep -q 'permissionDecision' <<<"$OUT"; } && record jq-missing-read 0 "" || record jq-missing-read 1 "ec=$EC out=$OUT"

inp=$(jq -nc '{tool_input:{command:"cat /etc/hostname"}}')
OUT=$(printf '%s' "$inp" | env PATH="$STUB" "$HOOKS/check-bash-read" 2>/dev/null); EC=$?
{ [[ $EC == 2 ]] && ! grep -q 'permissionDecision' <<<"$OUT"; } && record jq-missing-bash 0 "" || record jq-missing-bash 1 "ec=$EC out=$OUT"

OUT=$(printf '{"session_id":"t"}' | env PATH="$STUB" "$HOOKS/check-jq" 2>/dev/null); EC=$?
if [[ $EC == 0 ]] \
  && jq -e '.hookSpecificOutput.additionalContext | test("jq")' <<<"$OUT" >/dev/null 2>&1 \
  && ! jq -e '.hookSpecificOutput.permissionDecision' <<<"$OUT" >/dev/null 2>&1; then
  record sessionstart-jq-missing 0 ""
else
  record sessionstart-jq-missing 1 "ec=$EC out=$OUT"
fi

# Every missing dependency must be named: reporting only the first one hides
# the others from the operator, who then fixes them one session at a time.
OUT=$(printf '{"session_id":"t"}' | env PATH="$STUB" "$HOOKS/check-jq" 2>/dev/null); EC=$?
if [[ $EC == 0 ]] \
  && jq -e '.hookSpecificOutput.additionalContext | test("jq") and test("Python 3")' <<<"$OUT" >/dev/null 2>&1; then
  record sessionstart-deps-missing 0 ""
else
  record sessionstart-deps-missing 1 "ec=$EC out=$OUT"
fi

ln -sf "$(command -v jq)" "$STUB/jq"
OUT=$(printf '{"session_id":"t"}' | env PATH="$STUB" "$HOOKS/check-jq" 2>/dev/null); EC=$?
if [[ $EC == 0 ]] \
  && jq -e '.hookSpecificOutput.additionalContext | test("Python 3") and (test("jq") | not)' <<<"$OUT" >/dev/null 2>&1; then
  record sessionstart-python-missing 0 ""
else
  record sessionstart-python-missing 1 "ec=$EC out=$OUT"
fi
rm -rf "$STUB"

OUT=$(printf '{"session_id":"t"}' | "$HOOKS/check-jq" 2>/dev/null); EC=$?
{ [[ $EC == 0 && -z $OUT ]]; } && record sessionstart-jq-present 0 "" || record sessionstart-jq-present 1 "ec=$EC out=$OUT"

# --- special: invalid JSON stdin -> fail-closed exit 2 (both hooks) ---
echo "== invalid-json =="
ERRF=$PWD/.invalid-json.err
OUT=$(printf 'not-json' | "$HOOKS/check-file-size" 2>"$ERRF"); EC=$?
ERR=$(cat "$ERRF")
{ [[ $EC == 2 ]] && [[ -z $OUT ]] && grep -qi 'invalid' <<<"$ERR"; } \
  && record invalid-json-read 0 "" || record invalid-json-read 1 "ec=$EC out=$OUT err=$ERR"
OUT=$(printf 'not-json' | "$HOOKS/check-bash-read" 2>"$ERRF"); EC=$?
ERR=$(cat "$ERRF")
{ [[ $EC == 2 ]] && [[ -z $OUT ]] && grep -qi 'invalid' <<<"$ERR"; } \
  && record invalid-json-bash 0 "" || record invalid-json-bash 1 "ec=$EC out=$OUT err=$ERR"
rm -f "$ERRF"

# Link targets must receive the same size gate as direct file paths.
echo "== symlink regression checks =="
python3 "$ROOT/evals/test_symlink_hooks.py" \
  && record symlink-regressions 0 "" || record symlink-regressions 1 "symlink regression failed"
echo "== cd regression checks =="
python3 "$ROOT/evals/test_cd_hooks.py" \
  && record cd-regressions 0 "" || record cd-regressions 1 "cd regression failed"
echo "== scan budget regression checks =="
python3 "$ROOT/evals/test_scan_budget_hooks.py" \
  && record scan-budget-regressions 0 "" || record scan-budget-regressions 1 "scan budget regression failed"
echo "== Bash operational regression checks =="
python3 "$ROOT/evals/test_bash_operational_hooks.py" \
  && record bash-operational-regressions 0 "" || record bash-operational-regressions 1 "Bash operational regression failed"

echo "== review regression checks =="
python3 -B "$ROOT/evals/test_review_hooks.py" \
  && record review-regressions 0 "" || record review-regressions 1 "review regression failed"

echo "== harness input regression checks =="
python3 -B "$ROOT/evals/test_harness_inputs.py" \
  && record harness-input-regressions 0 "" || record harness-input-regressions 1 "harness input regression failed"

echo "== model selection regression checks =="
python3 -B -m unittest discover -s "$ROOT/evals/compare" -p test_unreadable_and_model.py \
  && record model-selection-regressions 0 "" || record model-selection-regressions 1 "model selection regression failed"

# These standalone suites are part of the result-accounted release checks.
for suite in reader_contract reader_call_contract bash_finding_fixes doctor_record; do
  echo "== $suite regression checks =="
  python3 -B "$ROOT/evals/test_${suite}.py" \
    && record "$suite-regressions" 0 "" || record "$suite-regressions" 1 "$suite regression failed"
done

# --- special: marketplace schema (§13 marketplace-schema) ---
echo "== marketplace-schema =="
if jq -e '.name | type == "string" and length > 0' "$ROOT/.claude-plugin/marketplace.json" >/dev/null \
  && jq -e '.owner.name | type == "string" and length > 0' "$ROOT/.claude-plugin/marketplace.json" >/dev/null \
  && jq -e '.plugins | type == "array" and length > 0' "$ROOT/.claude-plugin/marketplace.json" >/dev/null; then
  if command -v claude >/dev/null 2>&1; then
    (cd "$ROOT" && claude plugin validate . >/dev/null 2>&1) \
      && record marketplace-schema 0 "" || record marketplace-schema 1 "claude plugin validate failed"
  else
    record marketplace-schema 0 ""
  fi
else
  record marketplace-schema 1 "missing name / owner.name / plugins"
fi

echo "== archive verification regression checks =="
python3 -B -m unittest discover -s "$ROOT/evals" -p test_build_zip.py \
  && record archive-verification-regressions 0 "" || record archive-verification-regressions 1 "archive verification regression failed"

# --- special: zip structure + exec bits (§13 zip-exec-bits) ---
echo "== zip-exec-bits =="
if "$ROOT/scripts/build-zip.sh" >/dev/null 2>&1; then
  record zip-exec-bits 0 ""
else
  record zip-exec-bits 1 "build-zip.sh failed"
fi

echo "== result =="
echo "pass: $PASS  fail: $FAIL"
for f in ${FAILED[@]+"${FAILED[@]}"}; do echo "FAIL $f"; done
(( FAIL == 0 ))
