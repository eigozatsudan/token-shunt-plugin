#!/usr/bin/env python3
"""Replay archived conversations through the shipped Lock B, at $0.

Spec: docs/superpowers/specs/2026-09-19-cumulative-intake-design.md 3.1
chose 16,384 bytes from a table computed with `parent_bytes.py`: 1 of 14
archived auto conversations over the line, 13 at or below 8,670. That says
what the measurement showed. It does not say what the code does.

This walks the archived transcripts read by read and asks
`intake_ledger.deny_reason` -- the hook's own function, not a restatement
of it -- whether the session was already over budget. It parses nothing
itself: `parent_turn_reads.read_rows` says what the parent read.

**It cannot say what the conversation would have done next.** A denied read
changes every turn after it, and the archive holds the conversation that
was never denied. So the ledger is charged the bytes the transcript really
took and a deny is a flag on that read, never a rewrite of the history.
`bytes_after_first_deny` is therefore "what this conversation went on to
take", not "what Lock B would have failed to stop".

Not part of the release gate. Bills nothing.
"""
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin" / "hooks"))

import intake_ledger  # noqa: E402
import parent_turn_reads  # noqa: E402

SESSION = "replay"


def _event(row, response=None):
    """The hook input a live session would have seen for this Read."""
    inp = {"file_path": row["path"]}
    for key in ("offset", "limit"):
        if row.get(key) is not None:
            inp[key] = row[key]
    event = {"session_id": SESSION, "tool_name": "Read", "tool_input": inp}
    if response is not None:
        event["hook_event_name"] = "PostToolUse"
        event["tool_response"] = response
    return event


def replay(directory, case, mode, root, budget=intake_ledger.MEASURED_BUDGET_BYTES):
    """Where Lock B would have fired in one archived conversation."""
    turns, denied, first, after = [], [], None, 0
    before = os.environ.get(intake_ledger.BUDGET_ENV)
    os.environ[intake_ledger.BUDGET_ENV] = str(budget)
    state = tempfile.mkdtemp(prefix="intake-replay-")
    try:
        for number, path in parent_turn_reads.turn_files(directory, case, mode):
            reads, taken, refused = 0, 0, []
            for row in parent_turn_reads.read_rows(path, root):
                reason = intake_ledger.deny_reason(_event(row), root=state)
                if reason:
                    refused.append(row["path"])
                    denied.append(row["path"])
                    if first is None:
                        first = number
                reads += 1
                taken += row["bytes"]
                if first is not None:
                    after += row["bytes"]
                # Charge what the transcript really took: this is a replay of
                # a conversation that happened, not a simulation of one that
                # did not.
                intake_ledger.charge(_event(row, {
                    "type": "text",
                    "file": {"filePath": row["path"],
                             "content": "x" * row["bytes"]}}), root=state)
            turns.append({"turn": number, "reads": reads, "bytes": taken,
                          "denied": refused})
    finally:
        if before is None:
            os.environ.pop(intake_ledger.BUDGET_ENV, None)
        else:
            os.environ[intake_ledger.BUDGET_ENV] = before
        for leftover in Path(state).glob("*"):
            leftover.unlink()
        os.rmdir(state)
    return {"case": case, "mode": mode, "budget": budget, "turns": turns,
            "denied": denied, "first_deny_turn": first,
            "total_reads": sum(t["reads"] for t in turns),
            "total_bytes": sum(t["bytes"] for t in turns),
            # From the first refused read onward, that read included.
            "bytes_after_first_deny": after}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    budget = intake_ledger.MEASURED_BUDGET_BYTES
    if argv and argv[0] == "--budget":
        if len(argv) < 2:
            return _usage()
        budget, argv = int(argv[1]), argv[2:]
    if len(argv) < 3:
        return _usage()
    case, mode, dirs = argv[0], argv[1], argv[2:]
    fired = 0
    for directory in dirs:
        root = parent_turn_reads.derive_root_of(directory, case, mode)
        got = replay(directory, case, mode, root, budget)
        fired += 1 if got["first_deny_turn"] else 0
        print("%-5s %-40s turns=%s bytes=%d first_deny_turn=%s denied=%d"
              % ("FIRE" if got["first_deny_turn"] else "-", directory,
                 ",".join(str(t["bytes"]) for t in got["turns"]),
                 got["total_bytes"], got["first_deny_turn"] or "-",
                 len(got["denied"])))
    print("%d/%d conversations would have been denied at budget %d"
          % (fired, len(dirs), budget))
    return 0


def _usage():
    print("usage: intake_replay.py [--budget N] <case> <mode> <dir> [...]",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
