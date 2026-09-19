"""Name where each missing gold was lost, for the 2026-09-14 reader probe.

`reviews/reader-protocol-reduction-2026-09-14.md` settled that the
`gold_confirmed` failure was pre-existing rather than a regression, but not
where it happened: `judge.gold_confirmed_source`, which splits the three
causes apart, only landed after 9346d19 (2026-09-16).

No new scorer. This calls `judge.gold_confirmed_ok` and
`judge.gold_confirmed_source` on the probe's own transcripts, and fixes two
things about how the 2026-09-14 re-judgement fed them:

* `--abs` makes the spec's `fixture_root` absolute. The probe RAN absolute
  (report.json, the worker's citations and the hooklog all carry
  /home/dev/...), but the `rejudge.*.json` specs carry a relative root.
  `gold_path_needles` then builds relative needles while `item_citations`
  only collects absolute paths, so the intersection is empty whatever the
  model wrote and every miss is blamed on the worker.
* the worker's reply comes from `Transcript.child_return_of`, not
  `result_of`. These runs launched the Agent asynchronously, so `result_of`
  returns "Async agent launched successfully." and every execution looks
  like a worker that confirmed nothing.

usage: gold-confirmed-cause-2026-09-20.py <probe-dir> [--abs]

The probe directories are untracked build output under
`evals/compare/tmp/`: `cost-probe/20260914-204044` (after the change) and
`cost-probe-baseline/20260914-214327` (plugin/ reverted to 1ad21b0).
"""
import collections
import glob
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "evals", "compare"))
import judge  # noqa: E402

CASE = "auto-explicit-multifile"


def main(argv):
    base = argv[0]
    absolute = "--abs" in argv[1:]
    causes = collections.Counter()
    for spec_path in sorted(glob.glob(os.path.join(base, "rejudge.%s.*.json" % CASE))):
        spec = json.load(open(spec_path))
        if absolute and not spec["fixture_root"].startswith("/"):
            spec["fixture_root"] = os.path.join(REPO, spec["fixture_root"])
        stem = os.path.basename(spec_path)[len("rejudge."):-len(".json")]
        transcript = os.path.join(base, "transcripts", stem + ".jsonl")
        if not os.path.exists(transcript):
            print("%-38s NO TRANSCRIPT" % stem)
            continue
        tr = judge.Transcript(judge.load_events(transcript))
        final = tr.final_text()
        replies = []
        for use in tr.agent_uses():
            reply = tr.child_return_of(use)
            if reply and reply.get("text"):
                replies.append(judge.child_model_text(reply["text"]))
        missing = judge.gold_confirmed_ok(final, spec["gold"], spec)
        named = [judge.gold_confirmed_source(g, replies, spec) for g in missing]
        causes.update(named)
        print("%-38s parent_items=%d worker_items=%d missing=%d/%d  %s"
              % (stem, len(judge.confirmed_items(final)),
                 sum(len(judge.confirmed_items(t)) for t in replies),
                 len(missing), len(spec["gold"]), sorted(set(named)) or "-"))
    print("causes:", dict(causes))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
