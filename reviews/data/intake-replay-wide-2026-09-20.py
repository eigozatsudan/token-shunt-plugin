"""Replay the shipped Lock B over every archived auto conversation, at $0.

Widens reviews/intake-replay-2026-09-19.md, which covered 14 of the 239
auto conversations in the archive. Adds no logic: enumeration here,
judgement in evals/compare/intake_replay.replay, which calls the shipped
intake_ledger.deny_reason.
"""
import collections, csv, os, sys
sys.path.insert(0, "/home/dev/projects/skills/token-shunt/evals/compare")
import intake_replay, parent_turn_reads as ptr

BASE = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else None
BUDGETS = [8192, 16384, 32768, 65536]

convs = []
for dirpath, _, names in os.walk(BASE):
    for n in sorted(names):
        if n.endswith(".auto.jsonl"):
            convs.append((dirpath, n[: -len(".auto.jsonl")]))
convs.sort()

rows, summary = [], collections.defaultdict(lambda: [0, 0])
for d, case in convs:
    root = ptr.derive_root_of(d, case, "auto")
    block = os.path.relpath(d, BASE).split(os.sep)[0]
    run = next((p for p in d.split(os.sep) if p.startswith("run.")), "?")
    per = {}
    for b in BUDGETS:
        got = intake_replay.replay(d, case, "auto", root, b)
        per[b] = got
        summary[b][1] += 1
        if got["first_deny_turn"]:
            summary[b][0] += 1
    base = per[BUDGETS[0]]
    rows.append({
        "block": block, "run": run, "case": case,
        "turns": len(base["turns"]),
        "parent_reads": base["total_reads"],
        "parent_bytes": base["total_bytes"],
        **{"fire_%d" % b: (per[b]["first_deny_turn"] or 0) for b in BUDGETS},
    })

print("auto conversations replayed:", len(convs))
print("turn counts:", dict(collections.Counter(r["turns"] for r in rows)))
print("conversations with >=1 parent corpus Read:",
      sum(1 for r in rows if r["parent_reads"]))
print()
print("budget   fires   of     rate    first-deny turns")
for b in BUDGETS:
    fired, total = summary[b]
    turns = collections.Counter(r["fire_%d" % b] for r in rows if r["fire_%d" % b])
    print("%-8d %-7d %-6d %-7.3f %s" % (b, fired, total, fired / total,
                                        dict(sorted(turns.items())) or "-"))
print()
mt = [r for r in rows if r["turns"] > 1]
st = [r for r in rows if r["turns"] == 1]
for label, group in (("multi-turn", mt), ("single-turn", st)):
    print("%-12s n=%-4d" % (label, len(group)), end=" ")
    for b in BUDGETS:
        print("%d:%d" % (b, sum(1 for r in group if r["fire_%d" % b])), end="  ")
    print("  max parent bytes=%d" % max((r["parent_bytes"] for r in group),
                                        default=0))
if OUT:
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("\nwrote", OUT)
