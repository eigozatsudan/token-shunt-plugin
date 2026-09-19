"""Run the shipped coverage aggregator over the archived auto conversations.

`reviews/read-coverage-2026-09-20.md` recorded n=3 live runs and said the
sequential-recovery case did not occur in them. This widens that to every
archived auto conversation, at $0.

No new aggregator: the grouping, the interval union and the rollup are
`evals/compare/read_coverage.rows` / `.rollup`, unchanged. The only new
code is the adapter below, which builds the same event `record-coverage`
writes -- `startLine` / `numLines` / `totalLines` -- out of a transcript's
`tool_use_result.file` instead of the hook's `tool_response.file`. They are
the same object, and the adapter reproduces the hook's own CSV exactly on
the three live runs (files=2 reads=2 covered=35 total=718 coverage=0.0487).

`bytes` is NOT reproduced and is not reported: the hook records the served
body, this sees the transcript's copy of it. Every other column matches.

Parent rows only: the parent test needs `agent_id`/`agent_type`, which a
transcript does not carry, so `parent_tool_use_id` stands in for it -- the
same filter `parent_turn_reads.read_rows` uses. A worker's coverage sits at
1.0 by design and is not the headline anyway (spec section 6).

usage: read-coverage-archive-2026-09-20.py <extracted-archive-root> [out.csv]
"""
import collections
import csv
import json
import os
import sys

sys.path.insert(0, "/home/dev/projects/skills/token-shunt/evals/compare")
import parent_turn_reads as ptr
import read_coverage

KEEP = [c for c in read_coverage.COLUMNS if c != 'bytes']


def events(transcript, root):
    """record-coverage-shaped events for the parent's own corpus Reads."""
    reads, found = {}, []
    try:
        source = open(transcript, encoding="utf-8", errors="replace")
    except OSError:
        return []
    with source:
        for line in source:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict) or row.get("parent_tool_use_id") is not None:
                continue
            message = row.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("name") == "Read":
                    path = (block.get("input") or {}).get("file_path")
                    if isinstance(path, str) and path:
                        reads[block.get("id")] = (path, block.get("input") or {})
                elif block.get("type") == "tool_result":
                    call = reads.get(block.get("tool_use_id"))
                    if call is None or block.get("is_error"):
                        continue
                    path, asked = call
                    if root is not None and not os.path.abspath(path).startswith(
                            os.path.abspath(root) + os.sep):
                        continue
                    served = (row.get("tool_use_result") or {})
                    served = served.get("file") if isinstance(served, dict) else None
                    served = served if isinstance(served, dict) else {}
                    found.append({
                        "hook": "record-coverage", "file_path": path,
                        "session_id": row.get("session_id"),
                        "start": served.get("startLine"),
                        "lines": served.get("numLines"),
                        "total": served.get("totalLines"),
                        # `full_file_reads` is computed from these, and a
                        # row with neither counts as a whole-file read: an
                        # adapter that drops them turns every slice into a
                        # full read and the whole/sliced split into noise.
                        "offset": asked.get("offset"),
                        "limit": asked.get("limit")})
    return found


def main(argv):
    base = argv[0]
    out = argv[1] if len(argv) > 1 else None
    convs = []
    for dirpath, _, names in os.walk(base):
        for name in sorted(names):
            if name.endswith(".auto.jsonl"):
                convs.append((dirpath, name[: -len(".auto.jsonl")]))
    convs.sort()

    records, blocks = [], {}
    for directory, case in convs:
        root = ptr.derive_root_of(directory, case, "auto")
        block = os.path.relpath(directory, base).split(os.sep)[0]
        run = next((p for p in directory.split(os.sep) if p.startswith("run.")), "?")
        talk = "%s/%s" % (block, case)
        blocks[talk] = block
        for _turn, path in ptr.turn_files(directory, case, "auto"):
            for event in events(path, root):
                records.append(dict(event, run=run, conversation=talk,
                                    source=os.path.basename(str(path))))

    rows = read_coverage.rows(records)
    parent = read_coverage.rollup(rows, parent=True)
    print("auto conversations:", len(convs))
    print("parent corpus reads:", len(records),
          " without totalLines:", sum(1 for r in records if r["total"] is None))
    print("rows (conversation x file):", len(rows))
    print("rollup:", {k: v for k, v in parent.items() if k != "bytes"})
    print()
    sliced = [r for r in rows if not r["full_file_reads"]]
    whole = [r for r in rows if r["full_file_reads"]]
    for label, group in (("whole-file", whole), ("sliced", sliced)):
        covered = sum(r["covered"] for r in group)
        total = sum(r["total"] for r in group)
        print("%-11s rows=%-3d reads=%-3d covered=%-5d total=%-5d rate=%.4f"
              % (label, len(group), sum(r["reads"] for r in group), covered,
                 total, covered / total if total else 0))
    print()
    print("reads per (conversation, file):",
          dict(sorted(collections.Counter(r["reads"] for r in rows).items())))
    print("segments after union:",
          dict(sorted(collections.Counter(r["segments"] for r in rows).items())))
    print("total overlap (lines read twice):", parent["overlap"])
    print()
    print("blocks:", dict(sorted(collections.Counter(
        blocks[r["conversation"]] for r in rows).items())))
    if out:
        with open(out, "w", newline="") as handle:
            writer = csv.DictWriter(handle, KEEP, extrasaction="ignore")
            writer.writeheader()
            for row in sorted(rows, key=lambda r: (-r["coverage"], r["conversation"])):
                writer.writerow(row)
        print("\nwrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
