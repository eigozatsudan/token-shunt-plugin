#!/usr/bin/env bash
# The loop that spends, and the four things that stop it.
#
# Every guard here exists because a loop ran past one. A $30 cap reached
# $36.55 with no checkpoint (reviews/scope-interleaved-2026-09-17.md
# section 6). An hour of CLI downtime left 450 run directories with no
# summary (reviews/django-dose-2026-09-17.md section 7.2). And a block is
# pre-registered only if the wording it ran under is the wording that was
# registered, which a driver has to check rather than assume
# (reviews/parent-no-read-rate-2026-09-17.md section 0).
#
#   SUITE=X SLOTS=django-plan-trace-bare/auto,django-plan-trace-plan/auto \
#   bash evals/compare/drive.sh --pairs 40 \
#       --cases django-plan-trace-bare,django-plan-trace-plan \
#       --cap 21 --reserve 0.80 --max-barren 10
#
# The bound that matters most is --max-runs, which is on whether or not the
# others fire: the two guards below only notice failures of their own kind,
# and a runner that fails in some third way -- a summary written with the
# wrong cases, a run that bills nothing and completes nothing -- would
# otherwise loop forever. It defaults to twice the target.
#
# Exit codes: 0 when the target is reached, 3 when a guard stopped it first,
# 2 for a usage error. Stopping is its own code so a mistyped argument
# cannot be read as "the block is done".
set -uo pipefail

CMP=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
STOPPED=3
USAGE=2
USAGE_TEXT="usage: drive.sh --pairs N [--runs DIR] [--cases a,b] \
[--cases-file FILE] [--cap USD] [--reserve USD] [--max-barren N] \
[--max-runs N]"

pairs=''
runs=$CMP/tmp/runs
cases=''
cases_file=$CMP/cases.json
cap=''
reserve=''
max_barren=''
max_runs=''

die() { printf '%s\n' "$1" >&2; exit "$2"; }

whole() { # name value -> echoes it, or exits usage
  [[ $2 =~ ^[0-9]+$ && $2 -ge 1 ]] \
    || die "$1 must be a positive whole number: $2" "$USAGE"
  printf '%s' "$2"
}

while (($#)); do
  case $1 in
    --pairs|--runs|--cases|--cases-file|--cap|--reserve|--max-barren|--max-runs)
      (($# >= 2)) || die "$USAGE_TEXT" "$USAGE"
      case $1 in
        --pairs) pairs=$(whole pairs "$2") || exit "$USAGE" ;;
        --runs) runs=$2 ;;
        --cases) cases=$2 ;;
        --cases-file) cases_file=$2 ;;
        --cap) cap=$2 ;;
        --reserve) reserve=$2 ;;
        --max-barren) max_barren=$(whole max-barren "$2") || exit "$USAGE" ;;
        --max-runs) max_runs=$(whole max-runs "$2") || exit "$USAGE" ;;
      esac
      shift 2 ;;
    *) die "$USAGE_TEXT" "$USAGE" ;;
  esac
done

[[ -n $pairs ]] || die "$USAGE_TEXT" "$USAGE"
# A reserve decides nothing without a cap, and spend.py refuses the pair.
# Accepting it here would leave the caller believing a stop rule was on.
[[ -z $reserve || -n $cap ]] || die '--reserve needs --cap' "$USAGE"
[[ -n $max_runs ]] || max_runs=$((pairs * 2))
mkdir -p "$runs" || die "cannot create $runs" "$USAGE"

# The wording under test, fingerprinted before the first run. Recomputing it
# each iteration is the whole point: an edit between runs would otherwise be
# invisible in the record.
prompts() {
  [[ -n $cases ]] || return 0
  local id
  for id in ${cases//,/ }; do
    jq -r --arg id "$id" '.cases[] | select(.id == $id)
                          | (.prompt_delegate // .prompt_direct // "")' \
      "$cases_file" 2>/dev/null
  done | md5sum | cut -d' ' -f1
}

# Completed means a summary that names every case asked for -- one arm is
# half a measurement, and a directory is not a measurement at all.
completed() {
  local dir n=0 want=${cases:-}
  for dir in "$runs"/*/; do
    [[ -d $dir ]] || continue
    [[ -f $dir/summary.json ]] || continue
    if [[ -z $want ]]; then
      jq -e '(.cases | type) == "object" and (.cases | length) > 0' \
        "$dir/summary.json" >/dev/null 2>&1 || continue
    else
      jq -e --arg want "$want" '. as $root
        | ($want | split(",")) as $ids
        | ($root.cases | type) == "object"
          and all($ids[]; . as $id | $root.cases | has($id))' \
        "$dir/summary.json" >/dev/null 2>&1 || continue
    fi
    n=$((n + 1))
  done
  printf '%s' "$n"
}

# A guard says one of three things, and they are not interchangeable: under
# its limit (0), at it (3), or "you typed that wrong" (2). Reading the last
# as a stop would end the block believing it was finished.
guard() {
  local rc=0
  "$@" >/dev/null || rc=$?
  ((rc == 0)) && return 0
  ((rc == STOPPED)) && exit "$STOPPED"
  printf 'stop: %s refused its arguments (exit %d)\n' "$2" "$rc" >&2
  exit "$USAGE"
}

# The runner is a command, not a string to be re-split: a path with a space
# in it must not become two arguments.
if [[ -n ${TS_RUNNER:-} ]]; then
  RUNNER=("$TS_RUNNER")
else
  RUNNER=(bash "$CMP/run.sh")
fi

baseline=$(prompts)
attempts=0

while :; do
  done_now=$(completed)
  if ((done_now >= pairs)); then
    printf 'done: %d completed runs\n' "$done_now" >&2
    exit 0
  fi
  if ((attempts >= max_runs)); then
    printf 'stop: %d attempts reached the bound of %d with %d completed\n' \
      "$attempts" "$max_runs" "$done_now" >&2
    exit "$STOPPED"
  fi
  if [[ $(prompts) != "$baseline" ]]; then
    printf 'stop: a case prompt changed during the block; %d completed\n' \
      "$done_now" >&2
    exit "$STOPPED"
  fi
  if [[ -n $max_barren ]]; then
    guard python3 "$CMP/progress.py" --max-barren "$max_barren" "$runs"
  fi
  if [[ -n $cap ]]; then
    guard python3 "$CMP/spend.py" --cap "$cap" \
      ${reserve:+--reserve "$reserve"} "$runs"
  fi
  attempts=$((attempts + 1))
  "${RUNNER[@]}" || true
done
