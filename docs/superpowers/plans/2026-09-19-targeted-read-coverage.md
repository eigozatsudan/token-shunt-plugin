# targeted Read 被覆率計器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 親が `offset`+`limit` の刻み読みで原本の何割を回収したかを、実機の PostToolUse で記録し、ファイル単位の被覆率として集計する。

**Architecture:** 判定を出せないフック 1 本（`record-coverage`）が Read 1 回につき JSONL 1 行を既存の `write-hook-log` に流し、事後の集計器（`read_coverage.py`）が `(session, agent, path)` ごとに行域の和集合を取る。状態ファイルなし、閾値なし、deny 経路なし。

**Tech Stack:** Python 3（標準ライブラリのみ）、bash、`unittest`。既存の `write-hook-log` / `hooks.json` / `evals/compare/run.sh`。

**Spec:** `docs/superpowers/specs/2026-09-19-targeted-read-coverage-design.md`

## Global Constraints

- **このフックは deny してはならない。** stdout に何も書かない。`hookSpecificOutput` という文字列がソースに出現してはならない（spec §4）。
- **状態ファイルを作らない。** `token-shunt-intake-*` / `token-shunt-reader-*` / 新規の状態ディレクトリ、いずれも作らない（spec §4）。
- **`intake_ledger` を import しない。** Lock B の budget=0 不活性と生死を共有しない（spec §4）。
- **`TOKEN_SHUNT_HOOK_LOG` が未設定なら 1 バイトも書かない。新しい環境変数を増やさない**（spec §5）。
- **失敗しても exit 0。** `main()` 全体を try/except で包む（spec §4）。
- **`start`/`lines`/`total` は `tool_response.file` の `startLine`/`numLines`/`totalLines` をそのまま使う。フックが数え直さない**（spec §3）。
- **Read のみ。Bash は対象外**（spec §3、§8.3）。
- **閾値を持たない。判定列を作らない**（spec §8.4）。
- **`evals` の release gate に入れない**（spec §8.5）。
- **課金しない。** 全テストはローカルの合成イベントで回る（spec §7）。
- commit message は必ず次の 2 行で終わる:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01Ea4ect8vUPUdiaXkjn2q8w`

## File Structure

| ファイル | 責務 |
|---|---|
| `plugin/hooks/record-coverage`（新規、755） | PostToolUse/Read の 1 イベント → JSONL 1 行。`record(event)` が純粋関数、`main()` が I/O。 |
| `plugin/hooks/hooks.json`（修正） | PostToolUse/Read の `record-intake` の後ろに登録。 |
| `evals/test_record_coverage.py`（新規） | フックの単体テストと配線テスト。 |
| `evals/compare/read_coverage.py`（新規） | hooklog → ファイル単位の行。和集合の算術と CSV。 |
| `evals/compare/test_read_coverage.py`（新規） | 集計器の単体テストとエンドツーエンド。 |
| `evals/compare/run.sh`（修正、`_claude_call` 内 L400 付近） | `TOKEN_SHUNT_HOOK_LOG` を run ディレクトリ配下へ pass-through。 |
| `evals/compare/test_runner.py`（修正） | pass-through のテスト。 |

---

### Task 1: `record(event)` —— 1 イベントを 1 行にする純粋関数

**Files:**
- Create: `plugin/hooks/record-coverage`
- Test: `evals/test_record_coverage.py`

**Interfaces:**
- Consumes: なし（最初のタスク）
- Produces: `record(event) -> dict | None`。`event` は PostToolUse のフック入力 dict。返す dict のキーは
  `hook`(str, 常に `"record-coverage"`), `session_id`(str|None), `agent_id`(str|None),
  `file_path`(str), `start`(int|None), `lines`(int|None), `total`(int|None),
  `bytes`(int), `offset`(int|None), `limit`(int|None), `is_error`(bool)。
  Read 以外・`file_path` 無しは `None`。

- [ ] **Step 1: Write the failing test**

`evals/test_record_coverage.py` を新規作成:

```python
"""The coverage instrument records; it never decides.

Spec: docs/superpowers/specs/2026-09-19-targeted-read-coverage-design.md

18 of 21 archived parent corpus Reads were targeted (offset+limit), which
Lock B never denies by design. This hook measures that route. It has no
deny path, no state file, and no threshold, and each test below names the
production change that would break it.
"""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HOOKS = Path(__file__).resolve().parents[1] / 'plugin' / 'hooks'
SOURCE = HOOKS / 'record-coverage'
hook = importlib.util.module_from_spec(
    importlib.util.spec_from_loader(
        'record_coverage',
        importlib.machinery.SourceFileLoader('record_coverage', str(SOURCE))))
# Execute the source directly so loading this extensionless hook cannot
# leave bytecode inside the distributable plugin tree.
exec(compile(SOURCE.read_bytes(), str(SOURCE), 'exec'), hook.__dict__)


def event(path='/corpus/migration.py', start=139, lines=50, total=316,
          content='x' * 2814, offset=139, limit=50, agent_id=None,
          is_error=False, **extra):
    response = {'type': 'text', 'file': {
        'filePath': path, 'content': content,
        'startLine': start, 'numLines': lines, 'totalLines': total}}
    if is_error:
        response['is_error'] = True
    body = {'hook_event_name': 'PostToolUse', 'tool_name': 'Read',
            'session_id': 's1', 'agent_id': agent_id,
            'tool_input': {'file_path': path},
            'tool_response': response}
    if offset is not None:
        body['tool_input']['offset'] = offset
    if limit is not None:
        body['tool_input']['limit'] = limit
    body.update(extra)
    return body


class RecordTests(unittest.TestCase):
    def test_the_line_range_comes_from_the_tool_response(self):
        # Fails if the hook ever counts lines itself instead of reading
        # startLine/numLines/totalLines back.
        got = hook.record(event())
        self.assertEqual(('record-coverage', 's1', None, '/corpus/migration.py'),
                         (got['hook'], got['session_id'], got['agent_id'],
                          got['file_path']))
        self.assertEqual((139, 50, 316), (got['start'], got['lines'], got['total']))
        self.assertEqual((139, 50), (got['offset'], got['limit']))
        self.assertEqual(2814, got['bytes'])
        self.assertIs(False, got['is_error'])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/dev/projects/skills/token-shunt && python3 -m pytest evals/test_record_coverage.py -v`
Expected: FAIL —— `record-coverage` が存在しないので `FileNotFoundError` で collection error になる。**これは「期待した失敗」ではない。** まず空のファイルを作る:

```bash
printf '#!/usr/bin/env python3\n' > plugin/hooks/record-coverage
```

再実行して `AttributeError: module 'record_coverage' has no attribute 'record'` を見る。**この失敗を見てから次へ進む。**

- [ ] **Step 3: Write minimal implementation**

`plugin/hooks/record-coverage` を次の内容にする:

```python
#!/usr/bin/env python3
"""PostToolUse: record how much of a file the parent took, and decide nothing.

Spec: docs/superpowers/specs/2026-09-19-targeted-read-coverage-design.md

Lock B never denies a targeted Read, and 18 of the 21 archived parent corpus
Reads were targeted (reviews/intake-replay-2026-09-19.md section 4). That is
the route this measures. It does not narrow it.

It writes one JSON line per Read through `write-hook-log` and produces no
protocol output at all: there is no code path here that can refuse a call.
`totalLines` is the reason the instrument lives in the hook rather than in a
transcript reader -- a transcript carries only `cat -n` text, so the
denominator is available here and nowhere else.
"""


def record(event):
    """One log line for one Read, or None when there is nothing to record."""
    if not isinstance(event, dict) or event.get('tool_name') != 'Read':
        return None
    inp = event.get('tool_input')
    inp = inp if isinstance(inp, dict) else {}
    path = inp.get('file_path')
    if not isinstance(path, str) or not path:
        return None
    response = event.get('tool_response')
    response = response if isinstance(response, dict) else {}
    file = response.get('file')
    file = file if isinstance(file, dict) else {}
    # A failed read makes no claim about which lines arrived; the row stays
    # so the count of attempts is not quietly lowered.
    failed = bool(response.get('is_error') or response.get('error')
                  or event.get('error'))
    content = file.get('content')
    return {
        'hook': 'record-coverage',
        'session_id': _str(event.get('session_id')),
        'agent_id': _str(event.get('agent_id')),
        'file_path': path,
        'start': None if failed else _int(file.get('startLine')),
        'lines': None if failed else _int(file.get('numLines')),
        'total': None if failed else _int(file.get('totalLines')),
        'bytes': 0 if failed or not isinstance(content, str)
                 else len(content.encode('utf-8')),
        'offset': _int(inp.get('offset')),
        'limit': _int(inp.get('limit')),
        'is_error': failed,
    }


def _int(value):
    return value if type(value) is int else None


def _str(value):
    return value if isinstance(value, str) and value else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest evals/test_record_coverage.py -v`
Expected: PASS（1 件）

- [ ] **Step 5: Commit**

```bash
git add plugin/hooks/record-coverage evals/test_record_coverage.py
git commit -m "$(cat <<'EOF'
feat: turn one Read into one coverage line

totalLines is why this lives in the hook: a transcript carries only cat -n
text, so the denominator exists here and nowhere else.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ea4ect8vUPUdiaXkjn2q8w
EOF
)"
```

---

### Task 2: 記録の欠損と異常入力

**Files:**
- Modify: `plugin/hooks/record-coverage`（必要なら）
- Test: `evals/test_record_coverage.py`（`RecordTests` に追加）

**Interfaces:**
- Consumes: Task 1 の `record(event) -> dict | None`
- Produces: 追加の公開関数なし。`record` の契約が固まる。

- [ ] **Step 1: Write the failing tests**

`RecordTests` の中に追加:

```python
    def test_a_failed_read_keeps_the_row_but_claims_no_lines(self):
        # Fails if the hook drops error rows: the count of attempts would
        # silently fall, which is how a corrected count of 21 in 10 of 14
        # once got published as 26 in 12 of 14.
        got = hook.record(event(is_error=True))
        self.assertEqual((None, None, None, 0),
                         (got['start'], got['lines'], got['total'], got['bytes']))
        self.assertIs(True, got['is_error'])
        self.assertEqual('/corpus/migration.py', got['file_path'])

    def test_a_full_read_records_no_offset_and_no_limit(self):
        # The hook must not decide what counts as "targeted"; it reports the
        # raw input and lets the aggregator define it.
        got = hook.record(event(offset=None, limit=None, start=1, lines=316))
        self.assertEqual((None, None), (got['offset'], got['limit']))
        self.assertEqual((1, 316, 316), (got['start'], got['lines'], got['total']))

    def test_a_worker_read_carries_its_agent_id(self):
        # Fails if agent_id is dropped: parent and worker coverage would be
        # summed together, and the number would mean nothing.
        self.assertEqual('a7', hook.record(event(agent_id='a7'))['agent_id'])

    def test_a_non_read_event_records_nothing(self):
        self.assertIsNone(hook.record(dict(event(), tool_name='Bash')))

    def test_a_malformed_response_records_a_row_without_line_numbers(self):
        # Fails if the hook raises on junk: a telemetry crash must not reach
        # the tool call.
        for junk in ('', [], {'file': 'not-an-object'}, {'file': {'startLine': 'x'}}):
            with self.subTest(junk=junk):
                got = hook.record(dict(event(), tool_response=junk))
                self.assertEqual('/corpus/migration.py', got['file_path'])
                self.assertIsNone(got['start'])

    def test_an_event_without_a_path_records_nothing(self):
        self.assertIsNone(hook.record(dict(event(), tool_input={})))
        self.assertIsNone(hook.record(dict(event(), tool_input='junk')))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest evals/test_record_coverage.py -v`
Expected: Task 1 の実装が既にこれらを満たしていれば **PASS してしまう。** その場合は
**テストが本番の変更を捕まえられるか mutation で確かめる**（下記 Step 3）。
`_int` を `int(value)` に変えると `test_a_malformed_response_...` が
`ValueError` で落ちる —— それを確認してから元に戻す。

- [ ] **Step 3: Mutation-check each new test**

1 つずつ本番を壊して、対応するテストだけが落ちることを見る:

```bash
# 1) error 行を捨てる -> test_a_failed_read_keeps_the_row_but_claims_no_lines
sed -i "s/    if not isinstance(path, str) or not path:/    if not isinstance(path, str) or not path or event.get('tool_response', {}).get('is_error'):/" plugin/hooks/record-coverage
python3 -m pytest evals/test_record_coverage.py -v   # 1 fail を確認
git checkout plugin/hooks/record-coverage

# 2) agent_id を落とす -> test_a_worker_read_carries_its_agent_id
sed -i "s/'agent_id': _str(event.get('agent_id')),/'agent_id': None,/" plugin/hooks/record-coverage
python3 -m pytest evals/test_record_coverage.py -v   # 1 fail を確認
git checkout plugin/hooks/record-coverage
```

**落ちなかったテストは、書き直すか捨てる。**

- [ ] **Step 4: Run the full file**

Run: `python3 -m pytest evals/test_record_coverage.py -v`
Expected: PASS（7 件）

- [ ] **Step 5: Commit**

```bash
git add evals/test_record_coverage.py plugin/hooks/record-coverage
git commit -m "$(cat <<'EOF'
test: pin the coverage row's missing cases

A failed read keeps its row and claims no lines, a worker read keeps its
agent_id, and junk in tool_response never raises. Each of the three was
mutation-checked against the production line that would break it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ea4ect8vUPUdiaXkjn2q8w
EOF
)"
```

---

### Task 3: `main()` —— 書き出し、既定 OFF、deny 経路なし

**Files:**
- Modify: `plugin/hooks/record-coverage`
- Modify: `plugin/hooks/hooks.json`（PostToolUse/Read の `record-intake` の後ろ）
- Test: `evals/test_record_coverage.py`

**Interfaces:**
- Consumes: Task 1–2 の `record(event) -> dict | None`
- Produces: `main() -> None`（stdin から 1 イベントを読み、`TOKEN_SHUNT_HOOK_LOG` があれば
  `write-hook-log` に 1 行流す）。実行ファイルとしての契約: **exit 0、stdout 空。**

- [ ] **Step 1: Write the failing tests**

`evals/test_record_coverage.py` に追加:

```python
class EntryPointTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith('TOKEN_SHUNT_')}
        self.env['TMPDIR'] = str(self.root / 'tmp')
        os.mkdir(self.env['TMPDIR'])

    def run_hook(self, body, log=None):
        env = dict(self.env)
        if log is not None:
            env['TOKEN_SHUNT_HOOK_LOG'] = str(log)
        return subprocess.run([sys.executable, str(SOURCE)],
                              input=json.dumps(body), text=True, timeout=10,
                              capture_output=True, env=env)

    def test_a_read_appends_one_line_to_the_hook_log(self):
        log = self.root / 'hooklog'
        result = self.run_hook(event(), log)
        self.assertEqual((0, '', ''), (result.returncode, result.stdout, result.stderr))
        rows = [json.loads(l) for l in log.read_text().splitlines()]
        self.assertEqual(1, len(rows))
        self.assertEqual(('record-coverage', 139, 50, 316),
                         (rows[0]['hook'], rows[0]['start'], rows[0]['lines'],
                          rows[0]['total']))

    def test_without_a_log_path_it_writes_nothing_at_all(self):
        # Fails if the instrument is ever switched on by default: an
        # unmeasured mechanism ships off.
        result = self.run_hook(event())
        self.assertEqual((0, '', ''), (result.returncode, result.stdout, result.stderr))
        self.assertEqual([], list(self.root.rglob('*hooklog*')))

    def test_it_creates_no_state_directory(self):
        # Fails if this is ever rewritten as a ledger: Lock A and Lock B are
        # two state files already, and a third would be a third way to break.
        self.run_hook(event(), self.root / 'hooklog')
        self.assertEqual([], sorted(Path(self.env['TMPDIR']).glob('token-shunt-*')))

    def test_junk_on_stdin_exits_zero_and_says_nothing(self):
        for junk in ('', 'not json', '[]', 'null'):
            with self.subTest(junk=junk):
                result = subprocess.run(
                    [sys.executable, str(SOURCE)], input=junk, text=True,
                    timeout=10, capture_output=True,
                    env=dict(self.env, TOKEN_SHUNT_HOOK_LOG=str(self.root / 'j')))
                self.assertEqual((0, '', ''),
                                 (result.returncode, result.stdout, result.stderr))

    def test_the_hook_has_no_way_to_deny_anything(self):
        # The safety property is structural, not behavioural: if a decision
        # path is ever added, this fails before any test of its behaviour.
        source = SOURCE.read_text()
        for forbidden in ('hookSpecificOutput', 'permissionDecision',
                          'intake_ledger'):
            self.assertNotIn(forbidden, source)

    def test_stdout_stays_empty_even_for_a_read_it_records(self):
        result = self.run_hook(event(), self.root / 'hooklog')
        self.assertEqual('', result.stdout)


class WiringTests(unittest.TestCase):
    def test_the_hook_is_registered_after_record_intake_on_post_read(self):
        config = json.loads((HOOKS / 'hooks.json').read_text())
        post = [g for g in config['hooks']['PostToolUse']
                if g.get('matcher') == 'Read'][0]['hooks']
        names = [h['command'].rsplit('/', 1)[-1] for h in post]
        self.assertEqual(['check-reader-contract', 'record-intake',
                          'record-coverage'], names)

    def test_the_hook_is_executable(self):
        self.assertTrue(os.access(str(SOURCE), os.X_OK))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest evals/test_record_coverage.py -v`
Expected: FAIL —— `test_a_read_appends_one_line...` は空のログ、
`WiringTests` は `hooks.json` に `record-coverage` が無い、
`test_the_hook_is_executable` は実行権限が無い。

- [ ] **Step 3: Write minimal implementation**

`plugin/hooks/record-coverage` の末尾に追加:

```python
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    """Read one PostToolUse event and, if telemetry is on, log one line."""
    if not os.environ.get('TOKEN_SHUNT_HOOK_LOG'):
        return
    row = record(json.load(sys.stdin))
    if row is None:
        return
    # write-hook-log owns the refusal to write to FIFOs, symlinks and the
    # protocol streams; duplicating those checks here would mean two copies
    # to keep right.
    subprocess.run([sys.executable, str(Path(__file__).resolve().parent
                                        / 'write-hook-log')],
                   input=json.dumps(row), text=True, timeout=5)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        pass  # Telemetry must never reach the tool call it is watching.
    sys.exit(0)
```

実行権限と配線:

```bash
chmod 755 plugin/hooks/record-coverage
python3 - <<'PY'
import json, pathlib
p = pathlib.Path('plugin/hooks/hooks.json')
config = json.loads(p.read_text())
group = [g for g in config['hooks']['PostToolUse'] if g.get('matcher') == 'Read'][0]
assert [h['command'].rsplit('/', 1)[-1] for h in group['hooks']] == [
    'check-reader-contract', 'record-intake'], 'unexpected PostToolUse/Read order'
group['hooks'].append({'type': 'command',
                       'command': '${CLAUDE_PLUGIN_ROOT}/hooks/record-coverage',
                       'args': [], 'timeout': 10})
p.write_text(json.dumps(config, indent=2) + '\n')
PY
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest evals/test_record_coverage.py -v`
Expected: PASS（15 件）

そして**既存の配線テストを壊していないこと**を確認する:

Run: `python3 -m pytest evals/ -x -q`
Expected: PASS（`hooks.json` を読む既存テストが再フォーマットで落ちないこと。落ちたら
`json.dumps(..., indent=2)` の出力が元のフォーマットと一致するかを `git diff` で見る —— 
差分が `record-coverage` の 6 行だけであるべき）

- [ ] **Step 5: Commit**

```bash
git add plugin/hooks/record-coverage plugin/hooks/hooks.json evals/test_record_coverage.py
git commit -m "$(cat <<'EOF'
feat: wire the coverage recorder into PostToolUse/Read

It writes nothing without TOKEN_SHUNT_HOOK_LOG, creates no state file, and
has no code path that can refuse a call -- the test asserts the absence of
hookSpecificOutput in the source, so a decision path fails the suite before
anyone tests its behaviour.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ea4ect8vUPUdiaXkjn2q8w
EOF
)"
```

---

### Task 4: `read_coverage.py` —— 行域の和集合

**Files:**
- Create: `evals/compare/read_coverage.py`
- Test: `evals/compare/test_read_coverage.py`

**Interfaces:**
- Consumes: Task 1–3 が書く JSONL 行（キーは Task 1 の Produces を参照）
- Produces:
  - `load(path) -> list[dict]` —— hooklog から `hook == "record-coverage"` の行だけ
  - `rows(records) -> list[dict]` —— キーは
    `session_id, agent_id, file_path, reads, covered, total, coverage,
    overlap, segments, bytes, total_changed`。
    `coverage` は `float | None`（`total_changed` または `total` が無い/0 のとき `None`）
  - `rollup(rows) -> dict` —— キーは `files, reads, covered, total, coverage`
  - `COLUMNS: tuple[str, ...]` —— CSV の列順
  - `main(argv=None) -> int`

- [ ] **Step 1: Write the failing test**

`evals/compare/test_read_coverage.py` を新規作成:

```python
"""Per-file coverage from the hook's own log, and nothing from transcripts.

Design: docs/superpowers/specs/2026-09-19-targeted-read-coverage-design.md

The denominator (totalLines) exists only in the PostToolUse event, so this
reads what `plugin/hooks/record-coverage` wrote and never parses a
transcript. It reports what the parent did; it does not score it.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
import read_coverage  # noqa: E402


def line(path='/c/a.py', start=1, lines=10, total=100, bytes=500,
         session='s1', agent=None, offset=1, limit=10, is_error=False):
    return {'hook': 'record-coverage', 'session_id': session, 'agent_id': agent,
            'file_path': path, 'start': start, 'lines': lines, 'total': total,
            'bytes': bytes, 'offset': offset, 'limit': limit,
            'is_error': is_error}


class CoverageTests(unittest.TestCase):
    def only(self, *records):
        got = read_coverage.rows(list(records))
        self.assertEqual(1, len(got), got)
        return got[0]

    def test_two_overlapping_reads_count_the_shared_lines_once(self):
        got = self.only(line(start=1, lines=10), line(start=6, lines=10))
        self.assertEqual(15, got['covered'])
        self.assertEqual(5, got['overlap'])
        self.assertEqual(1, got['segments'])
        self.assertEqual(2, got['reads'])

    def test_adjacent_reads_make_one_segment(self):
        got = self.only(line(start=1, lines=10), line(start=11, lines=10))
        self.assertEqual((20, 0, 1), (got['covered'], got['overlap'], got['segments']))

    def test_reads_with_a_gap_stay_two_segments(self):
        got = self.only(line(start=1, lines=10), line(start=50, lines=10))
        self.assertEqual((20, 0, 2), (got['covered'], got['overlap'], got['segments']))

    def test_one_full_read_is_complete_coverage(self):
        got = self.only(line(start=1, lines=100, total=100, offset=None, limit=None))
        self.assertEqual(1.0, got['coverage'])

    def test_a_failed_read_is_counted_but_covers_nothing(self):
        got = self.only(line(start=1, lines=10),
                        line(start=None, lines=None, total=None, bytes=0,
                             is_error=True))
        self.assertEqual((2, 10), (got['reads'], got['covered']))

    def test_a_file_that_changed_size_reports_no_rate(self):
        # An Edit between two reads moves the denominator. Averaging across
        # it would be a number nobody can defend.
        got = self.only(line(start=1, lines=10, total=100),
                        line(start=20, lines=10, total=140))
        self.assertIs(True, got['total_changed'])
        self.assertIsNone(got['coverage'])
        self.assertEqual(140, got['total'])

    def test_parent_and_worker_are_separate_rows(self):
        got = read_coverage.rows([line(agent=None), line(agent='a7')])
        self.assertEqual([None, 'a7'], sorted(
            (r['agent_id'] for r in got), key=lambda v: (v is not None, v)))
        self.assertEqual([10, 10], [r['covered'] for r in got])

    def test_the_rollup_leaves_out_the_rows_with_no_rate(self):
        got = read_coverage.rollup(read_coverage.rows([
            line(path='/c/a.py', start=1, lines=25, total=100),
            line(path='/c/b.py', start=1, lines=10, total=100),
            line(path='/c/b.py', start=20, lines=10, total=140)]))
        self.assertEqual(1, got['files'])
        self.assertEqual(25, got['covered'])
        self.assertEqual(100, got['total'])
        self.assertEqual(0.25, got['coverage'])


class LoadTests(unittest.TestCase):
    def test_other_hooks_lines_are_ignored(self):
        # The hook log is shared: check-file-size writes {hook,decision,...}
        # into the same file.
        with tempfile.NamedTemporaryFile('w', suffix='.hooklog',
                                         delete=False) as handle:
            handle.write(json.dumps({'hook': 'check-file-size',
                                     'decision': 'deny'}) + '\n')
            handle.write(json.dumps(line()) + '\n')
            handle.write('truncated{\n')
            name = handle.name
        self.addCleanup(lambda: Path(name).unlink())
        self.assertEqual(1, len(read_coverage.load(name)))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/dev/projects/skills/token-shunt && python3 -m pytest evals/compare/test_read_coverage.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'read_coverage'`

- [ ] **Step 3: Write minimal implementation**

`evals/compare/read_coverage.py` を新規作成:

```python
#!/usr/bin/env python3
"""What fraction of a file the parent recovered, read by read.

Design: docs/superpowers/specs/2026-09-19-targeted-read-coverage-design.md

Lock B never denies a targeted Read, and 18 of the 21 archived parent corpus
Reads were targeted. This says how much of each file those reads added up
to. It parses no transcript: the denominator (totalLines) is in the hook
event and nowhere else, so the input is the hook's own log.

It reports what the parent did. High coverage is not a verdict, and there
is no threshold here, because no measurement supports one yet.

Not part of the release gate. Bills nothing.
"""
import csv
import json
import sys

COLUMNS = ('session_id', 'agent_id', 'file_path', 'reads', 'covered', 'total',
           'coverage', 'overlap', 'segments', 'bytes', 'total_changed')


def load(path):
    """The coverage lines of one hook log, in order.

    The log is shared with every other hook, and a run killed mid-write
    leaves a partial last line; neither is a reason to produce no number.
    """
    found = []
    with open(path, encoding='utf-8', errors='replace') as source:
        for entry in source:
            try:
                row = json.loads(entry)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get('hook') == 'record-coverage':
                found.append(row)
    return found


def rows(records):
    """One row per (session, agent, file): the union of the lines taken."""
    groups = {}
    for row in records:
        key = (row.get('session_id'), row.get('agent_id'), row.get('file_path'))
        groups.setdefault(key, []).append(row)
    out = []
    for (session, agent, path), taken in groups.items():
        spans = [(r['start'], r['start'] + r['lines'] - 1) for r in taken
                 if type(r.get('start')) is int and type(r.get('lines')) is int
                 and r['lines'] > 0]
        totals = [r['total'] for r in taken if type(r.get('total')) is int]
        merged = _merge(spans)
        covered = sum(end - start + 1 for start, end in merged)
        changed = len(set(totals)) > 1
        total = totals[-1] if totals else None
        out.append({
            'session_id': session, 'agent_id': agent, 'file_path': path,
            'reads': len(taken), 'covered': covered, 'total': total,
            'coverage': None if changed or not total else covered / total,
            'overlap': sum(end - start + 1 for start, end in spans) - covered,
            'segments': len(merged),
            'bytes': sum(r.get('bytes') or 0 for r in taken),
            'total_changed': changed})
    return sorted(out, key=lambda r: (r['session_id'] or '',
                                      r['agent_id'] or '', r['file_path']))


def _merge(spans):
    """Disjoint closed intervals covering the same lines, low to high.

    Adjacent spans join: reading 1-10 then 11-20 is one recovery of 20
    lines, not two of ten.
    """
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [tuple(span) for span in merged]


def rollup(counted):
    """The rate across the files that have one.

    A file whose size changed mid-session has no defensible denominator, so
    it is left out here rather than averaged in silently.
    """
    usable = [r for r in counted if r['coverage'] is not None]
    covered = sum(r['covered'] for r in usable)
    total = sum(r['total'] for r in usable)
    return {'files': len(usable), 'reads': sum(r['reads'] for r in usable),
            'covered': covered, 'total': total,
            'coverage': (covered / total) if total else None}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print('usage: read_coverage.py <hooklog> [...]', file=sys.stderr)
        return 2
    records = []
    for path in argv:
        records.extend(load(path))
    counted = rows(records)
    writer = csv.DictWriter(sys.stdout, fieldnames=COLUMNS)
    writer.writeheader()
    for row in counted:
        writer.writerow(row)
    summary = rollup(counted)
    print('# files=%(files)d reads=%(reads)d covered=%(covered)d '
          'total=%(total)d' % summary, file=sys.stderr)
    print('# coverage=%s' % ('-' if summary['coverage'] is None
                             else '%.4f' % summary['coverage']), file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest evals/compare/test_read_coverage.py -v`
Expected: PASS（9 件）

- [ ] **Step 5: Commit**

```bash
git add evals/compare/read_coverage.py evals/compare/test_read_coverage.py
git commit -m "$(cat <<'EOF'
feat: aggregate per-file coverage from the hook log

Adjacent reads join into one segment, overlapping lines are counted once,
and a file whose totalLines moved mid-session reports no rate at all rather
than an average across two denominators.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ea4ect8vUPUdiaXkjn2q8w
EOF
)"
```

---

### Task 5: `run.sh` の pass-through

**Files:**
- Modify: `evals/compare/run.sh`（`_claude_call` 内、`TOKEN_SHUNT_SESSION_BUDGET_BYTES` の export の直後）
- Test: `evals/compare/test_runner.py`

**Interfaces:**
- Consumes: Task 3 の `TOKEN_SHUNT_HOOK_LOG` 依存
- Produces: run ごとに `<transcript>.hooklog` が生まれる（`cost_probe.py` と同じ命名）

- [ ] **Step 1: Write the failing test**

`evals/compare/test_runner.py` の `test_an_unusable_session_budget_stops_the_run` の直後に追加:

```python
    def test_the_hook_log_lands_beside_the_transcript(self):
        # _claude_call unsets every TOKEN_SHUNT_* name, so without this
        # pass-through the coverage instrument records nothing in a
        # measurement run -- the same hole the arm variable had.
        result = self.shell('''
ONLY=''; SUITE=''; setup_run || exit 1
mkdir -p "$TMP/bin"
cat > "$TMP/bin/claude" <<'CLI'
#!/bin/bash
printf '%s' "${TOKEN_SHUNT_HOOK_LOG-unset}"
CLI
chmod +x "$TMP/bin/claude"
export PATH="$TMP/bin:$PATH"
run_claude prompt "$TRD/base"
cat "$TRD/base"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.endswith('/base.hooklog'), result.stdout)

    def test_a_callers_hook_log_cannot_escape_the_run_directory(self):
        # A path exported by the caller would send one run's telemetry into
        # another run's file, or outside the measurement tree entirely.
        result = self.shell('''
ONLY=''; SUITE=''; setup_run || exit 1
mkdir -p "$TMP/bin"
cat > "$TMP/bin/claude" <<'CLI'
#!/bin/bash
printf '%s' "${TOKEN_SHUNT_HOOK_LOG-unset}"
CLI
chmod +x "$TMP/bin/claude"
export PATH="$TMP/bin:$PATH"
export TOKEN_SHUNT_HOOK_LOG=/tmp/somewhere-else
run_claude prompt "$TRD/base"
cat "$TRD/base"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.endswith('/base.hooklog'), result.stdout)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest evals/compare/test_runner.py -k hook_log -v`
Expected: FAIL —— 両方 `'unset'` が返る（`_claude_call` が剥がしたまま）。

- [ ] **Step 3: Write minimal implementation**

`evals/compare/run.sh` の `_claude_call` の中、
`export TOKEN_SHUNT_SESSION_BUDGET_BYTES=${SESSION_BUDGET_BYTES:-0}` の直後に:

```bash
    # The coverage instrument records only when this is set, and it is set
    # per run: a caller's exported path would mix two runs' telemetry into
    # one file. Costs nothing and rides along on whatever run happens next.
    export TOKEN_SHUNT_HOOK_LOG=$out.hooklog
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest evals/compare/test_runner.py -v`
Expected: PASS（既存を含め全件）

- [ ] **Step 5: Commit**

```bash
git add evals/compare/run.sh evals/compare/test_runner.py
git commit -m "$(cat <<'EOF'
feat: give every run its own hook log

_claude_call strips TOKEN_SHUNT_*, so without this the coverage instrument
would record nothing in a measurement run -- the same hole the Lock B arm
variable had. Pinned per run so a caller's export cannot mix two runs'
telemetry into one file.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ea4ect8vUPUdiaXkjn2q8w
EOF
)"
```

---

### Task 6: エンドツーエンド —— 計器の両端を 1 本のテストで結ぶ

**Files:**
- Test: `evals/compare/test_read_coverage.py`（`EndToEndTests` を追加）

**Interfaces:**
- Consumes: Task 3 の実行ファイル契約、Task 4 の `load`/`rows`
- Produces: なし（検証のみ）

- [ ] **Step 1: Write the failing test**

`evals/compare/test_read_coverage.py` の末尾に追加:

```python
import json as _json
import os
import subprocess

HOOK = Path(__file__).resolve().parents[2] / 'plugin' / 'hooks' / 'record-coverage'


class EndToEndTests(unittest.TestCase):
    """Three real Reads through the real hook, then the real aggregator."""

    def test_the_two_ends_of_the_instrument_agree(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        log = Path(temp.name) / 'hooklog'
        env = {k: v for k, v in os.environ.items()
               if not k.startswith('TOKEN_SHUNT_')}
        env['TOKEN_SHUNT_HOOK_LOG'] = str(log)
        # 1-40, 31-70, 120-139 of a 200-line file: one overlap of ten lines
        # and one gap, so every column has a value worth getting wrong.
        for start, count in ((1, 40), (31, 40), (120, 20)):
            body = {'hook_event_name': 'PostToolUse', 'tool_name': 'Read',
                    'session_id': 'e2e', 'agent_id': None,
                    'tool_input': {'file_path': '/c/big.py',
                                   'offset': start, 'limit': count},
                    'tool_response': {'type': 'text', 'file': {
                        'filePath': '/c/big.py', 'content': 'x' * (count * 30),
                        'startLine': start, 'numLines': count,
                        'totalLines': 200}}}
            result = subprocess.run([sys.executable, str(HOOK)],
                                    input=_json.dumps(body), text=True,
                                    timeout=10, capture_output=True, env=env)
            self.assertEqual((0, ''), (result.returncode, result.stdout))

        got = read_coverage.rows(read_coverage.load(str(log)))
        self.assertEqual(1, len(got))
        row = got[0]
        # 1-70 is 70 lines, 120-139 is 20: 90 of 200.
        self.assertEqual(3, row['reads'])
        self.assertEqual(90, row['covered'])
        self.assertEqual(200, row['total'])
        self.assertEqual(0.45, row['coverage'])
        self.assertEqual(10, row['overlap'])
        self.assertEqual(2, row['segments'])
        self.assertEqual(3000, row['bytes'])
        self.assertIs(False, row['total_changed'])
```

- [ ] **Step 2: Run test to verify it fails, then passes**

Run: `python3 -m pytest evals/compare/test_read_coverage.py::EndToEndTests -v`

Task 1–5 が済んでいれば PASS する。**PASS したら mutation で確かめる:**

```bash
# 隣接を結合しない実装にすると segments が 3 になる
sed -i 's/if merged and start <= merged\[-1\]\[1\] + 1:/if merged and start <= merged[-1][1]:/' evals/compare/read_coverage.py
python3 -m pytest evals/compare/test_read_coverage.py -v   # fail を確認
git checkout evals/compare/read_coverage.py
```

（この mutation は `test_adjacent_reads_make_one_segment` も落とす。**両方落ちるのが正しい** —— 
エンドツーエンドは単体テストの代わりではなく、配線が生きている証拠である。）

- [ ] **Step 3: Run the whole suite**

Run: `python3 -m pytest evals/ -q && python3 -m pytest evals/compare/ -q`
Expected: 全件 PASS。**新しい失敗が 1 件も無いこと。**

- [ ] **Step 4: Commit**

```bash
git add evals/compare/test_read_coverage.py
git commit -m "$(cat <<'EOF'
test: drive three real reads through the hook into the aggregator

Overlapping and gapped spans of one 200-line file: 90 lines covered, 10
overlapped, 2 segments. The wiring is the thing under test -- the union
arithmetic already has its own cases.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ea4ect8vUPUdiaXkjn2q8w
EOF
)"
```

---

### Task 7: ドキュメント —— 何が計られ、何が計られないか

**Files:**
- Modify: `README.md`（環境変数の表）
- Modify: `docs/2026-09-12-token-shunt-design.md`（§15 の既知の限界）
- Modify: `docs/superpowers/specs/2026-09-19-targeted-read-coverage-design.md`（実装記録の節）

**Interfaces:**
- Consumes: Task 1–6 の全部
- Produces: なし

- [ ] **Step 1: README の環境変数表に 1 行足す**

`README.md` の `TOKEN_SHUNT_SESSION_BUDGET_BYTES` の行の下に、同じ書式で:

| 変数 | 既定 | 効果 |
|---|---|---|
| `TOKEN_SHUNT_HOOK_LOG` | 未設定（無効） | フックの判定と、Read 1 回ごとの被覆行を JSONL で追記する。**判定には一切影響しない。** |

（既存の表の列名・書式に合わせること。`TOKEN_SHUNT_HOOK_LOG` の行が**既にある**なら、
被覆行が加わったことを効果欄に追記するだけにする。**行を二重に作らない。**）

- [ ] **Step 2: §15 の既知の限界を更新する**

`docs/2026-09-12-token-shunt-design.md` の §15 に:

```
- **targeted Read の逐次回収は今も拒まれない**（cumulative-intake spec §3.3）。
  アーカイブでは親の corpus Read 21 回中 18 回がこの形だった。
  2026-09-19 以降、`record-coverage` がファイル単位の被覆率を**観測する**
  （`docs/superpowers/specs/2026-09-19-targeted-read-coverage-design.md`）。
  **観測するだけで、封鎖範囲は広げていない。** Bash 経由の刻み読みは
  分母が取れないため、依然として観測対象外である。
```

- [ ] **Step 3: spec に実装記録の節を足す**

`docs/superpowers/specs/2026-09-19-targeted-read-coverage-design.md` の末尾に `## 9. 実装記録` を作り、
実際に書いたファイル・テスト件数・mutation で確認した項目・**まだ 1 行もデータが無いこと**を書く。
**設計と実装が食い違っていたら、spec 側を直して両方を commit する**（片方だけ直さない）。

- [ ] **Step 4: 退避の手順を run sheet の書式で書く**

`reviews/cumulative-intake-run-sheet-2026-09-19.md` §5 と同じ扱いで、
run ディレクトリが消える前に行を出す手順を spec §9 に 1 ブロックで残す:

```bash
# run ディレクトリを消す前に。腕ごとに 1 ファイル。
python3 evals/compare/read_coverage.py \
    evals/compare/tmp/runs/run.*/transcripts/*.hooklog \
    > reviews/data/read-coverage-$(date +%Y-%m-%d).csv
sha256sum reviews/data/read-coverage-*.csv
```

**CSV を commit する。hooklog 本体はリポジトリに入れない**（transcript と同じ扱いで
`~/measurements/` へ）。

- [ ] **Step 5: Commit**

```bash
git add README.md docs/2026-09-12-token-shunt-design.md \
        docs/superpowers/specs/2026-09-19-targeted-read-coverage-design.md
git commit -m "$(cat <<'EOF'
docs: say what the coverage instrument measures and what it does not

It observes the route Lock B never denies; it does not narrow it. Bash
sequential reads stay unobserved because their denominator does not exist,
and the instrument holds no data at all until a run happens.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ea4ect8vUPUdiaXkjn2q8w
EOF
)"
```
