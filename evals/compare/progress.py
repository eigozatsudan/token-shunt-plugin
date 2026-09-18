#!/usr/bin/env python3
"""How many run directories finished, and how many produced nothing.

A driver that retries until a run completes has no bound on how many times
it may fail to complete one. On 2026-09-17 the CLI was down for about an
hour and the driver kept retrying, leaving 450 run directories with no
summary.json (reviews/django-dose-2026-09-17.md section 7.2). That cost
$0.0000 because the failures happened before the model was reached, which
is luck and not a bound. This is the bound:

    for i in $(seq 1 80); do
      python3 evals/compare/progress.py --max-barren 10 /tmp/ts-plan || break
      python3 evals/compare/spend.py --cap 21 --reserve 0.80 /tmp/ts-plan || break
      ...
    done

A run directory is barren when it carries no summary.json that loads as an
object. That is the same file `pairs.py` requires before it will score a
run and the same shape `run.sh` requires before it copies one forward, so a
barren run is exactly one no measurement can use.

Unlike the cost cap this takes no reserve: it counts what has already
failed, so there is nothing to hold back for the next run. It counts every
barren run in the roots, not a consecutive streak -- a driver that fails
one run in three still never finishes, and a streak resets on the one that
succeeds.

Exit codes: 0 under the cap, 3 at or over it, 2 for a usage error. Over-cap
is its own code so a mistyped cap cannot be read as "stop".
"""
import json
import os
import sys

OVER_CAP = 3
USAGE = 2

USAGE_TEXT = 'usage: progress.py [--max-barren N] <dir> [...]'


def summarized(path):
    """Whether this run left the summary object a measurement can score."""
    try:
        with open(path, encoding='utf-8') as source:
            return isinstance(json.load(source), dict)
    except (OSError, ValueError):
        # Unreadable and half-written are the states a run is in when it
        # failed, which is what the cap is counting.
        return False


def counted(roots):
    """(finished, barren) over the run directories directly under each root."""
    finished = barren = 0
    for root in roots:
        for name in sorted(os.listdir(root)):
            run = os.path.join(root, name)
            if not os.path.isdir(run):
                continue           # last-run.json and friends are not runs
            if summarized(os.path.join(run, 'summary.json')):
                finished += 1
            else:
                barren += 1
    return finished, barren


def cap_from(raw):
    """A positive whole number, or None with the reason already printed."""
    try:
        value = int(raw)
    except ValueError:
        print('max-barren must be a whole number: %s' % raw, file=sys.stderr)
        return None
    if value < 1:
        # Zero would stop before the first run went out, which is never what
        # a driver meant to ask for.
        print('max-barren must be positive: %s' % raw, file=sys.stderr)
        return None
    return value


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cap = None
    while argv and argv[0] == '--max-barren':
        if len(argv) < 2:
            print(USAGE_TEXT, file=sys.stderr)
            return USAGE
        cap = cap_from(argv[1])
        if cap is None:
            return USAGE
        argv = argv[2:]
    if not argv:
        print(USAGE_TEXT, file=sys.stderr)
        return USAGE
    for root in argv:
        if not os.path.isdir(root):
            print('not a directory: %s' % root, file=sys.stderr)
            return USAGE
    finished, barren = counted(argv)
    print('%d %d' % (finished, barren))
    if cap is not None and barren >= cap:
        print('stop: %d run directories carry no summary.json, reaching the '
              'cap of %d' % (barren, cap), file=sys.stderr)
        return OVER_CAP
    return 0


if __name__ == '__main__':
    sys.exit(main())
