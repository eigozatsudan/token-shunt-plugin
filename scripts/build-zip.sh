#!/usr/bin/env bash
# Build the distributable plugin ZIP (design §6, §13).
# Primary artifact = contents of plugin/ (plugin.json at archive root).
set -euo pipefail
export LC_ALL=C
cd "$(dirname "$0")/.."
ROOT=$PWD
ZIP=$ROOT/token-shunt.zip

chmod +x plugin/hooks/check-file-size plugin/hooks/check-bash-read plugin/hooks/check-jq plugin/hooks/check-agent-model plugin/hooks/check-reader-contract plugin/hooks/check-final-answer
rm -f "$ZIP"

if command -v zip >/dev/null 2>&1; then
  (cd plugin && zip -q -r "$ZIP" . -x '__pycache__/*' '*/__pycache__/*' '*.pyc' '*.pyo')
elif command -v python3 >/dev/null 2>&1; then
  python3 - "$ROOT/plugin" "$ZIP" <<'PY'
import os, stat, sys, zipfile
root, zp = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d != '__pycache__')
        for fn in sorted(fns):
            if fn.endswith(('.pyc', '.pyo')):
                continue
            p = os.path.join(dp, fn)
            arc = os.path.relpath(p, root).replace(os.sep, '/')
            zi = zipfile.ZipInfo(arc)
            zi.external_attr = (stat.S_IMODE(os.stat(p).st_mode)) << 16
            zi.compress_type = zipfile.ZIP_DEFLATED
            with open(p, 'rb') as fh:
                z.writestr(zi, fh.read())
PY
else
  echo "build-zip: need 'zip' or 'python3'" >&2
  exit 1
fi

# Verify: plugin.json at archive top or one level down; hooks keep +x (§13).
verify() {
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$1" <<'PY'
import re, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    names = z.namelist()
    manifests = [n for n in names if re.fullmatch(
        r'(?:[A-Za-z0-9_-][A-Za-z0-9_.-]*/)?\.claude-plugin/plugin\.json', n)]
    clean = all('__pycache__' not in n.split('/') and not n.endswith(('.pyc', '.pyo')) for n in names)
    valid = clean and len(names) == len(set(names)) and len(manifests) == 1
    if valid:
        prefix = manifests[0][:-len('.claude-plugin/plugin.json')]
        for hook in ('check-file-size', 'check-bash-read', 'check-jq', 'check-agent-model',
                     'check-reader-contract', 'check-final-answer'):
            name = prefix + 'hooks/' + hook
            if name not in names:
                valid = False
                continue
            mode = z.getinfo(name).external_attr >> 16
            valid = valid and bool(mode & 0o111) and (mode & 0o170000) in (0, 0o100000)
    sys.exit(0 if valid else 1)
PY
  elif command -v zipinfo >/dev/null 2>&1; then
    # Read the filename field rather than matching against the full listing;
    # root-level hooks have whitespace, not a slash, before "hooks/".
    local listing
    listing=$(zipinfo -l "$1") || return 1
    printf '%s\n' "$listing" | awk '
      /^[-dl?][rwxstST?-]/ {
        name = $0
        for (i = 1; i <= 9; i++) sub(/^[^[:space:]]+[[:space:]]+/, "", name)
        if (seen[name]++) bad = 1
        if (name ~ /(^|\/)__pycache__(\/|$)/ || name ~ /\.py[co]$/) bad = 1
        modes[name] = $1
        if (name ~ /^(\.claude-plugin\/plugin\.json|[A-Za-z0-9_-][A-Za-z0-9_.-]*\/\.claude-plugin\/plugin\.json)$/) {
          manifests++
          prefix = name
          sub(/\.claude-plugin\/plugin\.json$/, "", prefix)
        }
      }
      END {
        split("check-file-size check-bash-read check-jq check-agent-model check-reader-contract check-final-answer", hooks, " ")
        for (i = 1; i <= 5; i++) {
          mode = modes[prefix "hooks/" hooks[i]]
          if (mode !~ /^[-?]/ || mode !~ /[xst]/) bad = 1
        }
        exit !(manifests == 1 && !bad)
      }'
  else
    echo "build-zip: cannot verify $1 (no python3/zipinfo)" >&2
    return 1
  fi
}

verify "$ZIP" || { echo "build-zip: verification failed for $ZIP" >&2; exit 1; }
echo "wrote $ZIP"
