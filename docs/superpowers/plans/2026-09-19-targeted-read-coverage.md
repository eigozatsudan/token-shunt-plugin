# targeted Read 被覆率計器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 親が `offset`+`limit` の刻み読みで原本の何割を回収したかを、実機の PostToolUse で記録し、ファイル単位の被覆率として集計する。

**Architecture:** 判定を出せないフック 1 本（`record-coverage`）が Read 1 回につき JSONL 1 行を既存の `write-hook-log` に流し、事後の集計器（`read_coverage.py`）が `(session, agent, path)` ごとに行域の和集合を取る。状態ファイルなし、閾値なし、deny 経路なし。

**Tech Stack:** Python 3（標準ライブラリのみ）、bash、`unittest`。既存の `write-hook-log` / `hooks.json` / `evals/compare/run.sh`。

**Spec:** `docs/superpowers/specs/2026-09-19-targeted-read-coverage-design.md`

## 状態: 実行済み・マージ済み（2026-09-19〜20）。追加作業なし（2026-09-20 確認）

**下の 30 個のチェックボックスは 1 つも付いていないが、未着手という意味ではない。**
実行中に更新されなかっただけで、計器は実装・レビュー・マージ済みで、実機 3 本と
アーカイブ 239 会話の再生を通っている。**チェックボックスは記録ではない。**
30 個を一括で ✓ にはしない —— 手順ごとの検証をしていないものを、したことにしない。

現物で確認したもの（2026-09-20）:

| 確認 | 証拠 |
|---|---|
| フックが出荷されている | `plugin/hooks/record-coverage`（4,850 B） |
| 登録されている | `plugin/hooks/hooks.json:125`、**PostToolUse / matcher `Read`** |
| 集計器 | `evals/compare/read_coverage.py`（312 行）、`test_read_coverage.py` 30 tests OK |
| **deny しない** | ソースに `hookSpecificOutput` が 0 箇所 |
| **`intake_ledger` を import しない** | 出現 2 箇所はいずれもコメント（`:49`、`:77`） |
| 実機 3 本 | `reviews/read-coverage-2026-09-20.md`（$1.7261） |
| アーカイブ 239 会話 | `reviews/read-coverage-archive-2026-09-20.md`（$0） |

マージ後に入った修正: `99babe4`（親と worker の率を分ける）、`e768ac2`（stdin を
読み切る・子を黙らせる）、`ac8c1b3`（hooklog 名ではなく会話でグループ化）、
`6a50383`（`bytes` 列を `parent_bytes.py` と突き合わせる）、`b794b1f`。

**spec §9 が未検証と書いた 2 点には答えが出た**（実機 3 本、live note §2）:
worker は `agent_id` と `agent_type` の両方を運ぶ。`--resume` は `session_id` を変えない（n=1）。

**まだ閉じていないもの:**

1. **閾値は無いままである。** spec は「線を引く根拠になる実測は 1 本も無い」と書いた。
   アーカイブ再生が分布を 1 つ与えた（targeted のみで 0.1398、最大 0.519）が、
   **24 行・6 ケースである。まだ線を引かない。**
2. **direct 腕は観測できない**（spec §8.8）。`run.sh` は direct に `--plugin-dir` を
   渡さないのでフックが走らない。**「direct の被覆率が 0」は成果ではなく計器の不在である。**
   代わりに direct 腕の読み取りの形は transcript から測った
   （`reviews/direct-arm-read-shape-2026-09-20.md`、199 Read 中 195 が全文）。
3. **逐次回収の基底率は低い** —— 親の 24 行中 2 行、うち 1 行はターンをまたいだ。
   この 1 行が、会話でグループ化するという設計判断（`ac8c1b3`）を実データで支えている。

---

## Global Constraints

- **このフックは deny してはならない。** stdout に何も書かない。`hookSpecificOutput` という文字列がソースに出現してはならない（spec §4）。
- **状態ファイルを作らない。** `token-shunt-intake-*` / `token-shunt-reader-*` / 新規の状態ディレクトリ、いずれも作らない（spec §4）。
- **`intake_ledger` を import しない。** Lock B の budget=0 不活性と生死を共有しない（spec §4）。
- **`TOKEN_SHUNT_HOOK_LOG` が未設定なら 1 バイトも書かない。新しい環境変数を増やさない**（spec §5）。
- **失敗しても exit 0。** `main()` 全体を try/except で包む（spec §4）。
- **`start`/`lines`/`total` は `tool_response.file` の `startLine`/`numLines`/`totalLines` をそのまま使う。フックが数え直さない**（spec §3）。
- **Read のみ。Bash は対象外**（spec §3、§8.3）。
- **閾値を持たない。判定列を作らない**（spec §8.4）。
- **親判定は `agent_id` と `agent_type` の両方から取る。** `intake_ledger.py:134`
  が `not (agent_id or agent_type)` を使っている。**片方だけ見ると worker の Read が
  親に混ざる**（spec §3、§6）。
- **`rollup` の出力に「これは順位ではない」と刻む。** 低い被覆率は健全さの証拠でも
  汚染の証拠でもない（spec §6）。
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
  `agent_type`(str|None), `file_path`(str), `start`(int|None), `lines`(int|None), `total`(int|None),
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
import re
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
          agent_type=None, is_error=False, **extra):
    response = {'type': 'text', 'file': {
        'filePath': path, 'content': content,
        'startLine': start, 'numLines': lines, 'totalLines': total}}
    if is_error:
        response['is_error'] = True
    body = {'hook_event_name': 'PostToolUse', 'tool_name': 'Read',
            'session_id': 's1', 'agent_id': agent_id, 'agent_type': agent_type,
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
        self.assertEqual(('record-coverage', 's1', None, None,
                          '/corpus/migration.py'),
                         (got['hook'], got['session_id'], got['agent_id'],
                          got['agent_type'], got['file_path']))
        self.assertEqual((139, 50, 316), (got['start'], got['lines'], got['total']))
        self.assertEqual((139, 50), (got['offset'], got['limit']))
        self.assertEqual(2814, got['bytes'])
        self.assertIs(False, got['is_error'])

    def test_a_worker_read_carries_both_of_the_fields_that_identify_it(self):
        # intake_ledger.py:134 judges a parent by `not (agent_id or
        # agent_type)`. Recording only agent_id files a worker Read whose
        # event carries agent_type alone as if the parent had made it, and
        # worker reads are full-file by design -- they would drag every
        # rate up.
        self.assertEqual(('a7', None),
                         (hook.record(event(agent_id='a7'))['agent_id'],
                          hook.record(event(agent_id='a7'))['agent_type']))
        typed = hook.record(event(agent_type='token-shunt:bulk-reader'))
        self.assertEqual('token-shunt:bulk-reader', typed['agent_type'])

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
        # Both fields, because intake_ledger.py:134 needs both to tell a
        # parent from a worker sharing the session.
        'agent_type': _str(event.get('agent_type')),
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest evals/test_record_coverage.py -v`
Expected: PASS（7 件）

- [ ] **Step 5: Mutation-check the three tests that guard a specific line**

通ったテストをそのまま信用しない。1 つずつ本番を壊し、**対応するテストだけが
落ちる**ことを見る。壊したら必ず戻す。

```bash
# 1) agent_type を落とす -> test_a_worker_read_carries_both_of_the_fields...
sed -i "s/'agent_type': _str(event.get('agent_type')),/'agent_type': None,/" plugin/hooks/record-coverage
python3 -m pytest evals/test_record_coverage.py -v   # 1 fail を確認
git checkout plugin/hooks/record-coverage 2>/dev/null || true

# 2) error 行を捨てる -> test_a_failed_read_keeps_the_row_but_claims_no_lines
sed -i "s/    if not isinstance(path, str) or not path:/    if not isinstance(path, str) or not path or response.get('is_error'):/" plugin/hooks/record-coverage
python3 -m pytest evals/test_record_coverage.py -v   # 1 fail を確認
git checkout plugin/hooks/record-coverage 2>/dev/null || true

# 3) 型を信じる -> test_a_malformed_response_records_a_row_without_line_numbers
sed -i 's/    return value if type(value) is int else None/    return int(value) if value is not None else None/' plugin/hooks/record-coverage
python3 -m pytest evals/test_record_coverage.py -v   # 1 fail を確認
git checkout plugin/hooks/record-coverage 2>/dev/null || true
```

**落ちなかったテストは、書き直すか捨てる。**
（まだ commit 前なので `git checkout` が効かない。その場合は編集を手で戻すか、
先に Step 6 で commit してから mutation を回す。**どちらでもよいが、mutation を
飛ばしてはいけない。**）

- [ ] **Step 6: Commit**

```bash
git add plugin/hooks/record-coverage evals/test_record_coverage.py
git commit -m "$(cat <<'EOF'
feat: turn one Read into one coverage line

totalLines is why this lives in the hook: a transcript carries only cat -n
text, so the denominator exists here and nowhere else. The row carries both
agent_id and agent_type, because a parent is `not (agent_id or agent_type)`
and a worker read filed as the parent's would drag every rate up.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ea4ect8vUPUdiaXkjn2q8w
EOF
)"
```

---

### Task 2: `main()` —— 書き出し、既定 OFF、deny 経路なし

**Files:**
- Modify: `plugin/hooks/record-coverage`
- Modify: `plugin/hooks/hooks.json`（PostToolUse/Read の `record-intake` の後ろ）
- Test: `evals/test_record_coverage.py`

**Interfaces:**
- Consumes: Task 1 の `record(event) -> dict | None`
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
        for forbidden in ('hookSpecificOutput', 'permissionDecision'):
            self.assertNotIn(forbidden, source)

    def test_the_hook_does_not_import_lock_b(self):
        # Lock B is inert at budget 0, which is the shipped default. Sharing
        # a module with it would make this instrument inert too. A comment
        # may cite intake_ledger.py:134 -- only an import is forbidden.
        self.assertIsNone(re.search(r'(?m)^\s*(import|from)\s+intake_ledger',
                                    SOURCE.read_text()))

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
Expected: PASS（16 件。**最終レビュー修正後は 23 件** —— 本行は当時の期待値であり、現在の本数は spec §9 を見ること）

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

### Task 3: `read_coverage.py` —— 行域の和集合

**Files:**
- Create: `evals/compare/read_coverage.py`
- Test: `evals/compare/test_read_coverage.py`

**Interfaces:**
- Consumes: Task 1–2 が書く JSONL 行（キーは Task 1 の Produces を参照）
- Produces:
  - `load(path) -> list[dict]` —— hooklog から `hook == "record-coverage"` の行だけ
  - `rows(records) -> list[dict]` —— キーは
    `session_id, parent, agent_id, agent_type, file_path, reads, covered,
    total, coverage, overlap, segments, bytes, total_changed, impossible`。
    **本行は計画当時の列であり、現在の列とグループ化キーは spec §6 を見ること**
    （最終レビューで `source` / `full_file_reads` が、2026-09-20 の訂正で
    `run` / `conversation` / `sources` が加わっている）。
    `parent` は `bool`（`not (agent_id or agent_type)`）。
    `coverage` は `float | None`（`total_changed` / `impossible` / `total` が
    無い・0 のとき `None`）
  - `rollup(rows) -> dict` —— キーは `files, reads, covered, total, coverage, excluded`
  - `sessions(records) -> list[str]` —— 現れた `session_id`。1 会話で 2 つ以上なら
    `--resume` が別セッションになっている合図（spec §8.7）
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
         session='s1', agent=None, agent_type=None, offset=1, limit=10,
         is_error=False):
    return {'hook': 'record-coverage', 'session_id': session, 'agent_id': agent,
            'agent_type': agent_type, 'file_path': path, 'start': start,
            'lines': lines, 'total': total, 'bytes': bytes, 'offset': offset,
            'limit': limit, 'is_error': is_error}


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
        self.assertEqual([True, False], [r['parent'] for r in got])
        self.assertEqual([10, 10], [r['covered'] for r in got])

    def test_a_worker_known_only_by_its_type_is_not_filed_as_the_parent(self):
        # intake_ledger.py:134 judges a parent by `not (agent_id or
        # agent_type)`. Grouping on agent_id alone merges this worker's
        # full-file reads into the parent's row.
        got = read_coverage.rows([
            line(agent=None, start=1, lines=10),
            line(agent=None, agent_type='token-shunt:bulk-reader',
                 start=1, lines=100)])
        self.assertEqual(2, len(got))
        self.assertEqual([True, False], [r['parent'] for r in got])
        self.assertEqual([10, 100], [r['covered'] for r in got])

    def test_a_read_past_the_end_of_the_file_reports_no_rate(self):
        # check-reader-contract:143 treats start+count-1 <= total as a
        # validity condition. Broken data is not a coverage of 1.4.
        got = self.only(line(start=1, lines=140, total=100))
        self.assertIs(True, got['impossible'])
        self.assertIsNone(got['coverage'])

    def test_the_rollup_leaves_out_the_rows_with_no_rate(self):
        got = read_coverage.rollup(read_coverage.rows([
            line(path='/c/a.py', start=1, lines=25, total=100),
            line(path='/c/b.py', start=1, lines=10, total=100),
            line(path='/c/b.py', start=20, lines=10, total=140)]))
        self.assertEqual(1, got['files'])
        self.assertEqual(25, got['covered'])
        self.assertEqual(100, got['total'])
        self.assertEqual(0.25, got['coverage'])
        self.assertEqual(1, got['excluded'])

    def test_two_sessions_in_one_log_are_reported(self):
        # A follow-up turn that starts a new session would split one
        # conversation's coverage in two and read as a lower rate.
        self.assertEqual(['s1', 's2'], read_coverage.sessions(
            [line(session='s1'), line(session='s2'), line(session='s1')]))


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

COLUMNS = ('session_id', 'parent', 'agent_id', 'agent_type', 'file_path',
           'reads', 'covered', 'total', 'coverage', 'overlap', 'segments',
           'bytes', 'total_changed', 'impossible')


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


def _parent(row):
    """Whether the parent issued this read, not a worker sharing the session.

    Both fields, because `intake_ledger.py:134` uses both: a worker whose
    event carries only `agent_type` would otherwise be filed as the parent,
    and a worker reads whole files by design.
    """
    return not (row.get('agent_id') or row.get('agent_type'))


def sessions(records):
    """Every session id in the log, sorted.

    One conversation should be one id across its follow-up turns. Two means
    `--resume` started a new session, and the coverage of one conversation
    has been split in two.
    """
    return sorted({r.get('session_id') for r in records if r.get('session_id')})


def rows(records):
    """One row per (session, reader, file): the union of the lines taken."""
    groups = {}
    for row in records:
        key = (row.get('session_id'), _parent(row), row.get('agent_id'),
               row.get('agent_type'), row.get('file_path'))
        groups.setdefault(key, []).append(row)
    out = []
    for (session, parent, agent, agent_type, path), taken in groups.items():
        spans = [(r['start'], r['start'] + r['lines'] - 1) for r in taken
                 if type(r.get('start')) is int and type(r.get('lines')) is int
                 and r['lines'] > 0]
        totals = [r['total'] for r in taken if type(r.get('total')) is int]
        merged = _merge(spans)
        covered = sum(end - start + 1 for start, end in merged)
        changed = len(set(totals)) > 1
        total = totals[-1] if totals else None
        # A read past the end of the file means the event was wrong, not
        # that the parent recovered 140% of it.
        impossible = bool(total) and covered > total
        out.append({
            'session_id': session, 'parent': parent, 'agent_id': agent,
            'agent_type': agent_type, 'file_path': path,
            'reads': len(taken), 'covered': covered, 'total': total,
            'coverage': None if changed or impossible or not total
                        else covered / total,
            'overlap': sum(end - start + 1 for start, end in spans) - covered,
            'segments': len(merged),
            'bytes': sum(r.get('bytes') or 0 for r in taken),
            'total_changed': changed, 'impossible': impossible})
    return sorted(out, key=lambda r: (r['session_id'] or '', not r['parent'],
                                      r['agent_id'] or '',
                                      r['agent_type'] or '', r['file_path']))


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
    it is left out here rather than averaged in silently. `excluded` is
    reported because that exclusion is not random: it drops the files an
    edit touched, which leaves a population of files that were only read.
    """
    usable = [r for r in counted if r['coverage'] is not None]
    covered = sum(r['covered'] for r in usable)
    total = sum(r['total'] for r in usable)
    return {'files': len(usable), 'reads': sum(r['reads'] for r in usable),
            'covered': covered, 'total': total,
            'coverage': (covered / total) if total else None,
            'excluded': len(counted) - len(usable)}


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
          'total=%(total)d excluded=%(excluded)d' % summary, file=sys.stderr)
    print('# coverage=%s' % ('-' if summary['coverage'] is None
                             else '%.4f' % summary['coverage']), file=sys.stderr)
    # This number is not a ranking. A parent that took 30% in slices
    # polluted itself; a parent that took 30% because Grep answered the
    # question did not. They print the same.
    print('# coverage is what the parent did, not how well it did it:'
          ' a low rate is neither good nor bad', file=sys.stderr)
    found = sessions(records)
    if len(found) > 1:
        print('# WARNING: %d session ids in this log (%s): one conversation'
              ' split across sessions reads as a lower rate'
              % (len(found), ','.join(found)), file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest evals/compare/test_read_coverage.py -v`
Expected: PASS（12 件。エンドツーエンド追加で 13 件、**最終レビュー修正後は 24 件** —— 本行は当時の期待値であり、現在の本数は spec §9 を見ること）

- [ ] **Step 5: Commit**

```bash
git add evals/compare/read_coverage.py evals/compare/test_read_coverage.py
git commit -m "$(cat <<'EOF'
feat: aggregate per-file coverage from the hook log

Adjacent reads join into one segment, overlapping lines are counted once,
and a file whose totalLines moved mid-session reports no rate at all rather
than an average across two denominators. Parent and worker are told apart
by both agent fields, since a worker reads whole files by design, and the
rollup says in its own output that the rate is not a ranking.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Ea4ect8vUPUdiaXkjn2q8w
EOF
)"
```

---

### Task 4: `run.sh` の pass-through

**Files:**
- Modify: `evals/compare/run.sh`（`_claude_call` 内、`TOKEN_SHUNT_SESSION_BUDGET_BYTES` の export の直後）
- Test: `evals/compare/test_runner.py`

**Interfaces:**
- Consumes: Task 2 の `TOKEN_SHUNT_HOOK_LOG` 依存
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

    def test_each_call_gets_its_own_hook_log(self):
        # Not "a caller's export cannot escape": _claude_call unsets every
        # TOKEN_SHUNT_* name before this line runs, so a buggy
        # ${TOKEN_SHUNT_HOOK_LOG:-$out.hooklog} would pass that test too. What
        # can actually break is pinning one path for the whole run, which
        # would pour five follow-up turns into one file and make a turn
        # impossible to tell from its successor.
        result = self.shell('''
ONLY=''; SUITE=''; setup_run || exit 1
mkdir -p "$TMP/bin"
cat > "$TMP/bin/claude" <<'CLI'
#!/bin/bash
printf '%s\n' "${TOKEN_SHUNT_HOOK_LOG-unset}"
CLI
chmod +x "$TMP/bin/claude"
export PATH="$TMP/bin:$PATH"
run_claude prompt "$TRD/one"
run_claude prompt "$TRD/two"
cat "$TRD/one" "$TRD/two"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        got = result.stdout.split()
        self.assertEqual(2, len(got), result.stdout)
        self.assertTrue(got[0].endswith('/one.hooklog'), got)
        self.assertTrue(got[1].endswith('/two.hooklog'), got)
        self.assertNotEqual(got[0], got[1])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest evals/compare/test_runner.py -k hook_log -v`
Expected: FAIL —— 両方 `'unset'` が返る（`_claude_call` が剥がしたまま）。

**そして、通した後に mutation で確かめる:**

```bash
# run 全体で 1 本に固定する実装にすると、2 本目のテストだけが落ちる
sed -i 's|export TOKEN_SHUNT_HOOK_LOG=$out.hooklog|export TOKEN_SHUNT_HOOK_LOG=$TRD/run.hooklog|' evals/compare/run.sh
python3 -m pytest evals/compare/test_runner.py -k hook_log -v   # 1 fail を確認
git checkout evals/compare/run.sh
```

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

### Task 5: エンドツーエンド —— 計器の両端を 1 本のテストで結ぶ

**Files:**
- Test: `evals/compare/test_read_coverage.py`（`EndToEndTests` を追加）

**Interfaces:**
- Consumes: Task 2 の実行ファイル契約、Task 3 の `load`/`rows`
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
                    'session_id': 'e2e', 'agent_id': None, 'agent_type': None,
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
        self.assertIs(True, row['parent'])
        self.assertEqual(3, row['reads'])
        self.assertEqual(90, row['covered'])
        self.assertEqual(200, row['total'])
        self.assertEqual(0.45, row['coverage'])
        self.assertEqual(10, row['overlap'])
        self.assertEqual(2, row['segments'])
        self.assertEqual(3000, row['bytes'])
        self.assertIs(False, row['total_changed'])
        self.assertIs(False, row['impossible'])
```

- [ ] **Step 2: Run test to verify it fails, then passes**

Run: `python3 -m pytest evals/compare/test_read_coverage.py::EndToEndTests -v`

Task 1–4 が済んでいれば PASS する。**PASS したら mutation で確かめる:**

```bash
# 隣接を結合しない実装にすると segments が 3 になる
sed -i 's/if merged and start <= merged\[-1\]\[1\] + 1:/if merged and start <= merged[-1][1]:/' evals/compare/read_coverage.py
python3 -m pytest evals/compare/test_read_coverage.py -v   # fail を確認
git checkout evals/compare/read_coverage.py
```

（**訂正（Task 6 実装時）：この予測「両方落ちるのが正しい」は誤りだった。**
実際に mutation を当てて確かめると、落ちるのは `test_adjacent_reads_make_one_segment`
だけで、エンドツーエンドは PASS したままである。理由はエンドツーエンドのフィクスチャの
区間が 1-40、31-70、120-139 で、31 <= 40 は重なり、120 > 70+1 は空隙であり、
隣接（`start == 前区間の終端 + 1`）を一度も踏まないからである。エンドツーエンドは
単体テストの代わりにはならない —— 隣接結合則はこの単体テストしか検査していない。）

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

### Task 6: ドキュメント —— 何が計られ、何が計られないか

**Files:**
- Modify: `README.md`（環境変数の表）
- Modify: `docs/2026-09-12-token-shunt-design.md`（§15 の既知の限界）
- Modify: `docs/superpowers/specs/2026-09-19-targeted-read-coverage-design.md`（実装記録の節）

**Interfaces:**
- Consumes: Task 1–5 の全部
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
併せて、**最初の 1 run で確かめる 2 点**を書き残す:
(a) `--resume` をまたいで `session_id` が同じか（spec §8.7、集計器の警告で分かる）、
(b) worker の Read が `agent_id`／`agent_type` のどちらを載せて来るか
（両方記録しているので、**最初の CSV の `parent` 列を見れば分かる**）。
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
