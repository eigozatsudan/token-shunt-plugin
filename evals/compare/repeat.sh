#!/usr/bin/env bash
# Repeat every configured case/mode; retain each aggregate independently.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
count=${1:-2}
[[ $count =~ ^[1-9][0-9]*$ ]] || { echo 'repeat count must be positive' >&2; exit 2; }
mkdir -p tmp/repeats
output=$(mktemp -d "$PWD/tmp/repeats/repeat.XXXXXXXX")
printf 'Repeated evaluation evidence: %s\n' "$output"
failed=0
for ((i=1; i<=count; i++)); do
  rc=0
  SUITE='' bash run.sh >"$output/run-$i.log" 2>&1 || rc=$?
  cp last-run.json "$output/run-$i.json"
  if jq -e '.environment_failure == true or .skip_reason != null' last-run.json >/dev/null; then
    printf 'Run %s blocked by environment; see %s\n' "$i" "$output/run-$i.log"
    exit 2
  fi
  printf 'Run %s finished (exit %s): %s\n' "$i" "$rc" "$output/run-$i.json"
  ((rc == 0)) || failed=1
 done
exit "$failed"
