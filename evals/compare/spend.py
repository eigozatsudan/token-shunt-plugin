#!/usr/bin/env python3
"""What a set of run directories has cost so far.

A cost cap written in a pre-registration is not a stop rule until the loop
that spends measures spend and exits. On 2026-09-17 a $30 cap ran to $36.55
because seventy runs went out as one loop with no checkpoint
(reviews/scope-interleaved-2026-09-17.md section 6). This is the checkpoint:

    for i in $(seq 1 70); do
      python3 evals/compare/spend.py --cap 40 --reserve 0.55 /tmp/ts-t /tmp/ts-c || break
      ...
    done

`--reserve` is what the next run is expected to cost. The check runs
*before* a run, so a bare cap overshoots by up to one run's cost: on
2026-09-17 four pairs spent $1.0868 against a $1.0 cap, because the balance
was still under it when the last one started
(reviews/pairs-tool-trial-2026-09-17.md section 3). With a reserve the
stop comes one run early, which is the only place it can come from a
check that runs beforehand.

Take the reserve from the HIGHEST recent per-run cost, not the average: an
average that underestimates the expensive tail is how the $30 cap became
$36.55 in the first place.

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


USAGE_TEXT = 'usage: spend.py [--cap USD] [--reserve USD] <dir> [...]'


def amount(name, raw):
    """A positive dollar figure, or None with the reason already printed."""
    try:
        value = float(raw)
    except ValueError:
        print('%s must be a number: %s' % (name, raw), file=sys.stderr)
        return None
    if not value > 0:
        print('%s must be positive: %s' % (name, raw), file=sys.stderr)
        return None
    return value


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cap = reserve = None
    while argv and argv[0] in ('--cap', '--reserve'):
        if len(argv) < 2:
            print(USAGE_TEXT, file=sys.stderr)
            return USAGE
        value = amount(argv[0].lstrip('-'), argv[1])
        if value is None:
            return USAGE
        if argv[0] == '--cap':
            cap = value
        else:
            reserve = value
        argv = argv[2:]
    if reserve is not None and cap is None:
        # A reserve decides nothing by itself. Ignoring it silently would
        # leave the caller believing it had asked for a stop rule.
        print('--reserve needs --cap', file=sys.stderr)
        return USAGE
    if not argv:
        print(USAGE_TEXT, file=sys.stderr)
        return USAGE
    for root in argv:
        if not os.path.isdir(root):
            print('not a directory: %s' % root, file=sys.stderr)
            return USAGE
    total = spent(argv)
    # What has been spent, not what is being held back: the reserve decides
    # the exit code and never the number a caller records.
    print('%.4f' % total)
    if cap is not None and total + (reserve or 0.0) >= cap:
        if reserve:
            print('stop: $%.4f plus the $%.4f reserved for the next run '
                  'reaches the $%.4f cap' % (total, reserve, cap), file=sys.stderr)
        else:
            print('stop: $%.4f has reached the $%.4f cap' % (total, cap),
                  file=sys.stderr)
        return OVER_CAP
    return 0


if __name__ == '__main__':
    sys.exit(main())
