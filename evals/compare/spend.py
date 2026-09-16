#!/usr/bin/env python3
"""What a set of run directories has cost so far.

A cost cap written in a pre-registration is not a stop rule until the loop
that spends measures spend and exits. On 2026-09-17 a $30 cap ran to $36.55
because seventy runs went out as one loop with no checkpoint
(reviews/scope-interleaved-2026-09-17.md section 6). This is the checkpoint:

    for i in $(seq 1 70); do
      python3 evals/compare/spend.py --cap 40 /tmp/ts-t /tmp/ts-c || break
      ...
    done

A stream-json transcript reports a running total, so each transcript counts
once, by its last `total_cost_usd`. Not part of the release gate.

Exit codes: 0 under the cap, 3 at or over it, 2 for a usage error. Over-cap
is its own code so a mistyped cap cannot be read as "stop".
"""
import json
import os
import sys

OVER_CAP = 3
USAGE = 2


def transcript_cost(path):
    """The last total_cost_usd in one transcript, or None."""
    last = None
    try:
        with open(path, encoding='utf-8', errors='replace') as source:
            for line in source:
                try:
                    row = json.loads(line)
                except ValueError:
                    # A truncated or interleaved line is exactly the state a
                    # caller is in when it needs the number most.
                    continue
                if isinstance(row, dict) and 'total_cost_usd' in row:
                    value = row['total_cost_usd']
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        last = float(value)
    except OSError:
        return None
    return last


def spent(roots):
    total = 0.0
    for root in roots:
        for base, _dirs, names in os.walk(root):
            for name in names:
                if not name.endswith('.jsonl'):
                    continue
                cost = transcript_cost(os.path.join(base, name))
                if cost is not None:
                    total += cost
    return total


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cap = None
    if argv and argv[0] == '--cap':
        if len(argv) < 2:
            print('usage: spend.py [--cap USD] <dir> [...]', file=sys.stderr)
            return USAGE
        try:
            cap = float(argv[1])
        except ValueError:
            print('cap must be a number: %s' % argv[1], file=sys.stderr)
            return USAGE
        if not cap > 0:
            print('cap must be positive: %s' % argv[1], file=sys.stderr)
            return USAGE
        argv = argv[2:]
    if not argv:
        print('usage: spend.py [--cap USD] <dir> [...]', file=sys.stderr)
        return USAGE
    for root in argv:
        if not os.path.isdir(root):
            print('not a directory: %s' % root, file=sys.stderr)
            return USAGE
    total = spent(argv)
    print('%.4f' % total)
    if cap is not None and total >= cap:
        print('stop: $%.4f has reached the $%.4f cap' % (total, cap), file=sys.stderr)
        return OVER_CAP
    return 0


if __name__ == '__main__':
    sys.exit(main())
