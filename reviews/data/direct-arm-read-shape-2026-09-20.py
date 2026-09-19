"""Count, over every archived direct-arm conversation, how the unimpeded
parent took files on: whole file, or slices.

Reuses parent_turn_reads.read_rows (the repo's only parent-Read parser,
which already drops denied Reads via is_error) and
routing_checks._returned_range (the repo's only Read-prefix parser)."""
import collections, csv, os, re, sys
sys.path.insert(0, "/home/dev/projects/skills/token-shunt/evals/compare")
import parent_turn_reads as ptr
import routing_checks
import json

ROOT = sys.argv[1]
TURN = re.compile(r"\.turn\d+\.jsonl\Z")

def conv_key(name):
    stem = TURN.sub("", name)
    return stem

rows = []
for dirpath, _, names in os.walk(ROOT):
    for name in sorted(names):
        if not name.endswith(".jsonl") or ".direct." not in name:
            continue
        path = os.path.join(dirpath, name)
        root = ptr.derive_root(ptr._all_read_paths(path))
        if root is None:
            continue
        for r in ptr.read_rows(path, root):
            rows.append({
                "run": next((p for p in path.split(os.sep) if p.startswith("run.")), "?"),
                "conversation": conv_key(name),
                "file_path": r["path"],
                "offset": r["offset"], "limit": r["limit"],
                "bytes": r["bytes"],
            })

by = collections.defaultdict(list)
for r in rows:
    by[(r["run"], r["conversation"], r["file_path"])].append(r)

sliced = [k for k, v in by.items() if any(x["offset"] or x["limit"] for x in v)]
multi = [k for k, v in by.items() if len(v) > 1]
convs = {(r["run"], r["conversation"]) for r in rows}
print("direct conversations with >=1 parent corpus Read:", len(convs))
print("parent corpus Reads:", len(rows))
print("rows (run,conversation,file):", len(by))
print("reads/row:", dict(collections.Counter(len(v) for v in by.values())))
print("rows with any offset/limit (a slice):", len(sliced))
print("rows read more than once:", len(multi))
for k in sliced[:10]:
    print("   SLICED", k, [(x["offset"], x["limit"]) for x in by[k]])
out = sys.argv[2] if len(sys.argv) > 2 else None
if out:
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, ["run", "conversation", "file_path", "reads",
                                "sliced_reads", "bytes"])
        w.writeheader()
        for (run, conv, fp), v in sorted(by.items()):
            w.writerow({"run": run, "conversation": conv, "file_path": fp,
                        "reads": len(v),
                        "sliced_reads": sum(1 for x in v if x["offset"] or x["limit"]),
                        "bytes": sum(x["bytes"] for x in v)})
    print("wrote", out)
