# token-shunt distribution

Shipping: keeps large bodies out of the parent; **cost reduction is
unproven**. Cost claims only when §26.5 is not worse than direct.
Isolation pass and cost regression are not separate product editions.

## Build

```bash
scripts/build-zip.sh   # chmod +x on hooks, zips plugin/ -> token-shunt.zip,
                       # then verifies layout + exec bits (fails nonzero)
```

ZIP layout contract (design §6, §13):

- `.claude-plugin/plugin.json` at the archive root or exactly one directory
  down. `marketplace.json` is **not** in the ZIP.
- `hooks/check-file-size`, `hooks/check-bash-read`, `hooks/check-jq` must carry
  the Unix exec bit inside the ZIP — hooks.json uses exec form (`"args": []`),
  which spawns the files directly.

## Install

```bash
claude --plugin-dir ./token-shunt.zip   # or: --plugin-dir plugin/
```

Marketplace route: the repository root holds `.claude-plugin/marketplace.json`
(required fields: `name`, `owner.name`, `plugins`; `plugins[].source` is
`./plugin`). Add the repo root as a marketplace, then install `token-shunt`.

PR1 zips are for development. Shipping requires the PR2 gates in
`docs/2026-09-12-token-shunt-design.md` §26.6 (suite A + suite B, isolation,
mandatory parent-token measurement).
