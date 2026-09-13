#!/usr/bin/env bash
# Build the distributable plugin ZIP (design §6, §13).
# Primary artifact = contents of plugin/ (plugin.json at archive root).
set -euo pipefail
export LC_ALL=C
cd "$(dirname "$0")/.."
ROOT=$PWD
ZIP=$ROOT/token-shunt.zip

chmod +x plugin/hooks/check-file-size plugin/hooks/check-bash-read plugin/hooks/check-jq
rm -f "$ZIP"

if command -v zip >/dev/null 2>&1; then
  (cd plugin && zip -q -r "$ZIP" .)
elif command -v python3 >/dev/null 2>&1; then
  python3 - "$ROOT/plugin" "$ZIP" <<'PY'
import os, stat, sys, zipfile
root, zp = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
    for dp, dns, fns in os.walk(root):
        dns.sort()
        for fn in sorted(fns):
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
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
names = z.namelist()
pj = [n for n in names if n == '.claude-plugin/plugin.json'
      or (n.endswith('/.claude-plugin/plugin.json') and n.count('/') == 2)]
need = {'check-file-size', 'check-bash-read', 'check-jq'}
hooks = {n.split('/')[-1]: n for n in names if n.split('/')[-1] in need}
bad = [n for k, n in hooks.items()
       if not ((z.getinfo(n).external_attr >> 16) & 0o111)]
sys.exit(0 if pj and set(hooks) == need and not bad else 1)
PY
  elif command -v zipinfo >/dev/null 2>&1; then
    zipinfo -l "$1" | awk '
      /\.claude-plugin\/plugin\.json$/ { pj=1 }
      /(^|\/)hooks\/check-(file-size|bash-read|jq)$/ {
        if ($1 ~ /x/) ok++; else bad++ }
      END { exit !((pj || 0) && ok == 3 && !bad) }'
  else
    echo "build-zip: cannot verify $1 (no python3/zipinfo)" >&2
    return 1
  fi
}

verify "$ZIP" || { echo "build-zip: verification failed for $ZIP" >&2; exit 1; }
echo "wrote $ZIP"
