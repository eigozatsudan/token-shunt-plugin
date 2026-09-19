"""Did parents keep the worker's confirmed lines, once 7f5fb43 reminded them?

`7f5fb43` (2026-09-16) states the retention rule at every worker launch,
because the deny that used to carry it never reaches an explicitly
delegated call. This asks the archive whether the reminder was enough.

No new check: the verdict is the shipped `sendback_retention.run_all`,
the same function `check-final-answer` decides a send-back with. The
worker's reply comes from `Transcript.child_return_of`, which resolves an
async launch into the completion notification.

`exists` is overridden: `classify_path` calls `os.path.exists`, and an
archived run's staged corpus is long deleted, so every citation would come
back UNDETERMINED. Treating any path under `/work/fixtures/` as present
reproduces the answer the hook would have given while the run was live.
It is an override, and it is the one assumption here that is not the
shipped code's own.

usage: retention-after-reminder-2026-09-20.py <extracted-archive-root>
"""
import collections, os, re, sys
sys.path.insert(0, "/home/dev/projects/skills/token-shunt/evals/compare")
sys.path.insert(0, "/home/dev/projects/skills/token-shunt/plugin/hooks")
import judge, parent_turn_reads as ptr, sendback_retention as sr

BASE = sys.argv[1]
REMINDER = "Copy each one into your final answer verbatim"
FIXTURE = re.compile(r"/work/fixtures/")
staged = lambda p: bool(FIXTURE.search(p or ""))

convs = []
for dp, _, names in os.walk(BASE):
    for n in sorted(names):
        if n.endswith(".auto.jsonl"):
            convs.append((dp, n[:-len(".auto.jsonl")]))
convs.sort()

verdicts = collections.Counter()
reminded = with_items = 0
examples = []
for d, case in convs:
    for _t, path in ptr.turn_files(d, case, "auto"):
        raw = open(path, encoding="utf-8", errors="replace").read()
        if REMINDER not in raw:
            continue
        reminded += 1
        tr = judge.Transcript(judge.load_events(str(path)))
        child = []
        for use in tr.agent_uses():
            r = tr.child_return_of(use)
            if r and r.get("text"):
                child.append(judge.child_model_text(r["text"]))
        if not child:
            verdicts["no worker reply resolved"] += 1
            continue
        got = sr.run_all(child, tr.final_text(), exists=staged)
        if got["child_items"]["status"] != sr.OK:
            verdicts["child_items:" + got["child_items"]["status"]] += 1
            continue
        with_items += 1
        v = got["line_retention"]["status"]
        verdicts["line_retention:" + v] += 1
        if v == sr.VIOLATION and len(examples) < 3:
            examples.append((os.path.basename(str(path)),
                             got["line_retention"].get("detail")
                             or got["line_retention"]))
print("turns carrying the reminder:", reminded)
print("of those, worker items present:", with_items)
for k, v in sorted(verdicts.items()):
    print("  %-34s %d" % (k, v))
for name, detail in examples:
    print("\n--", name, "\n  ", str(detail)[:300])
