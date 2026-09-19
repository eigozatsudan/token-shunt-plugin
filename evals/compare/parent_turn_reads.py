#!/usr/bin/env python3
"""Where in a conversation the parent took the corpus on.

`judge.py` reads one transcript per case (design 5.1), so `parent_no_read`
judges turn 1 only. In the multi-turn block turn 1 is the one turn where the
parent never reads the corpus: 0 parent corpus Reads at turn 1 against 21
across turns 2-5, in 10 of 14 conversations
(reviews/multiturn-context-2026-09-18.md section 4-2, corrected 2026-09-19).
A conversation can therefore pass `parent_no_read` and still end up holding
most of the files it was supposed to delegate.

The first count written here was 26 in 12 of 14: it charged the parent for
Reads the hook had denied. Those are the numbers this module exists to stop
producing, so it must not quote them.

This walks the follow-up transcripts `run_followups()` already writes and
reports, per turn, the Reads the parent itself issued against the corpus.

It counts a Read only when the result came back without an error: a denied
Read is the hook doing its job and nothing reached the parent. That is the
one place it departs from `parent_bytes.parent_read_bytes`, which sums the
payload and has no verdict to get wrong.

Not part of the release gate.
"""
import json
import os
import pathlib
import re
import sys

TURN = re.compile(r"\.turn(\d+)\.jsonl\Z")


def turn_files(directory, case, mode):
    """[(turn number, path)] for one conversation, first turn first.

    run.sh writes `<case>.<mode>.jsonl` and then
    `<case>.<mode>.jsonl.turn<N>.jsonl`. Without the first turn there is no
    conversation, only orphaned follow-ups.
    """
    directory = pathlib.Path(directory)
    first = directory / ("%s.%s.jsonl" % (case, mode))
    if not first.exists():
        return []
    found = [(1, first)]
    for name in os.listdir(str(directory)):
        m = TURN.search(name)
        if m and name.startswith("%s.%s.jsonl." % (case, mode)):
            found.append((int(m.group(1)), directory / name))
    return sorted(found, key=lambda pair: pair[0])


def derive_root(paths):
    """The staged corpus root, from any path that runs through it.

    The five archived blocks staged fixtures under different absolute roots,
    so asking the caller to know each one would make the instrument harder
    to point at the evidence already on disk.
    """
    for path in paths:
        head, sep, _ = str(path).partition("/work/fixtures/")
        if sep:
            return head + "/work/fixtures"
    return None


def derive_root_of(directory, case, mode):
    """The corpus root this conversation used, from its own Read paths.

    Every parent Read is offered, not only successful ones: a run whose
    corpus Reads were all denied still names the root, and that is exactly
    the run whose verdict must not silently widen to the plugin's own files.
    """
    for _, path in turn_files(directory, case, mode):
        root = derive_root(_all_read_paths(path))
        if root:
            return root
    return None


def _all_read_paths(transcript):
    try:
        source = open(transcript, encoding="utf-8", errors="replace")
    except OSError:
        return []
    found = []
    with source:
        for line in source:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            message = row.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            for block in content if isinstance(content, list) else []:
                if (isinstance(block, dict) and block.get("type") == "tool_use"
                        and block.get("name") == "Read"):
                    path = (block.get("input") or {}).get("file_path")
                    if isinstance(path, str) and path:
                        found.append(path)
    return found


def read_rows(transcript, root):
    """[{path, bytes}] for the parent's own successful Reads, in order.

    One scan serves both callers: `turn_reads` sums these, and Lock B's $0
    replay walks them in order to ask, read by read, whether the session was
    already over budget. A second parser is how a count of 26 in 12 of 14
    got published against the real 21 in 10 of 14.
    """
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
                # A truncated transcript still has to yield a number.
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
                    path, inp = call
                    if root is not None and not os.path.abspath(path).startswith(
                            os.path.abspath(root) + os.sep):
                        continue
                    found.append({
                        "path": path,
                        "bytes": len(_text(block.get("content")).encode("utf-8")),
                        "offset": inp.get("offset"), "limit": inp.get("limit")})
    return found


def turn_reads(transcript, root):
    """(count, bytes, paths) the parent itself Read under `root`."""
    found = read_rows(transcript, root)
    return (len(found), sum(r["bytes"] for r in found),
            [r["path"] for r in found])


def _text(content):
    """The result payload as text, whether a string or content blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content
                       if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


def conversation(directory, case, mode, root):
    """One conversation's per-turn corpus Reads, and whether it stayed clean."""
    turns, paths = [], []
    for number, path in turn_files(directory, case, mode):
        count, size, read = turn_reads(path, root)
        turns.append({"turn": number, "reads": count, "bytes": size,
                      "transcript": str(path)})
        paths.extend(read)
    return {
        "case": case, "mode": mode, "turns": turns, "paths": paths,
        "total_reads": sum(t["reads"] for t in turns),
        "total_bytes": sum(t["bytes"] for t in turns),
        "dirty_turns": [t["turn"] for t in turns if t["reads"]],
        "clean": not any(t["reads"] for t in turns),
    }


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = None
    if argv and argv[0] == "--root":
        if len(argv) < 2:
            return _usage()
        root, argv = argv[1], argv[2:]
    if len(argv) < 3:
        return _usage()
    case, mode, dirs = argv[0], argv[1], argv[2:]
    dirty = 0
    for directory in dirs:
        # Without a root every Read counts, including the plugin's own
        # files, so derive one per conversation: the archived blocks staged
        # their fixtures under five different absolute roots.
        got = conversation(directory, case, mode,
                           root or derive_root_of(directory, case, mode))
        dirty += 0 if got["clean"] else 1
        print("%-9s %-40s turns=%s reads=%d bytes=%d dirty=%s"
              % ("CLEAN" if got["clean"] else "DIRTY", directory,
                 ",".join(str(t["reads"]) for t in got["turns"]),
                 got["total_reads"], got["total_bytes"],
                 got["dirty_turns"] or "-"))
    print("%d/%d conversations read the corpus in the parent" % (dirty, len(dirs)))
    return 0


def _usage():
    print("usage: parent_turn_reads.py [--root DIR] <case> <mode> <dir> [...]",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
