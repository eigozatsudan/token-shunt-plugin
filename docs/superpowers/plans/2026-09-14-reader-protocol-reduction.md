# reader 委譲プロトコル往復削減 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** reader 経路の deny そのものに呼び出し仕様を載せ、親がスキルを読み込まずに1回で委譲できるようにして、direct 比の料金を下げる。

**Architecture:** 共通契約の正本をプレーンテキスト `plugin/hooks/reader-call-contract` に置く。`check-file-size` と `check-bash-read` は、委譲で解決できる deny に限りこの正本を読み、`{REASON}` と `{PATHS}` を埋めて `permissionDecisionReason` として返す。それ以外の deny と、正本が読めない場合は現行文言を維持する。SKILL.md は定型ケースの呼び出し仕様を持たず、明示委譲・バッチ・曖昧性・再試行のみを扱う。

**Tech Stack:** Bash 4+ フック（jq 依存）、Python 3 の unittest、`evals/run.sh` の記録型ハーネス、`evals/compare/cost_probe.py`（実機3条件プローブ）

**Spec:** `docs/superpowers/specs/2026-09-14-reader-protocol-reduction-design.md`

## Global Constraints

- 固定本文（`{REASON}` / `{PATHS}` を除く）は **900 バイト以下**。§4.1 の実測は 860 バイト。
- 正本が欠落・読み込み不能・プレースホルダ欠損なら、**現行の deny 文言をそのまま返す**（フェイルセーフ）。テンプレート用の短縮理由とフォールバック理由は**別の引数**で渡し、テストで**全文一致**を確認する。
- テンプレートに載せるパスは **1〜3件**。子の実行契約が1回あたり最大3パスなので、4件以上はバッチ判断としてスキル経路（現行文言）に残す。載せる場合は、超過した1件だけでなく**解決済みの対象全件**を列挙する。
- **走査予算超過のうち、時間予算（`SCAN_BUDGET_MS`）側の超過はテンプレート対象外**（設計 §5）。バイト予算超過と走査失敗だけを対象にする。
- 走査予算は `MIN_LINES` と `MIN_BYTES` の**両方を下回るファイル**でしか発火しない。サイズ超過ファイルでは `stat` の時点で `EXCEEDED` が確定し、走査に入らない。テストの fixture はこれを踏まえて分ける。
- テンプレートを返す deny は §5 の表に載っているものだけ。heredoc・解析安全性・cwd 不正・時間予算超過・シェル展開でパス未解決・バイト境界なしパイプは**現行文言のまま**。
- `agent_type=token-shunt:bulk-reader` / `token-shunt:code-writer` の呼び出しは従来どおり pass（`check-file-size:153-165`、`check-bash-read:173`）。この allowlist を動かさない。
- deny の JSON 形状（`hookSpecificOutput.permissionDecision="deny"` + `permissionDecisionReason`、exit 0）を変えない。`evals/run.sh` の `check_expect` は deny 理由が `bulk-reader` を含むことを要求する。テンプレート本文は `token-shunt:bulk-reader` を含むためこの条件を満たす。
- writer 経路（code-writer）と、複数小ファイルの総I/O超過による自動発火は**本計画の範囲外**。
- モデル解決規則: 呼び出し側の明示指定を優先、未指定または `auto` は **haiku**。`auto` の文字列を Agent に渡さない。
- 既存の未コミット変更が作業ツリーに多数ある。`git add` は各タスクで触れたパスのみを明示指定し、`git add -A` を使わない。

---

### Task 1: worker 側の制限適用の確認と判定表の確定

テンプレート適用の前提条件。**このタスクが終わるまで、走査予算超過には現行 deny を維持する**（Task 5 がこの結果に依存する）。コード変更はなく、成果物は記録ファイル。

**Files:**
- Create: `reviews/worker-limit-applicability-2026-09-14.md`
- Modify: `docs/superpowers/specs/2026-09-14-reader-protocol-reduction-design.md`（§5 の判定表を確認結果で確定させる場合のみ）

**Interfaces:**
- Produces: 「走査予算超過にテンプレートを適用してよいか」の真偽と根拠。Task 5 の実施可否をこれで決める。

- [ ] **Step 1: 4つの制限それぞれについて、worker に適用されるかをフック実行で確認する**

確認対象は次の4つ。1〜3はフック側の制限、4はハーネス側の制限。

| 制限 | 定義箇所 | 確認方法 |
|---|---|---|
| サイズ閾値（`MIN_LINES` / `MIN_BYTES`） | `check-file-size` / `check-bash-read` の `int_env` | `agent_type` 付き入力で pass するか |
| 走査予算バイト数（`SCAN_BUDGET_BYTES`） | 同上 | 同上 |
| 走査予算時間（`SCAN_BUDGET_MS`） | 同上 | 同上 |
| ネイティブ Read のトークン上限（`CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS`） | ハーネス（フック外） | フックでは検証不能。既存実機記録から判断する |

次のスクリプトを実行する（スクラッチに置いてよい。リポジトリには残さない）:

**走査予算は大きいファイルでは検証できない。** `full_file_verdict`
（`check-file-size:105-138`）は `stat` の結果が `MIN_BYTES` を超えた時点で
`EXCEEDED` を返し、走査に入らない。400KB の `big.txt` では
`TOKEN_SHUNT_SCAN_BUDGET_MS` も `TOKEN_SHUNT_SCAN_BUDGET_BYTES` も走査予算経路に
届かない。走査予算は **`MIN_LINES`（350行）と `MIN_BYTES`（65536バイト）の両方を
下回る fixture** に対して個別に発火させ、**拒否理由の文言まで**確認する。

スクリプトは `/home/dev/projects/skills/token-shunt` 直下で実行する。ネストした
heredoc を避けるため、fixture 作成は別ファイルに書いてから呼ぶ。

```bash
cd /home/dev/projects/skills/token-shunt
T=$(mktemp -d)
cat > "$T/mkfix.py" <<'FIXEOF'
import sys, pathlib
d = pathlib.Path(sys.argv[1])
(d / 'big.txt').write_bytes(b'x\n' * 200000)           # サイズ超過（stat だけで確定）
(d / 'oneline.txt').write_bytes(b'y' * 200000 + b'\n')  # 単一巨大行
(d / 'tiny.txt').write_bytes(b'abc\n')                 # 両閾値を下回る → 走査予算検証用
FIXEOF
python3 "$T/mkfix.py" "$T"

probe() { # label env... hook   (payload は stdin)
  local label=$1; shift
  printf '%-44s -> ' "$label"
  env -u CDPATH "$@" | jq -r '.hookSpecificOutput.permissionDecision // "pass"'
}

# (1) サイズ閾値
for agent in '' 'token-shunt:bulk-reader'; do
  for f in big.txt oneline.txt; do
    probe "size ${agent:-parent} read $f" plugin/hooks/check-file-size \
      <<<"$(jq -nc --arg a "$agent" --arg c "$T" --arg p "$f" \
        '{cwd:$c, tool_input:{file_path:$p}} + (if $a == "" then {} else {agent_type:$a} end)')"
    probe "size ${agent:-parent} bash $f" plugin/hooks/check-bash-read \
      <<<"$(jq -nc --arg a "$agent" --arg c "$T" --arg p "$f" \
        '{cwd:$c, tool_input:{command:("cat " + $p)}} + (if $a == "" then {} else {agent_type:$a} end)')"
  done
done

# (2) 走査予算バイト数: tiny.txt は両閾値を下回るので、ここだけが予算超過で deny になる
for agent in '' 'token-shunt:bulk-reader'; do
  probe "scan-bytes ${agent:-parent} read" TOKEN_SHUNT_SCAN_BUDGET_BYTES=1 \
    plugin/hooks/check-file-size \
    <<<"$(jq -nc --arg a "$agent" --arg c "$T" \
      '{cwd:$c, tool_input:{file_path:"tiny.txt"}} + (if $a == "" then {} else {agent_type:$a} end)')"
  probe "scan-bytes ${agent:-parent} bash" TOKEN_SHUNT_SCAN_BUDGET_BYTES=1 \
    plugin/hooks/check-bash-read \
    <<<"$(jq -nc --arg a "$agent" --arg c "$T" \
      '{cwd:$c, tool_input:{command:"cat tiny.txt"}} + (if $a == "" then {} else {agent_type:$a} end)')"
  # (3) 走査予算時間: 設計 §5 でテンプレート対象外。worker への適用有無だけ記録する
  probe "scan-ms ${agent:-parent} read" TOKEN_SHUNT_SCAN_BUDGET_MS=0 \
    plugin/hooks/check-file-size \
    <<<"$(jq -nc --arg a "$agent" --arg c "$T" \
      '{cwd:$c, tool_input:{file_path:"tiny.txt"}} + (if $a == "" then {} else {agent_type:$a} end)')"
done

# (4) 拒否理由の全文: どの制限が発火したかを文言で確定させる
env -u CDPATH TOKEN_SHUNT_SCAN_BUDGET_BYTES=1 plugin/hooks/check-file-size \
  <<<"$(jq -nc --arg c "$T" '{cwd:$c, tool_input:{file_path:"tiny.txt"}}')" \
  | jq -r '.hookSpecificOutput.permissionDecisionReason'
env -u CDPATH TOKEN_SHUNT_SCAN_BUDGET_MS=0 plugin/hooks/check-file-size \
  <<<"$(jq -nc --arg c "$T" '{cwd:$c, tool_input:{file_path:"tiny.txt"}}')" \
  | jq -r '.hookSpecificOutput.permissionDecisionReason'
rm -rf "$T"
```

期待（コードから読める予測、実行で確認すること）: 親はすべて `deny`、
`token-shunt:bulk-reader` はすべて `pass`。worker allowlist は
`check-file-size:153-165` と `check-bash-read:173` にあり、サイズ判定・走査予算
判定より前にあるため、フック側の3制限はいずれも worker に適用されない。
(4) の拒否理由は `Scan budget exceeded (read_bytes=2/1, ms=.../2000)` を含み、
`read_bytes` 側と `ms` 側のどちらが発火したかを区別できる。**この区別は Task 5 の
実装条件**になる: 時間予算（`ms` 側）の超過は設計 §5 でテンプレート対象外なので、
バイト側だけをテンプレートに載せる。

- [ ] **Step 2: ネイティブ Read のトークン上限が worker にも適用されることを確認する**

これはフックの外なので、上のスクリプトでは判定できない。`reviews/live-rerun-2026-09-14c.md` と `reviews/cost-structure-2026-09-14.md` の `auto-one-line`（70KB 単一行）の実行記録を読み、worker 側でも Read が拒否され `status: partial` / `stop_reason: unreadable_line` に落ちている実行があるかを確認する。

```bash
cd /home/dev/projects/skills/token-shunt
grep -n "one-line\|unreadable_line\|read_max_output_tokens" reviews/live-rerun-2026-09-14c.md reviews/cost-structure-2026-09-14.md
grep -n "read_max_output_tokens" evals/compare/cases.json
```

結論として次を確定する: **ネイティブ Read のトークン上限は worker にも同じく適用される**（`CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS` は親プロセスの環境変数で、サブエージェントも同じプロセスツリーで動く）。したがって単一巨大行に起因する拒否は「同一制限で子も拒否される」ケースであり、テンプレートの「First call only ... stop and report partial」節が担当する。

- [ ] **Step 3: 判定表を確定して記録ファイルを書く**

`reviews/worker-limit-applicability-2026-09-14.md` に、次の見出しで書く。

```markdown
# worker 側の制限適用の確認（2026-09-14）

## 確認方法
（Step 1 のスクリプトと Step 2 の参照記録をそのまま貼る）

## 結果

| 制限 | worker に適用されるか | 根拠 | 委譲で処理継続が可能か |
|---|---|---|---|
| サイズ閾値 | （実行結果） | check-file-size:153-165 / check-bash-read:173 | |
| 走査予算バイト数 | | | |
| 走査予算時間 | | | 設計 §5 でテンプレート対象外（適用有無は記録のみ） |
| ネイティブ Read トークン上限 | | | |

## 走査予算超過へのテンプレート適用の可否
（可 / 不可 と、その理由を1段落）

## 未確認のまま残ること
（あれば列挙。なければ「なし」と書く）
```

実行結果と食い違った予測があれば、予測ではなく**実行結果**を書き、食い違いも明記する。

- [ ] **Step 4: 確認結果を設計文書に反映する**

Step 3 の結論が「走査予算超過は委譲で継続可能」であれば、`docs/superpowers/specs/2026-09-14-reader-protocol-reduction-design.md` の §5 直後の注記（L117-124）に1行追記する:

```markdown
**確認済み（2026-09-14）**: `reviews/worker-limit-applicability-2026-09-14.md` を参照。
走査予算超過へのテンプレート適用は Task 5 で実施する。
```

「継続不可」または判断がつかない場合は、代わりに次を追記し、**Task 5 を実施しない**。

```markdown
**確認済み（2026-09-14）**: 走査予算超過では worker 側でも継続できないため、
テンプレートを適用せず現行 deny を維持する（`reviews/worker-limit-applicability-2026-09-14.md`）。
```

- [ ] **Step 5: Commit**

```bash
cd /home/dev/projects/skills/token-shunt
git add reviews/worker-limit-applicability-2026-09-14.md docs/superpowers/specs/2026-09-14-reader-protocol-reduction-design.md
git commit -m "docs: confirm worker-side limit applicability for the reader contract"
```

---

### Task 2: 契約の正本ファイルとバイト数の回帰テスト

**Files:**
- Create: `plugin/hooks/reader-call-contract`
- Create: `evals/test_reader_call_contract.py`
- Modify: `evals/run.sh:214`（標準スイートのループに `reader_call_contract` を追加）

**Interfaces:**
- Produces: `plugin/hooks/reader-call-contract` — プレーンテキスト。`{REASON}` と `{PATHS}` をそれぞれ独立した行に含む。Task 3〜5 のフックがこのファイルを `$HOOK_DIR/reader-call-contract` として読む。
- Produces: `evals/test_reader_call_contract.py` の `ContractBodyTests` — 固定本文のバイト数回帰。Task 3〜5 はこの同じファイルにテストクラスを追加する。

- [ ] **Step 1: 失敗するテストを書く**

`evals/test_reader_call_contract.py` を新規作成する（`evals/test_clean_context_fixes.py` のスタイルに合わせる）。

```python
"""Check the reader call contract source of truth and its deny rendering."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / 'plugin/hooks'
CONTRACT = HOOKS / 'reader-call-contract'

# The rendered deny must carry the call spec; these markers identify it.
MARKERS = ('Agent: subagent_type=token-shunt:bulk-reader',
           'use haiku. Pass a concrete model, never "auto".',
           'First call only.',
           'paths:')


class ContractBodyTests(unittest.TestCase):
    def test_placeholders_are_present_on_their_own_lines(self):
        lines = CONTRACT.read_text(encoding='utf-8').split('\n')
        self.assertIn('{REASON}', lines)
        self.assertIn('{PATHS}', lines)

    def test_fixed_body_stays_within_900_bytes(self):
        lines = [l for l in CONTRACT.read_text(encoding='utf-8').split('\n')
                 if l not in ('{REASON}', '{PATHS}')]
        fixed = '\n'.join(lines).encode('utf-8')
        self.assertLessEqual(len(fixed), 900, len(fixed))
        self.assertGreater(len(fixed), 400, 'contract looks truncated')

    def test_contract_states_the_required_obligations(self):
        body = CONTRACT.read_text(encoding='utf-8')
        for marker in MARKERS[:3]:
            self.assertIn(marker, body)
        self.assertIn('unabbreviated', body)
        self.assertIn('status: complete|partial', body)


if __name__ == '__main__':
    unittest.main()
```

**`unittest.main()` はこのファイルの末尾にだけ置く。** Task 3・4・5・6 はこの
同じファイルにクラスを追加するが、**必ず `if __name__ == '__main__':` ブロックの
前に挿入する**。ファイル末尾に追記すると、`python3 evals/test_reader_call_contract.py`
で直接実行したときに `unittest.main()` が先に走り、後ろのクラスが読み込まれない。
`evals/run.sh` は直接実行の形（`python3 -B evals/test_<suite>.py`）で呼ぶため、
この取り違えは回帰の取りこぼしになる。

- [ ] **Step 2: 失敗することを確認する**

Run: `cd /home/dev/projects/skills/token-shunt && python3 -B evals/test_reader_call_contract.py`
Expected: FAIL（`FileNotFoundError: .../plugin/hooks/reader-call-contract`）

- [ ] **Step 3: 正本を作る**

```bash
cd /home/dev/projects/skills/token-shunt
cat > plugin/hooks/reader-call-contract <<'CONTRACT_EOF'
{REASON}
Delegate now — do not read these paths yourself, and do not load the
bulk-reader skill for this call.
Agent: subagent_type=token-shunt:bulk-reader
  model: the worker model the caller specified; if none or "auto",
  use haiku. Pass a concrete model, never "auto".
  prompt must contain: your question; the paths below with sizes; and —
  "One bullet per fact: confirmed: <absolute path> — <symbol>: <fact>.
   unconfirmed for missing evidence. No source lines or code fences.
   Max 4000 chars. End with two plain lines: status: complete|partial,
   then stop_reason: <reason>."
{PATHS}
First call only. If the worker is refused by this same limit, stop and
report partial — do not delegate again. For any other partial, consult
the bulk-reader skill before retrying.
In your final answer keep each confirmed bullet with its full absolute
path, unabbreviated.
CONTRACT_EOF
```

実行ビットは不要（フックが `cat` で読むだけ）。`scripts/build-zip.sh` は `plugin/` 配下を丸ごと収めるので、追加設定はいらない。

- [ ] **Step 4: テストが通ることを確認する**

Run: `cd /home/dev/projects/skills/token-shunt && python3 -B evals/test_reader_call_contract.py -v`
Expected: PASS（3件）。固定本文は 860 バイトのはず。

- [ ] **Step 5: `evals/run.sh` に登録する**

`evals/run.sh:214` の標準スイートのループに追加する。

```bash
cd /home/dev/projects/skills/token-shunt
python3 - <<'PY'
from pathlib import Path
p = Path('evals/run.sh')
s = p.read_text(encoding='utf-8')
old = 'for suite in reader_contract bash_finding_fixes clean_context_fixes hook_logging doctor_record; do'
new = ('for suite in reader_contract reader_call_contract bash_finding_fixes '
       'clean_context_fixes hook_logging doctor_record; do')
assert s.count(old) == 1
p.write_text(s.replace(old, new), encoding='utf-8')
PY
grep -n "for suite in" evals/run.sh
```

- [ ] **Step 6: ハーネス全体を流す**

Run: `cd /home/dev/projects/skills/token-shunt && ./evals/run.sh 2>&1 | tail -5`
Expected: 失敗0。件数は 123 から増える（新スイート1件）。

- [ ] **Step 7: Commit**

```bash
cd /home/dev/projects/skills/token-shunt
git add plugin/hooks/reader-call-contract evals/test_reader_call_contract.py evals/run.sh
git commit -m "feat: add the reader call contract source of truth"
```

---

### Task 3: `check-file-size` のサイズ超過 deny にテンプレートを載せる

走査予算超過（`UNDETERMINED`）は**このタスクでは変更しない**。Task 5 が扱う。

**Files:**
- Modify: `plugin/hooks/check-file-size`（`deny_reason` の直後にレンダラを追加、L196/199/204/211 の deny 呼び出しを分岐）
- Modify: `evals/test_reader_call_contract.py`（テストクラスを追加）

**Interfaces:**
- Consumes: `plugin/hooks/reader-call-contract`（Task 2）
- Produces: シェル関数 `contract_add_path <path> <size|unknown>`、`render_contract <reason>`（成功時は本文を stdout、失敗時は戻り値1）、`deny_contract <template-reason> <fallback-reason>`（レンダリングできれば契約付きで deny、できなければ `deny "$2"` = 現行文言）。Task 4 は `check-bash-read` に**同じ名前・同じ引数**でこの3関数を複製する（両フックは既に `deny` / `file_size` を複製しており、共有ライブラリを持たない）。
- Produces: `contract_reason <lines> <bytes>` — テンプレートの `{REASON}` に入れる短い理由文。

- [ ] **Step 1: 失敗するテストを書く**

`evals/test_reader_call_contract.py` の `if __name__ == '__main__':` の**前に**
挿入する（`import` 群はすでにある）。

先頭の定数部に、**現行フックの拒否文言をそのまま**書き写す。これは変更前の
フックを実際に叩いて得た全文であり、フォールバックはこれと**完全一致**しなければ
ならない。

```python
# Captured from the unmodified hooks on 2026-09-14. The fallback path must keep
# returning exactly this, not the shortened template reason.
LEGACY_READ_SIZE = (
    'File exceeds token-shunt thresholds (bytes=%d/65536). '
    'Use /token-shunt:bulk-reader. For edits, use a targeted Read of the '
    'original that passes the hook. If that fails, editing is outside v0.1 scope.')
LEGACY_BASH_SIZE = (
    "Bash 'cat' on a large file exceeds token-shunt thresholds (bytes=%d/65536). "
    'Use /token-shunt:bulk-reader. For edits, use a targeted Read of the '
    'original that passes the hook.')
```

```python
class RenderedDenyTests(unittest.TestCase):
    """The template must reach the parent only on delegable reader denies."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.big = self.root / 'big.txt'
        self.big.write_bytes(b'x\n' * 200000)
        self.small = self.root / 'small.txt'
        self.small.write_bytes(b'ok\n')
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith('TOKEN_SHUNT_') and k != 'CDPATH'}

    def invoke(self, event, hook='check-file-size', hooks=None):
        result = subprocess.run([str((hooks or HOOKS) / hook)],
                                input=json.dumps(event), cwd=self.root,
                                env=self.env, text=True, capture_output=True,
                                timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        if not result.stdout:
            return 'pass', ''
        payload = json.loads(result.stdout)['hookSpecificOutput']
        return payload['permissionDecision'], payload['permissionDecisionReason']

    def assertTemplated(self, reason):
        for marker in MARKERS:
            self.assertIn(marker, reason)

    def assertNotTemplated(self, reason):
        self.assertNotIn(MARKERS[0], reason)
        self.assertIn('bulk-reader', reason)

    def test_size_exceeded_read_carries_the_contract_and_real_size(self):
        decision, reason = self.invoke({'cwd': str(self.root),
                                        'tool_input': {'file_path': 'big.txt'}})
        self.assertEqual(decision, 'deny')
        self.assertTemplated(reason)
        self.assertIn('%s (%d B)' % (self.big, self.big.stat().st_size), reason)
        self.assertNotIn('{REASON}', reason)
        self.assertNotIn('{PATHS}', reason)

    def test_bad_limit_on_an_oversized_file_carries_the_contract(self):
        for bad in ('0', 'abc', '-1'):
            decision, reason = self.invoke(
                {'cwd': str(self.root),
                 'tool_input': {'file_path': 'big.txt', 'limit': bad}})
            self.assertEqual(decision, 'deny', bad)
            self.assertTemplated(reason)

    def test_oversized_range_carries_the_contract(self):
        decision, reason = self.invoke(
            {'cwd': str(self.root),
             'tool_input': {'file_path': 'big.txt', 'limit': 190000, 'offset': 2}})
        self.assertEqual(decision, 'deny')
        self.assertTemplated(reason)

    def test_worker_read_still_passes(self):
        decision, _ = self.invoke({'cwd': str(self.root),
                                   'agent_type': 'token-shunt:bulk-reader',
                                   'tool_input': {'file_path': 'big.txt'}})
        self.assertEqual(decision, 'pass')

    def test_small_file_still_passes(self):
        decision, _ = self.invoke({'cwd': str(self.root),
                                   'tool_input': {'file_path': 'small.txt'}})
        self.assertEqual(decision, 'pass')

    def legacy(self):
        """The exact wording the parent sees today, for full-string equality."""
        return LEGACY_READ_SIZE % self.big.stat().st_size

    def broken_contract(self, name, mutate):
        alt = self.root / name
        shutil.copytree(HOOKS, alt)
        mutate(alt / 'reader-call-contract')
        return alt

    def test_missing_contract_falls_back_to_the_current_wording(self):
        alt = self.broken_contract('hooks1', lambda f: f.unlink())
        decision, reason = self.invoke({'cwd': str(self.root),
                                        'tool_input': {'file_path': 'big.txt'}},
                                       hooks=alt)
        self.assertEqual(decision, 'deny')
        self.assertEqual(reason, self.legacy())

    def test_unreadable_contract_falls_back_to_the_current_wording(self):
        if os.geteuid() == 0:
            self.skipTest('root ignores the unreadable mode')
        alt = self.broken_contract('hooks2', lambda f: f.chmod(0o000))
        self.addCleanup((alt / 'reader-call-contract').chmod, 0o644)
        decision, reason = self.invoke({'cwd': str(self.root),
                                        'tool_input': {'file_path': 'big.txt'}},
                                       hooks=alt)
        self.assertEqual(decision, 'deny')
        self.assertEqual(reason, self.legacy())

    def test_placeholderless_contract_falls_back(self):
        alt = self.broken_contract(
            'hooks3',
            lambda f: f.write_text('no placeholders here\n', encoding='utf-8'))
        decision, reason = self.invoke({'cwd': str(self.root),
                                        'tool_input': {'file_path': 'big.txt'}},
                                       hooks=alt)
        self.assertEqual(decision, 'deny')
        self.assertEqual(reason, self.legacy())
```

`assertEqual` で全文一致を見るのが要点。`assertNotTemplated`（`MARKERS[0]` が無い
ことだけを見る）では、短縮した契約用理由がフォールバックに漏れても通ってしまう。
`assertNotTemplated` は、全文が定数化できない経路（走査予算の `ms=` を含む文言など）
にだけ使う。

- [ ] **Step 2: 失敗することを確認する**

Run: `cd /home/dev/projects/skills/token-shunt && python3 -B evals/test_reader_call_contract.py RenderedDenyTests -v`
Expected: FAIL。`test_size_exceeded_read_carries_the_contract_and_real_size` は `'Agent: subagent_type=token-shunt:bulk-reader' not found in 'File exceeds token-shunt thresholds ...'`。

- [ ] **Step 3: レンダラを実装する**

`plugin/hooks/check-file-size` の `deny_reason()` 定義（L140 付近）の直後に追加する。

```bash
# --- reader call contract (spec 2026-09-14 §4) ---
CONTRACT_FILE=$HOOK_DIR/reader-call-contract
CONTRACT_PATHS=()

contract_add_path() { # absolute-path size-or-empty
  local abs=$1
  [[ $abs == /* ]] || abs=$PWD/$abs
  if [[ $2 =~ ^[0-9]+$ ]]; then
    CONTRACT_PATHS+=("$abs ($2 B)")
  else
    CONTRACT_PATHS+=("$abs (size unknown)")
  fi
}

# Fail closed to the current wording: a missing, unreadable, or malformed
# source of truth must never drop the deny itself.
render_contract() { # reason
  local body paths
  (( ${#CONTRACT_PATHS[@]} )) || return 1
  body=$(cat -- "$CONTRACT_FILE" 2>/dev/null) || return 1
  [[ $body == *'{REASON}'* && $body == *'{PATHS}'* ]] || return 1
  printf -v paths 'paths:\n%s' "$(printf '%s\n' "${CONTRACT_PATHS[@]}")"
  body=${body/'{REASON}'/"$1"}
  body=${body/'{PATHS}'/"$paths"}
  printf '%s' "$body"
}

# The template reason and the fallback reason are different texts: rendering
# failure must return the current wording, never the shortened template reason.
deny_contract() { # template-reason fallback-reason
  local rendered
  rendered=$(render_contract "$1") && deny "$rendered"
  deny "$2"
}

contract_reason() { # lines bytes
  local parts
  if [[ $1 == -1 ]]; then parts="bytes=${2}/${MIN_BYTES}"
  else parts="lines=${1}/${MIN_LINES}, bytes=${2}/${MIN_BYTES}"; fi
  printf 'File exceeds token-shunt thresholds (%s). For edits, use a targeted Read of the original that passes the hook.' "$parts"
}
```

`deny` は `exit 0` するので `deny_contract` の `deny "$2"` は、レンダリングに
失敗したときだけ到達する。`$1` は短縮した契約用理由、`$2` は現行の
`deny_reason` 出力そのもの。両者を取り違えるとフォールバックが現行文言でなくなる。

- [ ] **Step 4: サイズ超過の deny 呼び出しを差し替える**

L196〜L211 の4か所を、走査予算超過（`un=1`）とそれ以外で分ける。`[[ -f $file_path ]]` は L180 付近で確認済みなので、パスは確定している。

```bash
cd /home/dev/projects/skills/token-shunt
python3 - <<'PY'
from pathlib import Path
p = Path('plugin/hooks/check-file-size')
s = p.read_text(encoding='utf-8')

old_whole = '''if [[ -z $limit ]]; then
  un0=0; [[ $fverdict == UNDETERMINED ]] && un0=1
  deny "$(deny_reason "$flines" "$fbytes" "$frb" "$fel" "$un0")"
fi'''
new_whole = '''# Size-exceeded denies route to delegation; scan-budget denies keep the
# current wording until the worker-side limit check confirms continuation.
if [[ $fverdict == EXCEEDED ]]; then
  contract_add_path "$file_path" "$fbytes"
fi
if [[ -z $limit ]]; then
  un0=0; [[ $fverdict == UNDETERMINED ]] && un0=1
  (( un0 )) && deny "$(deny_reason "$flines" "$fbytes" "$frb" "$fel" 1)"
  deny_contract "$(contract_reason "$flines" "$fbytes")" \\
                "$(deny_reason "$flines" "$fbytes" "$frb" "$fel" 0)"
fi'''
assert s.count(old_whole) == 1
s = s.replace(old_whole, new_whole)

old_limit = '''if ! [[ $limit =~ ^[0-9]+$ ]] || (( ${#limit} > 15 || 10#$limit < 1 )); then
  deny "$(deny_reason "$flines" "$fbytes" "$frb" "$fel" 0)"
fi'''
new_limit = '''if ! [[ $limit =~ ^[0-9]+$ ]] || (( ${#limit} > 15 || 10#$limit < 1 )); then
  deny_contract "$(contract_reason "$flines" "$fbytes")" \\
                "$(deny_reason "$flines" "$fbytes" "$frb" "$fel" 0)"
fi'''
assert s.count(old_limit) == 1
s = s.replace(old_limit, new_limit)

old_offset = '''  if ! [[ $offset =~ ^[0-9]+$ ]] || (( ${#offset} > 15 || 10#$offset < 1 )); then
    deny "$(deny_reason "$flines" "$fbytes" "$frb" "$fel" 0)"
  fi'''
new_offset = '''  if ! [[ $offset =~ ^[0-9]+$ ]] || (( ${#offset} > 15 || 10#$offset < 1 )); then
    deny_contract "$(contract_reason "$flines" "$fbytes")" \\
                  "$(deny_reason "$flines" "$fbytes" "$frb" "$fel" 0)"
  fi'''
assert s.count(old_offset) == 1
s = s.replace(old_offset, new_offset)

old_range = '''if (( ex )); then
  deny "$(deny_reason "$rl" "$rby" "$rd" "$el" "$un")"
fi'''
new_range = '''if (( ex )); then
  (( un )) && deny "$(deny_reason "$rl" "$rby" "$rd" "$el" 1)"
  deny_contract "$(contract_reason "$rl" "$rby")" \\
                "$(deny_reason "$rl" "$rby" "$rd" "$el" 0)"
fi'''
assert s.count(old_range) == 1
s = s.replace(old_range, new_range)

p.write_text(s, encoding='utf-8')
PY
bash -n plugin/hooks/check-file-size
```

`fverdict == UNDETERMINED` のときは `contract_add_path` を呼ばないので、`render_contract` は `CONTRACT_PATHS` が空で戻り値1になり、`deny_contract` は現行文言に落ちる。走査予算超過の経路が二重に守られる。

- [ ] **Step 5: テストが通ることを確認する**

Run: `cd /home/dev/projects/skills/token-shunt && python3 -B evals/test_reader_call_contract.py -v`
Expected: PASS

- [ ] **Step 6: 既存の回帰を壊していないことを確認する**

Run: `cd /home/dev/projects/skills/token-shunt && ./evals/run.sh 2>&1 | tail -5`
Expected: 失敗0。`evals/hook-evals.json` の `deny` 期待は理由に `bulk-reader` を要求するだけなので、テンプレート化しても満たされる。

- [ ] **Step 7: Commit**

```bash
cd /home/dev/projects/skills/token-shunt
git add plugin/hooks/check-file-size evals/test_reader_call_contract.py
git commit -m "feat: carry the call contract in check-file-size size denies"
```

---

### Task 4: `check-bash-read` のサイズ超過 deny にテンプレートを載せる

**Files:**
- Modify: `plugin/hooks/check-bash-read`（`bash_reason` の直後にレンダラを複製、`check_files_full` と head/tail のサイズ確定 deny を差し替え）
- Modify: `evals/test_reader_call_contract.py`（Bash 側のテストクラスを追加）

**Interfaces:**
- Consumes: Task 3 の `contract_add_path` / `render_contract` / `deny_contract`（2引数。同一シグネチャで複製する）
- Produces: `bash_contract_reason <tool> <lines> <bytes>`
- Produces: `contract_add_all_files`（引数なし。`FILES` 全件を収集し、1〜3件なら 0、それ以外は 1 を返す）。Task 5 がこれを使う。

- [ ] **Step 1: 失敗するテストを書く**

`evals/test_reader_call_contract.py` の `if __name__ == '__main__':` の**前に**
挿入する。

```python
class BashRenderedDenyTests(RenderedDenyTests):
    """Same contract obligations on the Bash path, plus its non-routing denies."""

    def bash(self, command, **kw):
        return self.invoke({'cwd': str(self.root),
                            'tool_input': {'command': command}},
                           hook='check-bash-read', **kw)

    # The Read-shaped cases in the parent class do not apply here.
    def test_bad_limit_on_an_oversized_file_carries_the_contract(self):
        self.skipTest('Read-only case')

    def test_oversized_range_carries_the_contract(self):
        self.skipTest('Read-only case')

    def test_size_exceeded_read_carries_the_contract_and_real_size(self):
        decision, reason = self.bash('cat big.txt')
        self.assertEqual(decision, 'deny')
        self.assertTemplated(reason)
        self.assertIn('%s (%d B)' % (self.big, self.big.stat().st_size), reason)

    def test_worker_read_still_passes(self):
        decision, _ = self.invoke({'cwd': str(self.root),
                                   'agent_type': 'token-shunt:bulk-reader',
                                   'tool_input': {'command': 'cat big.txt'}},
                                  hook='check-bash-read')
        self.assertEqual(decision, 'pass')

    def test_small_file_still_passes(self):
        decision, _ = self.bash('cat small.txt')
        self.assertEqual(decision, 'pass')

    def legacy(self):
        return LEGACY_BASH_SIZE % self.big.stat().st_size

    def test_missing_contract_falls_back_to_the_current_wording(self):
        alt = self.broken_contract('hooks1', lambda f: f.unlink())
        decision, reason = self.bash('cat big.txt', hooks=alt)
        self.assertEqual(decision, 'deny')
        self.assertEqual(reason, self.legacy())

    def test_unreadable_contract_falls_back_to_the_current_wording(self):
        if os.geteuid() == 0:
            self.skipTest('root ignores the unreadable mode')
        alt = self.broken_contract('hooks2', lambda f: f.chmod(0o000))
        self.addCleanup((alt / 'reader-call-contract').chmod, 0o644)
        decision, reason = self.bash('cat big.txt', hooks=alt)
        self.assertEqual(decision, 'deny')
        self.assertEqual(reason, self.legacy())

    def test_placeholderless_contract_falls_back(self):
        alt = self.broken_contract(
            'hooks3',
            lambda f: f.write_text('no placeholders\n', encoding='utf-8'))
        decision, reason = self.bash('cat big.txt', hooks=alt)
        self.assertEqual(decision, 'deny')
        self.assertEqual(reason, self.legacy())

    def sized(self, name, unit):
        path = self.root / name
        path.write_bytes(unit * 200000)
        return path

    def test_every_resolved_path_is_listed_up_to_three(self):
        second = self.sized('big2.txt', b'y\n')
        third = self.sized('big3.txt', b'z\n')
        decision, reason = self.bash('cat big.txt big2.txt big3.txt')
        self.assertEqual(decision, 'deny')
        for path in (self.big, second, third):
            self.assertIn('%s (%d B)' % (path, path.stat().st_size), reason)

    def test_four_or_more_paths_stay_on_the_batch_route(self):
        # The worker contract reads at most 3 explicit paths per call, so a
        # wider operand list is a batch decision for the skill, not a template.
        for name, unit in (('big2.txt', b'y\n'), ('big3.txt', b'z\n'),
                           ('big4.txt', b'w\n')):
            self.sized(name, unit)
        decision, reason = self.bash('cat big.txt big2.txt big3.txt big4.txt')
        self.assertEqual(decision, 'deny')
        self.assertNotIn(MARKERS[0], reason)
        self.assertEqual(reason, self.legacy())

    def test_bounded_head_lists_every_target(self):
        second = self.sized('big2.txt', b'y\n')
        decision, reason = self.bash('head -c 100000 big.txt big2.txt')
        self.assertEqual(decision, 'deny')
        for path in (self.big, second):
            self.assertIn('%s (%d B)' % (path, path.stat().st_size), reason)

    def test_non_routing_denies_keep_their_wording(self):
        cases = {
            'heredoc': 'cat <<EOF\n$(cat big.txt)\nEOF',
            'expansion': 'cat $PWD/big.txt',
            'unbounded_pipe': "cat big.txt | grep ''",
            'parse_budget': 'echo ' + 'x' * 100000,
        }
        for name, command in cases.items():
            with self.subTest(case=name):
                decision, reason = self.bash(command)
                self.assertEqual(decision, 'deny')
                self.assertNotIn(MARKERS[0], reason)

    def test_invalid_cwd_keeps_its_wording(self):
        decision, reason = self.invoke({'cwd': 'relative',
                                        'tool_input': {'command': 'cat big.txt'}},
                                       hook='check-bash-read')
        self.assertEqual(decision, 'deny')
        self.assertNotIn(MARKERS[0], reason)
```

`assertNotTemplated` は理由に `bulk-reader` が残ることも確認する。`parse_budget` と `invalid_cwd` の現行文言には `bulk-reader` が入らないため、この2件は `assertNotTemplated` ではなく `assertNotIn(MARKERS[0], ...)` だけを使っている。

- [ ] **Step 2: 失敗することを確認する**

Run: `cd /home/dev/projects/skills/token-shunt && python3 -B evals/test_reader_call_contract.py BashRenderedDenyTests -v`
Expected: FAIL（`Agent: subagent_type=...` が見つからない）

- [ ] **Step 3: レンダラを複製する**

`plugin/hooks/check-bash-read` の `bash_reason()` 定義（L161-168）の直後に、Task 3 Step 3 と**同じ** `CONTRACT_FILE` / `CONTRACT_PATHS` / `contract_add_path` / `render_contract` / `deny_contract`（2引数版）を貼る（`check-bash-read:11` に `HOOK_DIR` があるので参照はそのまま動く）。加えて Bash 用の理由文と、対象収集ヘルパを足す。

```bash
bash_contract_reason() { # tool lines bytes
  local parts
  if [[ $2 == -1 ]]; then parts="bytes=${3}/${MIN_BYTES}"
  else parts="lines=${2}/${MIN_LINES}, bytes=${3}/${MIN_BYTES}"; fi
  printf "Bash '%s' on a large file exceeds token-shunt thresholds (%s). For edits, use a targeted Read of the original that passes the hook." "$1" "$parts"
}

# One collection point for every Bash deny that can be delegated: list all
# resolved operands, not just the one that tripped the check. The worker
# contract reads at most 3 explicit paths per call, so a wider operand list
# is a batch decision and stays on the skill route (return 1 -> no template).
contract_add_all_files() {
  local other sz
  (( ${#FILES[@]} >= 1 && ${#FILES[@]} <= 3 )) || return 1
  for other in "${FILES[@]}"; do
    check_parse_budget
    sz=$(file_size "$other") || sz=""
    contract_add_path "$other" "$sz"
  done
}
```

`check_files_full` と `run_head_tail` の両方がこのヘルパを使う。件数条件を
1か所に置くことで、「全対象の収集」と「定型経路に載せる件数」がずれない。

- [ ] **Step 4: `check_files_full` を差し替える**

確定している全 `FILES` を列挙し、サイズを取れないものは `(size unknown)` にする。走査予算超過（`UNDETERMINED`）は現行文言のまま。

```bash
cd /home/dev/projects/skills/token-shunt
python3 - <<'PY'
from pathlib import Path
p = Path('plugin/hooks/check-bash-read')
s = p.read_text(encoding='utf-8')
old = '''check_files_full() { # toolname; deny on first exceeding/undetermined target
  local tool=$1 f v nl rb rd el
  for f in ${FILES[@]+"${FILES[@]}"}; do
    check_parse_budget
    read -r v nl rb rd el <<<"$(full_file_verdict "$f")"
    [[ $v == OK ]] && continue
    [[ $v == UNDETERMINED ]] && deny "$(bash_reason "$tool" "$nl" "$rb" "$rd" "$el" 1)"
    deny "$(bash_reason "$tool" "$nl" "$rb" "$rd" "$el" 0)"
  done
}'''
new = '''check_files_full() { # toolname; deny on first exceeding/undetermined target
  local tool=$1 f v nl rb rd el
  for f in ${FILES[@]+"${FILES[@]}"}; do
    check_parse_budget
    read -r v nl rb rd el <<<"$(full_file_verdict "$f")"
    [[ $v == OK ]] && continue
    [[ $v == UNDETERMINED ]] && deny "$(bash_reason "$tool" "$nl" "$rb" "$rd" "$el" 1)"
    contract_add_all_files \\
      && deny_contract "$(bash_contract_reason "$tool" "$nl" "$rb")" \\
                       "$(bash_reason "$tool" "$nl" "$rb" "$rd" "$el" 0)"
    deny "$(bash_reason "$tool" "$nl" "$rb" "$rd" "$el" 0)"
  done
}'''
assert s.count(old) == 1
p.write_text(s.replace(old, new), encoding='utf-8')
PY
bash -n plugin/hooks/check-bash-read
```

- [ ] **Step 5: `run_head_tail` のサイズ確定 deny を差し替える**

`run_head_tail`（`check-bash-read:667-718`）には、サイズが数値として確定している
deny が3か所ある。行数形（`head -n`）の範囲超過1か所と、バイト形（`head -c`）の
`st` / `actual` の2か所。**いずれも、拒否された1件だけでなく `FILES` 全件を
列挙する**（`contract_add_all_files` が担当する）。`bash_reason ... 1`
（undetermined）の4か所には触れない。それらは Task 5 が扱う。

```bash
cd /home/dev/projects/skills/token-shunt
python3 - <<'PYEOF'
from pathlib import Path
p = Path('plugin/hooks/check-bash-read')
s = p.read_text(encoding='utf-8')
pairs = [
    # line form: the requested range itself exceeded a threshold
    ('      deny "$(bash_reason "$tool" "$rl" "$rby" "$rd" "$el" 0)"',
     '      contract_add_all_files \\\n'
     '        && deny_contract "$(bash_contract_reason "$tool" "$rl" "$rby")" \\\n'
     '                         "$(bash_reason "$tool" "$rl" "$rby" "$rd" "$el" 0)"\n'
     '      deny "$(bash_reason "$tool" "$rl" "$rby" "$rd" "$el" 0)"'),
    # byte form: stat established the size
    ('      (( st > MIN_BYTES )) && deny "$(bash_reason "$tool" 0 "$st" 0 0 0)"',
     '      if (( st > MIN_BYTES )); then\n'
     '        contract_add_all_files \\\n'
     '          && deny_contract "$(bash_contract_reason "$tool" -1 "$st")" \\\n'
     '                           "$(bash_reason "$tool" 0 "$st" 0 0 0)"\n'
     '        deny "$(bash_reason "$tool" 0 "$st" 0 0 0)"\n'
     '      fi'),
    # byte form: a bounded prefix established the size
    ('      (( actual > MIN_BYTES )) && deny "$(bash_reason "$tool" 0 "$actual" "$actual" "$el" 0)"',
     '      if (( actual > MIN_BYTES )); then\n'
     '        contract_add_all_files \\\n'
     '          && deny_contract "$(bash_contract_reason "$tool" -1 "$actual")" \\\n'
     '                           "$(bash_reason "$tool" 0 "$actual" "$actual" "$el" 0)"\n'
     '        deny "$(bash_reason "$tool" 0 "$actual" "$actual" "$el" 0)"\n'
     '      fi'),
]
for old, new in pairs:
    assert s.count(old) == 1, old
    s = s.replace(old, new)
p.write_text(s, encoding='utf-8')
PYEOF
bash -n plugin/hooks/check-bash-read
```

`bash_contract_reason` に `-1` を渡すと `bytes=...` だけの文言になる。バイト形の
経路では行数を数えていないため、行数を出さないのが正しい。`contract_add_all_files`
が 1 を返す（4件以上）場合はテンプレートを使わず、現行文言の `deny` に落ちる。

- [ ] **Step 6: テストが通ることを確認する**

Run: `cd /home/dev/projects/skills/token-shunt && python3 -B evals/test_reader_call_contract.py -v`
Expected: PASS

- [ ] **Step 7: 既存回帰を流す**

Run: `cd /home/dev/projects/skills/token-shunt && ./evals/run.sh 2>&1 | tail -5`
Expected: 失敗0（`evals/bash-hook-evals.json` 73件を含む）。

- [ ] **Step 8: Commit**

```bash
cd /home/dev/projects/skills/token-shunt
git add plugin/hooks/check-bash-read evals/test_reader_call_contract.py
git commit -m "feat: carry the call contract in check-bash-read size denies"
```

---

### Task 5: 走査予算超過へのテンプレート適用（Task 1 が「継続可能」と確定した場合のみ）

**Task 1 Step 3 の結論が「不可」または未確定なら、このタスクを実施せず、その旨を Task 9 の記録に書く。**
その場合は代わりに、走査予算 deny にテンプレートが載らないことを固定する回帰を
1件だけ足す（下の `test_time_budget_is_not_templated` を、バイト予算超過にも
適用した形）。

**時間予算超過は、確定した場合でもテンプレート対象外**（設計 §5）。
バイト予算超過と走査失敗だけを載せる。

**Files:**
- Modify: `plugin/hooks/check-file-size`（`un0` / `un` 分岐）
- Modify: `plugin/hooks/check-bash-read`（`check_files_full` の UNDETERMINED 分岐と `run_head_tail` の undetermined deny）
- Modify: `evals/test_reader_call_contract.py`

**Interfaces:**
- Consumes: Task 3・4 の `contract_add_path` / `deny_contract`（2引数）/ `contract_add_all_files`
- Produces: `scan_budget_reason <read_bytes> <elapsed_ms>`（両フックに複製）
- Produces: テンプレート適用条件 `un == 1 && elapsed <= SCAN_BUDGET_MS`。
  `full_file_verdict` / `range_scan` は経過時間をそのまま返すので、
  戻り値の形を変えずに時間予算超過だけを除外できる。

- [ ] **Step 1: 失敗するテストを書く**

走査予算は、**`MIN_LINES`（350行）と `MIN_BYTES`（65536バイト）の両方を下回る
ファイル**でしか発火しない。`full_file_verdict`（`check-file-size:105-138`）は
`stat` が `MIN_BYTES` を超えた時点で `EXCEEDED` を返して走査に入らないため、
400KB の `big.txt` では予算をいくら絞っても走査予算経路に届かない。

`evals/test_reader_call_contract.py` の `if __name__ == '__main__':` の**前に**
挿入する。

```python
class ScanBudgetContractTests(unittest.TestCase):
    """Scan-budget denies only exist for files under both size thresholds."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.tiny = self.root / 'tiny.txt'
        self.tiny.write_bytes(b'abc\n')
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith('TOKEN_SHUNT_') and k != 'CDPATH'}

    def run_hook(self, hook, tool_input, **extra_env):
        result = subprocess.run(
            [str(HOOKS / hook)],
            input=json.dumps({'cwd': str(self.root), 'tool_input': tool_input}),
            cwd=self.root, env=dict(self.env, **extra_env), text=True,
            capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        if not result.stdout:
            return 'pass', ''
        out = json.loads(result.stdout)['hookSpecificOutput']
        return out['permissionDecision'], out['permissionDecisionReason']

    def test_byte_budget_templates_with_the_real_size(self):
        for hook, tool_input in (('check-file-size', {'file_path': 'tiny.txt'}),
                                 ('check-bash-read', {'command': 'cat tiny.txt'})):
            with self.subTest(hook=hook):
                decision, reason = self.run_hook(
                    hook, tool_input, TOKEN_SHUNT_SCAN_BUDGET_BYTES='1')
                self.assertEqual(decision, 'deny')
                for marker in MARKERS:
                    self.assertIn(marker, reason)
                self.assertIn('Scan budget exceeded', reason)
                self.assertNotIn('File exceeds token-shunt thresholds', reason)
                self.assertIn('%s (%d B)' % (self.tiny, self.tiny.stat().st_size),
                              reason)
                self.assertNotIn('size unknown', reason)

    def test_unobtainable_size_renders_size_unknown(self):
        # Control the stat failure directly instead of hunting for a file type
        # whose size cannot be read: a stub earlier on PATH makes file_size
        # fail while the operand itself stays valid.
        stub = self.root / 'bin'
        stub.mkdir()
        (stub / 'stat').write_text('#!/bin/sh\nexit 1\n', encoding='utf-8')
        (stub / 'stat').chmod(0o755)
        decision, reason = self.run_hook(
            'check-file-size', {'file_path': 'tiny.txt'},
            PATH='%s:%s' % (stub, self.env['PATH']))
        self.assertEqual(decision, 'deny')
        self.assertIn(MARKERS[0], reason)
        self.assertIn('%s (size unknown)' % self.tiny, reason)

    def test_time_budget_is_not_templated(self):
        decision, reason = self.run_hook(
            'check-file-size', {'file_path': 'tiny.txt'},
            TOKEN_SHUNT_SCAN_BUDGET_MS='0')
        self.assertEqual(decision, 'deny')
        self.assertNotIn(MARKERS[0], reason)
        self.assertIn('Scan budget exceeded', reason)

    def test_size_exceeded_file_never_reaches_the_scan_budget(self):
        (self.root / 'big.txt').write_bytes(b'x\n' * 200000)
        decision, reason = self.run_hook(
            'check-file-size', {'file_path': 'big.txt'},
            TOKEN_SHUNT_SCAN_BUDGET_BYTES='1')
        self.assertEqual(decision, 'deny')
        self.assertNotIn('Scan budget exceeded', reason)
        self.assertIn('File exceeds token-shunt thresholds', reason)
```

`test_time_budget_is_not_templated` は、`tiny.txt` の走査が 0ms で終わると
`elapsed > 0` が成り立たず `pass` になる。その場合は skip せず、fixture を
**340行 × 180バイト（両閾値以下、走査は計測可能な長さ）** に差し替えて確実に
発火させる。

- [ ] **Step 2: 失敗することを確認する**

Run: `cd /home/dev/projects/skills/token-shunt && python3 -B evals/test_reader_call_contract.py ScanBudgetContractTests -v`
Expected: FAIL（`Agent: subagent_type=...` が見つからない）。
`test_size_exceeded_file_never_reaches_the_scan_budget` と
`test_time_budget_is_not_templated` は Task 3 の実装だけで既に PASS するはず。
ここで FAIL するなら、Task 3 の分岐が走査予算経路を巻き込んでいる。

- [ ] **Step 3: 両フックに走査予算用の理由文を足す**

`contract_reason` / `bash_contract_reason` の直後に置く。

```bash
scan_budget_reason() { # read_bytes elapsed_ms
  printf 'Scan budget exceeded (read_bytes=%s/%s, ms=%s/%s); the size could not be established cheaply. For edits, use a targeted Read of the original that passes the hook.' \
    "$1" "$SCAN_BUDGET_BYTES" "$2" "$SCAN_BUDGET_MS"
}
```

あわせて `contract_add_path` の先頭に重複排除を入れる（両フック）。Task 3 の
サイズ経路と Task 5 の走査予算経路が同じパスを二度足す可能性があるため。

```bash
  local existing
  for existing in ${CONTRACT_PATHS[@]+"${CONTRACT_PATHS[@]}"}; do
    [[ $existing == "$abs "* ]] && return 0
  done
```

- [ ] **Step 4: `check-file-size` の undetermined 分岐を差し替える**

時間予算超過は除外する。`full_file_verdict` / `range_scan` が返す経過時間
（`$fel` / `$el`）が `SCAN_BUDGET_MS` を超えていれば時間側、そうでなければ
バイト側か走査失敗。

```bash
cd /home/dev/projects/skills/token-shunt
python3 - <<'PYEOF'
from pathlib import Path
p = Path('plugin/hooks/check-file-size')
s = p.read_text(encoding='utf-8')

old = '  (( un0 )) && deny "$(deny_reason "$flines" "$fbytes" "$frb" "$fel" 1)"'
new = """  if (( un0 )); then
    # Byte-budget overruns and scan failures are delegable. A time-budget
    # overrun is excluded by design 2026-09-14 5, so it keeps the current
    # wording; the elapsed value distinguishes them without changing the
    # verdict tuple.
    if (( fel <= SCAN_BUDGET_MS )); then
      sz=$(file_size "$file_path") || sz=""
      contract_add_path "$file_path" "$sz"
      deny_contract "$(scan_budget_reason "$frb" "$fel")" \\
                    "$(deny_reason "$flines" "$fbytes" "$frb" "$fel" 1)"
    fi
    deny "$(deny_reason "$flines" "$fbytes" "$frb" "$fel" 1)"
  fi"""
assert s.count(old) == 1
s = s.replace(old, new)

old_range = '  (( un )) && deny "$(deny_reason "$rl" "$rby" "$rd" "$el" 1)"'
new_range = """  if (( un )); then
    if (( el <= SCAN_BUDGET_MS )); then
      sz=$(file_size "$file_path") || sz=""
      contract_add_path "$file_path" "$sz"
      deny_contract "$(scan_budget_reason "$rd" "$el")" \\
                    "$(deny_reason "$rl" "$rby" "$rd" "$el" 1)"
    fi
    deny "$(deny_reason "$rl" "$rby" "$rd" "$el" 1)"
  fi"""
assert s.count(old_range) == 1
p.write_text(s.replace(old_range, new_range), encoding='utf-8')
PYEOF
bash -n plugin/hooks/check-file-size
```

- [ ] **Step 5: `check-bash-read` の undetermined 分岐を差し替える**

対象は、**パスが確定している** undetermined deny だけ。まず該当行を読んで
`$f` が有効かを確認する。

```bash
cd /home/dev/projects/skills/token-shunt
grep -n 'bash_reason "$tool" .* 1)"' plugin/hooks/check-bash-read
```

`check_files_full` の `[[ $v == UNDETERMINED ]] && deny ...` と、`run_head_tail`
の undetermined deny を、次の形に置き換える（`$EL` は各文脈の経過時間。
`el` が無い経路では 0 なので常に `<= SCAN_BUDGET_MS` となり、走査失敗として
テンプレート対象になる）。

```bash
  if (( EL <= SCAN_BUDGET_MS )); then
    contract_add_all_files \
      && deny_contract "$(scan_budget_reason "$RD" "$EL")" \
                       "$(bash_reason "$tool" "$NL" "$RB" "$RD" "$EL" 1)"
  fi
  deny "$(bash_reason "$tool" "$NL" "$RB" "$RD" "$EL" 1)"
```

`(( actual > SCAN_BUDGET_BYTES || el > SCAN_BUDGET_MS ))` の1か所だけは、
バイト側と時間側が同じ条件にまとまっている。**2つに割る**:

```bash
      if (( actual > SCAN_BUDGET_BYTES )) && (( el <= SCAN_BUDGET_MS )); then
        contract_add_all_files \
          && deny_contract "$(scan_budget_reason "$actual" "$el")" \
                           "$(bash_reason "$tool" 0 "$actual" "$actual" "$el" 1)"
      fi
      (( actual > SCAN_BUDGET_BYTES || el > SCAN_BUDGET_MS )) \
        && deny "$(bash_reason "$tool" 0 "$actual" "$actual" "$el" 1)"
```

パスが確定していない undetermined deny（`FS_UNCERTAIN` やシェル展開の経路）は
**変更しない**。`contract_add_all_files` は `FILES` が空なら 1 を返すので、
取りこぼしても現行文言に落ちる。

- [ ] **Step 6: テストが通ることを確認する**

Run: `cd /home/dev/projects/skills/token-shunt && python3 -B evals/test_reader_call_contract.py -v`
Expected: PASS（走査予算のテストクラスもこのファイルに入る。別ファイルは作らない）

- [ ] **Step 7: 全体回帰**

Run: `cd /home/dev/projects/skills/token-shunt && ./evals/run.sh 2>&1 | tail -5`
Expected: 失敗0

- [ ] **Step 8: Commit**

```bash
cd /home/dev/projects/skills/token-shunt
git add plugin/hooks/check-file-size plugin/hooks/check-bash-read evals/test_reader_call_contract.py
git commit -m "feat: apply the call contract to delegable scan-budget denies"
```

---

### Task 6: SKILL.md と agent md から親向け呼び出し仕様を外す

**Files:**
- Modify: `plugin/skills/bulk-reader/SKILL.md`（frontmatter `description`、手順1〜3の定型部分、返答契約の再掲、メタデータ探索手順）
- Modify: `plugin/agents/bulk-reader.md`（親向け呼び出し仕様の重複のみ）
- Modify: `evals/test_reader_call_contract.py`（文書側の回帰）

**Interfaces:**
- Consumes: `plugin/hooks/reader-call-contract`（明示委譲手順が参照する）
- Produces: なし（文書のみ）

- [ ] **Step 1: 失敗するテストを書く**

```python
class SkillDocumentTests(unittest.TestCase):
    SKILL = ROOT / 'plugin/skills/bulk-reader/SKILL.md'
    AGENT = ROOT / 'plugin/agents/bulk-reader.md'

    def test_description_defers_to_the_deny_for_typical_cases(self):
        head = self.SKILL.read_text(encoding='utf-8').split('---')[1]
        self.assertIn('Not needed when the deny already carries the call spec',
                      head)
        for keyword in ('explicit delegation', 'batch', 'ambiguity', 'retry'):
            self.assertIn(keyword, head.lower())

    def test_skill_no_longer_restates_the_parent_call_spec(self):
        body = self.SKILL.read_text(encoding='utf-8')
        for gone in ("awk 'END{print NR}'", 'One bullet per fact: confirmed:',
                     'Maximum 4000 characters total'):
            self.assertNotIn(gone, body)

    def test_skill_keeps_the_out_of_scope_and_explicit_delegation_notes(self):
        body = self.SKILL.read_text(encoding='utf-8')
        self.assertIn('hooks/reader-call-contract', body)
        self.assertIn('(size unknown)', body)
        self.assertIn('Explicit delegation (no hook deny)', body)
        self.assertIn('16384', body)   # multi-small-file note stays

    def test_agent_keeps_its_own_execution_contract(self):
        body = self.AGENT.read_text(encoding='utf-8')
        for kept in ('next_line', '4000 character', 'stop_reason',
                     'unreadable_line'):
            self.assertIn(kept, body)

    def test_skill_shrinks_below_six_kilobytes(self):
        self.assertLess(self.SKILL.stat().st_size, 6144,
                        self.SKILL.stat().st_size)
```

- [ ] **Step 2: 失敗することを確認する**

Run: `cd /home/dev/projects/skills/token-shunt && python3 -B evals/test_reader_call_contract.py SkillDocumentTests -v`
Expected: FAIL（現行 SKILL.md は 12,235 バイト、旧 description のまま）

- [ ] **Step 3: `description` を書き換える**

```yaml
description: Not needed when the deny already carries the call spec — follow the deny and delegate. Use for explicit delegation with no hook deny, batch boundaries (4+ paths, cross-file relationships), ambiguity between confirmed and unconfirmed evidence, and retry or model-escalation decisions after a partial. Not for debugging, architectural decisions, or edits needing exact parent context. Do not @-mention large files.
```

- [ ] **Step 4: 本文から定型呼び出し仕様を外す**

削除するのは次の範囲。

| 削除 | 現在の位置 |
|---|---|
| `--worker-model` 解釈と Agent 呼び出しの手順（前文） | L7-12 |
| 手順1のメタデータ探索の手順（`stat`/`wc -c` で測る部分） | 手順1の後半 |
| 手順2（委譲プロンプトの構成、行数の事前取得、返答契約の全文） | 手順2すべて |
| 手順4「Child contract」の子向け指示の再掲 | 手順4すべて（agent md に同内容がある） |

残すのは: 手順1の小タスク判定（16384バイト境界）と §26.5 のルート判定、手順3のバッチ境界とバッチ間証拠契約、手順5の follow-up、手順6の編集契約、手順7の Explore、「Model escalation」節、`--worker-model` の意味論（1〜2行に圧縮）。

新規に追加する節（本文末尾）:

```markdown
## Explicit delegation (no hook deny)

Read `${CLAUDE_PLUGIN_ROOT}/hooks/reader-call-contract`, substitute
`{REASON}` with `Explicit delegation (no hook deny)` and `{PATHS}` with the
target paths and their sizes, then call Agent exactly as that contract
specifies. Write `(size unknown)` for any path whose size you do not
already have; do not run metadata commands just to obtain a size.

## Out of scope in v0.1

Several small files whose individual sizes are under the hook thresholds do
not fire a deny, even when their total I/O exceeds 16384 bytes. v0.1 does
not auto-delegate that case; delegate through this skill only when the
parent decides it is needed.
```

- [ ] **Step 5: agent md から親向けの重複を外す**

`plugin/agents/bulk-reader.md` L13-16 の「Runtime hooks enforce ... Follow the hook's required offset」は子の実行契約なので**残す**。親向けの再掲は現状ほぼ無いので、確認のうえ変更なしでよい場合は「変更なし」と記録する。実際に重複しているのは次のみで、これを削る:

```bash
cd /home/dev/projects/skills/token-shunt
grep -n "invoked via the token-shunt bulk-reader skill" plugin/agents/bulk-reader.md
```

frontmatter の `description` を、スキル経由という前提を外した表現に変える:

```yaml
description: Bounded reader of up to three explicitly supplied files. Reads only the given paths and returns path-tagged facts.
```

- [ ] **Step 6: テストが通ることを確認する**

Run: `cd /home/dev/projects/skills/token-shunt && python3 -B evals/test_reader_call_contract.py -v && python3 -B evals/test_reader_contract.py`
Expected: 両方 PASS。`test_reader_contract.py` が SKILL.md の削除済み文言を参照して落ちる場合は、**削除が正しい**ので、そのアサーションを新しい配置（正本ファイル or agent md）を見るように直す。直した箇所は Step 8 のコミットメッセージに書く。

- [ ] **Step 7: 全体回帰と ZIP 再生成**

```bash
cd /home/dev/projects/skills/token-shunt
./evals/run.sh 2>&1 | tail -5
./scripts/build-zip.sh
```
Expected: 失敗0、`build-zip` の検証が成功

- [ ] **Step 8: Commit**

```bash
cd /home/dev/projects/skills/token-shunt
git add plugin/skills/bulk-reader/SKILL.md plugin/agents/bulk-reader.md \
        evals/test_reader_call_contract.py evals/test_reader_contract.py token-shunt.zip
git commit -m "refactor: move the parent call spec out of the reader skill"
```

---

### Task 7: 設計文書（`docs/2026-09-12-token-shunt-design.md`）の改訂

**Files:**
- Modify: `docs/2026-09-12-token-shunt-design.md`（§26.5 L448 付近、§11、§26.2 L868 付近、§26.1、§5 適用条件の新規節）

**Interfaces:**
- Consumes: 設計仕様 §7 の改訂表
- Produces: なし

- [ ] **Step 1: 改訂対象の現行文言を読む**

```bash
cd /home/dev/projects/skills/token-shunt
sed -n '440,460p' docs/2026-09-12-token-shunt-design.md
sed -n '860,880p' docs/2026-09-12-token-shunt-design.md
grep -n '^## §11\|^### §11\|^## §26\|^### §26' docs/2026-09-12-token-shunt-design.md
```

- [ ] **Step 2: 4か所を改訂する**

| 節 | 改訂内容 |
|---|---|
| §26.5 | 「フックが deny するファイルでは、**deny が経路判定そのもの**になる。事前のメタデータ探索は不要」を追記。「超過と分かっているファイルを本文検索しない」という既存の禁止規則は**そのまま維持**する |
| §11 | 子へ渡すのは**サイズのみ**。行数の事前取得は要求しない（子は自分の Read の `totalLines` で把握する）。サイズ未取得時は `size unknown` を許容する |
| §26.2 | 「総I/O 16384バイト以下なら親が直接」は維持。超過側の自動発火は deny のある経路に限る。複数小ファイルの総I/O超過は v0.1 では自動発火しない |
| §26.1 | 契約の正本は `plugin/hooks/reader-call-contract`。SKILL.md と agent md は親向け呼び出し仕様を再掲しない |

- [ ] **Step 3: 適用条件表とフェイルセーフを新規節として足す**

設計仕様 §5 の表をそのまま転記し、末尾に1文を添える:

```markdown
正本が欠落・読み込み不能・プレースホルダ欠損のいずれかなら、テンプレートを
使わず現行の deny 文言をそのまま返す。deny 自体を落とすことはない。
```

- [ ] **Step 4: 文書内の整合を確認する**

```bash
cd /home/dev/projects/skills/token-shunt
grep -n "wc -l\|awk 'END{print NR}'\|line count" docs/2026-09-12-token-shunt-design.md
```
§11 の改訂と矛盾する「行数を事前に取得する」記述が残っていれば直す。

- [ ] **Step 5: 回帰を流す**

Run: `cd /home/dev/projects/skills/token-shunt && ./evals/run.sh 2>&1 | tail -5`
Expected: 失敗0（設計文書を参照するチェックがあれば、そこも通る）

- [ ] **Step 6: Commit**

```bash
cd /home/dev/projects/skills/token-shunt
git add docs/2026-09-12-token-shunt-design.md
git commit -m "docs: route through the deny and drop the line-count prefetch"
```

---

### Task 8: `cost_probe.py` に Skill 読み込み・deny 回数・注入バイト数の計測を足す

**Files:**
- Modify: `evals/compare/cost_probe.py`（`CASES` のフィルタ引数、`run_one` のフックログ、`metrics` の追加指標）
- Create: `evals/compare/test_cost_probe_metrics.py`

**Interfaces:**
- Produces: `metrics(path, hooklog=None)` が返す辞書に `skill_loads`（int）、`deny_count`（int）、`deny_bytes`（int）を追加。既存キーは変えない。
- Produces: `python3 evals/compare/cost_probe.py <repeats> [case-id ...]` — ケースを絞れるようにする。

- [ ] **Step 1: 失敗するテストを書く**

`evals/compare/test_cost_probe_metrics.py`:

```python
"""The cost probe must count skill loads and the bytes each deny injects."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cost_probe


class MetricsTests(unittest.TestCase):
    def write(self, events):
        fh = tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False,
                                         encoding='utf-8')
        for event in events:
            fh.write(json.dumps(event) + '\n')
        fh.close()
        return fh.name

    def assistant(self, *tools, child=False):
        event = {'type': 'assistant',
                 'message': {'content': [{'type': 'tool_use', 'name': n}
                                         for n in tools]}}
        if child:
            event['parent_tool_use_id'] = 'toolu_1'
        return event

    def result(self):
        return {'type': 'result', 'is_error': False, 'total_cost_usd': 0.1,
                'usage': {}, 'modelUsage': {}, 'num_turns': 2, 'result': 'ok'}

    def read_skill_md(self):
        return {'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'name': 'Read',
             'input': {'file_path': '/p/plugin/skills/bulk-reader/SKILL.md'}}]}}

    def test_skill_loads_count_both_tool_and_skill_md_read(self):
        path = self.write([self.assistant('Skill'),
                           self.read_skill_md(),
                           self.assistant('Agent'),
                           self.result()])
        row = cost_probe.metrics(path)
        self.assertEqual(row['skill_loads'], 2)
        self.assertEqual(row['parent_reads'], 1)

    def test_child_skill_use_is_not_counted_as_a_parent_load(self):
        path = self.write([self.assistant('Skill', child=True), self.result()])
        self.assertEqual(cost_probe.metrics(path)['skill_loads'], 0)

    def test_deny_count_and_bytes_come_from_the_hook_log(self):
        path = self.write([self.assistant('Read'), self.result()])
        log = tempfile.NamedTemporaryFile('w', suffix='.hooklog', delete=False,
                                          encoding='utf-8')
        log.write(json.dumps({'hook': 'check-file-size', 'decision': 'pass',
                              'reason': ''}) + '\n')
        log.write(json.dumps({'hook': 'check-file-size', 'decision': 'deny',
                              'reason': 'ありがとう' * 10}) + '\n')
        log.close()
        row = cost_probe.metrics(path, log.name)
        self.assertEqual(row['deny_count'], 1)
        self.assertEqual(row['deny_bytes'], len(('ありがとう' * 10).encode()))

    def test_missing_hook_log_is_recorded_as_missing_not_zero(self):
        # A lost log is unmeasured, not "no denies": the difference decides
        # whether the run counts toward the injection total at all.
        path = self.write([self.assistant('Read'), self.result()])
        row = cost_probe.metrics(path, '/nonexistent/hook.log')
        self.assertIsNone(row['deny_count'])
        self.assertIsNone(row['deny_bytes'])
        self.assertEqual(row['hooklog'], 'missing')

    def test_direct_condition_has_no_hook_log_by_design(self):
        path = self.write([self.assistant('Read'), self.result()])
        row = cost_probe.metrics(path)
        self.assertIsNone(row['deny_count'])
        self.assertEqual(row['hooklog'], 'not_applicable')

    def test_present_hook_log_is_marked_ok(self):
        path = self.write([self.assistant('Read'), self.result()])
        log = tempfile.NamedTemporaryFile('w', suffix='.hooklog', delete=False,
                                          encoding='utf-8')
        log.close()
        row = cost_probe.metrics(path, log.name)
        self.assertEqual((row['deny_count'], row['deny_bytes']), (0, 0))
        self.assertEqual(row['hooklog'], 'ok')


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 失敗することを確認する**

Run: `cd /home/dev/projects/skills/token-shunt && python3 -B evals/compare/test_cost_probe_metrics.py -v`
Expected: FAIL（`metrics() takes 1 positional argument` / `KeyError: 'skill_loads'`）

- [ ] **Step 3: `metrics` を拡張する**

```python
def metrics(path, hooklog=None):
    turns = child_turns = agent_calls = parent_reads = parent_bash = 0
    skill_loads = 0
```

親ターンのツールループ内に追加する:

```python
                elif name == "Skill":
                    skill_loads += 1
                elif name == "Read":
                    parent_reads += 1
                    args = block.get("input") or {}
                    if str(args.get("file_path", "")).endswith(
                            "skills/bulk-reader/SKILL.md"):
                        skill_loads += 1
```

（既存の `elif name == "Read": parent_reads += 1` を上の形に置き換える。）

deny 集計。**ログ欠測は 0 件ではなく「未計測」として記録する**。0 と混ぜると、
注入バイト数の合計が実際より小さく見え、§9 の累積リスクの検出指標が壊れる。

```python
    # None = not measured. Only an existing log can assert "no denies".
    deny_count = deny_bytes = None
    hooklog_status = "not_applicable" if not hooklog else "missing"
    if hooklog and os.path.exists(hooklog):
        hooklog_status = "ok"
        deny_count = deny_bytes = 0
        with open(hooklog, encoding="utf-8") as fh:
            for line in fh:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("decision") == "deny":
                    deny_count += 1
                    deny_bytes += len((record.get("reason") or "").encode("utf-8"))
```

戻り値の辞書に `"skill_loads": skill_loads, "deny_count": deny_count,
"deny_bytes": deny_bytes, "hooklog": hooklog_status` を足す。
`{"ok": False, "reason": "missing final result"}` の早期 return にも同じ4キーを
足す（`skill_loads` は 0、deny 系は `None`、`hooklog` は判定済みの値）。
`hooklog` が `"ok"` 以外の行は、Task 9 の注入バイト数の集計から除外し、除外件数を
記録する。

- [ ] **Step 4: `run_one` にフックログを渡し、ケースを絞れるようにする**

```python
def run_one(case, cond, fix, tmp, cwd, out_path):
    ...
    env["TOKEN_SHUNT_EVAL_FIXTURES"] = fix
    if cond != "direct":
        env["TOKEN_SHUNT_HOOK_LOG"] = out_path + ".hooklog"
```

`main()`:

```python
def main():
    repeats = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    selected = sys.argv[2:] or CASES
    unknown = [c for c in selected if c not in CASES]
    if unknown:
        sys.exit("unknown case ids: %s" % ", ".join(unknown))
```

以降のループの `for cid in CASES:` を `for cid in selected:` にし、`load_cases()` のフィルタも `selected` を使う。`row.update(metrics(out))` を、条件に応じて渡し分ける:

```python
                hooklog = None if cond == "direct" else out + ".hooklog"
                row.update(metrics(out, hooklog))
```

`direct` はプラグインを読み込まないのでフックログが存在しない。`None` を渡すと
`hooklog="not_applicable"` になり、ログ紛失（`"missing"`）と区別できる。
出力行に `skill=%s deny=%s/%sB(%s)` を足し、最後に `hooklog` の状態を出す。

- [ ] **Step 5: テストが通ることを確認する**

Run: `cd /home/dev/projects/skills/token-shunt && python3 -B evals/compare/test_cost_probe_metrics.py -v`
Expected: PASS（4件）

- [ ] **Step 6: `evals/run.sh` に登録する**

```bash
cd /home/dev/projects/skills/token-shunt
python3 - <<'PY'
from pathlib import Path
p = Path('evals/run.sh')
s = p.read_text(encoding='utf-8')
old = '''python3 -B -m unittest discover -s "$ROOT/evals/compare" -p test_unreadable_and_model.py \\
  && record model-selection-regressions 0 "" || record model-selection-regressions 1 "model selection regression failed"'''
new = old + '''

echo "== cost probe metric checks =="
python3 -B -m unittest discover -s "$ROOT/evals/compare" -p test_cost_probe_metrics.py \\
  && record cost-probe-metrics 0 "" || record cost-probe-metrics 1 "cost probe metric regression failed"'''
assert s.count(old) == 1
p.write_text(s.replace(old, new), encoding='utf-8')
PY
./evals/run.sh 2>&1 | tail -5
```
Expected: 失敗0

- [ ] **Step 7: Commit**

```bash
cd /home/dev/projects/skills/token-shunt
git add evals/compare/cost_probe.py evals/compare/test_cost_probe_metrics.py evals/run.sh
git commit -m "test: measure skill loads and deny injection in the cost probe"
```

---

### Task 9: 実機での小規模比較（3回）と記録、全体再評価の判定

**Files:**
- Create: `reviews/reader-protocol-reduction-2026-09-14.md`

**Interfaces:**
- Consumes: Task 2〜8 のすべて
- Produces: `repeat.sh 3` に進むかどうかの判定

- [ ] **Step 1: fixtures が残っていることを確認する**

```bash
cd /home/dev/projects/skills/token-shunt
ls -d evals/compare/tmp/runs/*/work/fixtures/gen 2>/dev/null | tail -3
```
無ければ先に `./evals/compare/run.sh direct` を1回流して fixtures を作る。

- [ ] **Step 2: reader の3ケースを3条件×3回で実行する**

writer ケース（`auto-large-writer`）は設計 §2 の範囲外なので回さない。

```bash
cd /home/dev/projects/skills/token-shunt
python3 evals/compare/cost_probe.py 3 auto-bulk-facts auto-explicit-multifile auto-one-line \
  2>&1 | tee evals/compare/tmp/cost-probe-postfix.log
```
27実行。`ok=False` の行は中央値の計算から除外し、除外件数を記録する。

- [ ] **Step 3: 料金を対応のある差で集計する**

ケースを混ぜた中央値は取らない。**各周について対象2ケース（`auto-bulk-facts`、
`auto-explicit-multifile`）の合計**を条件ごとに出し、その**周ごとの差
（skill − direct）の中央値**を見る。`auto-one-line` は既存測定で実行間4倍の
ばらつきがあるため、合計に混ぜず別行で報告する。

**欠測があれば3回完了として扱わない。** ある周のある条件で `ok=False` が1件でも
あれば、その周は差を計算せず「不成立」として数え、記録に残す。

```bash
cd /home/dev/projects/skills/token-shunt
python3 - <<'PYEOF'
import json, statistics, glob, os
report = sorted(glob.glob('evals/compare/tmp/cost-probe/*/report.json'),
                key=os.path.getmtime)[-1]
rows = json.load(open(report))['rows']
print('report:', report, 'rows=%d ok=%d' % (len(rows), sum(1 for r in rows if r.get('ok'))))
PAIR = ('auto-bulk-facts', 'auto-explicit-multifile')
CONDS = ('direct', 'bare', 'skill')
reps = sorted({r['rep'] for r in rows})
diffs, complete = [], 0
for rep in reps:
    totals, missing = {}, []
    for cond in CONDS:
        sel = [r for r in rows if r['rep'] == rep and r['cond'] == cond
               and r['case'] in PAIR]
        good = [r for r in sel if r.get('ok') and r.get('cost_usd') is not None]
        if len(good) != len(PAIR):
            missing.append(cond)
            totals[cond] = None
        else:
            totals[cond] = sum(r['cost_usd'] for r in good)
    if missing:
        print('rep%d INCOMPLETE (%s) -> excluded from the median'
              % (rep, ', '.join(missing)))
        continue
    complete += 1
    d = totals['skill'] - totals['direct']
    diffs.append(d)
    print('rep%d direct=%.4f bare=%.4f skill=%.4f  skill-direct=%+.4f'
          % (rep, totals['direct'], totals['bare'], totals['skill'], d))
print('complete reps: %d/%d' % (complete, len(reps)))
if complete == len(reps) and diffs:
    print('median(skill-direct) = %+.4f' % statistics.median(diffs))
else:
    print('median withheld: not all reps completed')
# auto-one-line and the protocol/delegation split, reported separately
for case in ('auto-one-line',):
    for cond in CONDS:
        vals = [r['cost_usd'] for r in rows
                if r['case'] == case and r['cond'] == cond and r.get('ok')]
        print('%-16s %-6s n=%d vals=%s' % (case, cond, len(vals),
                                           [round(v, 4) for v in vals]))
# parent turns, skill loads, deny injection (only measured hook logs)
for cond in CONDS:
    sel = [r for r in rows if r['cond'] == cond and r.get('ok')]
    measured = [r for r in sel if r.get('hooklog') == 'ok']
    print('%-7s turns=%s skill_loads=%s deny=%s bytes=%s (measured %d/%d)'
          % (cond, [r.get('parent_turns') for r in sel],
             [r.get('skill_loads') for r in sel],
             [r.get('deny_count') for r in measured],
             [r.get('deny_bytes') for r in measured], len(measured), len(sel)))
PYEOF
```

- [ ] **Step 4: 契約違反を既存の判定器で数える**

自前の正規表現は使わない。バッククォートで囲まれた省略パスを見逃し、
`unconfirmed:` 行にも一致してしまう。`judge.py` の `confirmed_items` /
`gold_confirmed_ok` は、`confirmed:` 項目の切り出し、引用符・バッククォート付き
パス、行頭パス、`:行番号` の除去まで既に扱っている。

モデルは3点を分けて見る: **未指定（`None` / `"auto"`）が無いこと**、
**初回が haiku であること**、**sonnet が出るのは再試行のときだけであること**。
今回のプローブは `--worker-model haiku` で回すため、正常なら全呼び出しが
haiku になる。

```bash
cd /home/dev/projects/skills/token-shunt
python3 - <<'PYEOF'
import json, os, glob, sys
CMP = 'evals/compare'
sys.path.insert(0, CMP)
import judge

report = sorted(glob.glob(os.path.join(CMP, 'tmp/cost-probe/*/report.json')),
                key=os.path.getmtime)[-1]
root = os.path.dirname(report)
meta = json.load(open(report))
fixtures = os.path.join(root, 'fixtures')
catalog = {c['id']: c for c in json.load(open(os.path.join(CMP, 'cases.json')))['cases']}

def golds(case):
    gf = case.get('gold_file')
    if not gf:
        return []
    with open(os.path.join(fixtures, gf), encoding='utf-8') as fh:
        data = json.load(fh)
    return data if isinstance(data, list) else list(data.values())

for path in sorted(glob.glob(os.path.join(root, 'transcripts', '*.jsonl'))):
    name = os.path.basename(path)
    cid = name.split('.')[0]
    case = dict(catalog[cid], fixture_root=fixtures)
    events = []
    for line in open(path, encoding='utf-8'):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    tr = judge.Transcript(events)
    final = tr.final_text()
    missing = judge.gold_confirmed_ok(final, golds(case), case)
    agents = tr.parent_tool_uses('Agent') + tr.parent_tool_uses('Task')
    requested = [(a.get('input') or {}).get('model') for a in agents]
    resolved = [judge.agent_resolved_models(tr, a) for a in agents]
    problems = []
    if any(m in (None, '', 'auto') for m in requested):
        problems.append('unspecified_or_auto_model')
    if requested and requested[0] != 'haiku':
        problems.append('first_call_not_haiku')
    for i, m in enumerate(requested):
        if m == 'sonnet' and i == 0:
            problems.append('sonnet_without_a_prior_attempt')
    print('%-34s confirmed_items=%d missing_gold=%s requested=%s resolved=%s %s'
          % (name, len(judge.confirmed_items(final)), missing, requested,
             resolved, ','.join(problems) or 'ok'))
PYEOF
```

`missing_gold` が空でない実行が `gold_confirmed` の失敗に相当する。
reader 経路（`auto-*` の reader 3ケース）と、対象外の writer 経路を混ぜずに
数え、記録では別行にする。

- [ ] **Step 5: 記録を書く**

`reviews/reader-protocol-reduction-2026-09-14.md` に次の見出しで書く。

```markdown
# reader プロトコル往復削減の実機比較（2026-09-14）

## 条件
（コミット、実行コマンド、ケース、回数、除外した実行と理由）

## 結果

| 指標 | 変更前 | 今回（中央値） | 各回 | 目標 | 判定 |
|---|---|---|---|---|---|
| 親ターン（読み取りケース） | skill 10.5〜11.5 | | | 5前後（目標値） | |
| Skill 読み込みターン | 毎回1回 | | | 0回（初回定型・正常終了ケース限定） | |
| コスト（読み取り2ケース計、各周の対応差 skill−direct） | skill $0.2986 / direct $0.2492 | | | 差の中央値がマイナス、かつ3周すべて成立 | |
| コスト（`auto-one-line`、別掲） | skill ×2.98 | | | 参考値（合計に混ぜない） | |
| gold_confirmed（パス省略） | 3周で15件 | | | 0件 | |
| モデル指定違反（reader 経路） | 3周で各11件 | | | 0件 | |
| deny 回数 / 注入バイト数 | 未計測 | | | 記録して削減幅と突き合わせ | |

## writer 経路（対象外）
（`auto-large-writer` は今回回していない。既存記録の値を参照として記載し、
本変更の評価には含めないことを明記する）

## 確認できたこと / まだ未確認のこと
（分けて書く）

## 全体再評価に進むか
（進む / 進まない と理由。進まない場合は次に調べること）
```

- [ ] **Step 6: 全体再評価の判定**

設計 §8.3 の条件は「契約を維持したまま料金削減を確認できた場合のみ」。すなわち次を**すべて**満たすとき `repeat.sh 3` に進む。

- **3周すべてが成立している**（どの周のどの条件にも `ok=False` が無い）。欠測があれば3回完了として扱わず、その分を回し直す
- 読み取り2ケース合計の**各周の差（skill − direct）の中央値がマイナス**。ケースを混ぜた中央値では判定しない
- `missing_gold`（パス省略）0件、reader 経路のモデル指定違反0件（未指定・`auto`・初回 sonnet のいずれも0）
- 初回の定型・正常終了ケースで Skill 読み込み0回
- deny 回数と注入バイト数が `hooklog="ok"` の実行で計測できている（未計測の実行は集計から除外し、除外件数を記録する）

満たさない項目があれば `repeat.sh 3` に進まず、Step 5 の「次に調べること」に原因調査の当たりを書いて止める。

- [ ] **Step 7: 条件を満たした場合のみ全体再評価を回す**

```bash
cd /home/dev/projects/skills/token-shunt
./evals/compare/repeat.sh 3
```
結果は同じ記録ファイルに追記し、リリースゲート（`suite_cost_usd` の `regression` / `release_gate`）の再判定を書く。

- [ ] **Step 8: Commit**

```bash
cd /home/dev/projects/skills/token-shunt
git add reviews/reader-protocol-reduction-2026-09-14.md
git commit -m "docs: record the reader protocol reduction live comparison"
```
