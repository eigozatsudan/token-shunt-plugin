# 実機再実行（2026-09-14 13:18–13:57）

対象: `evals/compare/tmp/repeats/repeat.zRRKeoe5/run-1.json`（transcript は
`evals/compare/tmp/runs/run.4PslHQBQ`）。コードは **HEAD 4c2fa1e**、作業ツリーは
クリーン。`repeat.sh 1` で全30ケース75実行を1周した。

前回（`repeat.LrC2RSGP` / [live-rerun-2026-09-14.md](live-rerun-2026-09-14.md)）は
末尾8実行が利用上限で未測定だったが、今回は**75実行すべてが測定できた**。

## 集計

| 項目 | 値 |
|---|---|
| 判定（aggregate） | pass 39 / fail 36 / runs 75 |
| `selected_run_valid` | false |
| `release_eligible` | false |
| `errors` | なし |
| 利用上限による未実行 | 0（前回8） |
| `foreign_hooks` | 0（前回49） |
| `scripts/doctor.sh` | exit 0。plugin と両 agent の登録、haiku→`claude-haiku-4-5-20251001` / sonnet→`claude-sonnet-5` の解決一致を確認 |

前回 doctor の haiku プローブで出ていた `child final message carried no
status/stop_reason line` は再現せず、契約行（`status: complete | stop_reason:
requested facts retrieved`）を報告した。単発プローブの揺れだった可能性が高い。

## 1. 前回の「次の一手」の消化状況

| # | 前回の課題 | 状況 |
|---|---|---|
| 1 | 許可マッチャに `PostToolUse:Read` / `PostToolUseFailure:Read` を追加 | **解消**。`foreign_hooks` 49 → 0 |
| 2 | token-shunt 由来の deny をネイティブ拒否と分離し強制の成功として扱う | **解消**。`reader-bounds` `retry-policy` `compare-hook-deny-route` `auto-known-range` はいずれも pass |
| 3 | `confirmed: none` 形の否定行の扱い | **表面上は解消**。`compare-one-line` は当該理由では落ちていない（別要因で失敗、§3） |

## 2. 失敗の内訳（理由コード、延べ）

```
13 verification_execution   8 isolation        7 gold_confirmed   6 child_status
 6 child_reads_once         4 accuracy         3 deny_bypass      3 agent_type
 3 agent_calls              2 single_invocation 2 parent_reads    2 edit_flow
 2 child_msg_cap            2 child_format     2 batch_evidence
 1 parent_no_full_read      1 parent_bash      1 no_parent_write
 1 deny_route               1 child_ref_before_write
```

### 2.1 `verification_execution` 13件（最多）

writer 系で、報告前に親が検証コマンドを実行した証跡がない。

- `auto-routing-boundary-49-lines-writer` は **4モード全滅**（direct 含む）。
  `w49.py lacks successful parent py_compile before report`
- `auto-routing-boundary-50-lines-writer` は direct / auto
- `writer-verification-levels/auto` 単独で7ファイル分
  （`vl_config.json` `vl_notes.md` `vl_notes.yaml` `vl_req.json` と
  `fixtures/gen/verify/control_*`）

direct でも落ちるものが含まれるため、プラグインの欠陥ではなく**ケース設計または
プロンプトの検証要求がモデルに踏ませられていない**問題として扱う。

### 2.2 `gold_confirmed` 7件

`compare-explicit-multifile`（haiku/sonnet/auto）、`auto-explicit-multifile`
（haiku/sonnet/auto）、`reader-batch-evidence/auto` が同一文言で失敗する。

```
gold not in confirmed: + matching path: Notifiable, after_create, WelcomeEmailJob
```

3ケース×複数モードで文言が完全に一致するため、gold 側の期待表記と子の出力表記の
契約ずれが疑われる。個別のモデル揺れではない。

### 2.3 `child_status` 6件

`compare-one-line/auto` `compare-code-writer-ok/auto` `compare-code-writer-no-ref/auto`
`writer-bounds/auto` `writer-verification-levels/auto` `auto-large-writer/auto` で
`worker <tool_use_id> lacks explicit status and stop_reason`。doctor の単発プローブ
では契約行が出ているので、スキル側の指示がケース本番で徹底されていない。

### 2.4 ルーティング不発 `agent_type` / `agent_calls` 各3件

`auto-one-line/sonnet`、`auto-routing-boundary-16k-plus/auto`、
`auto-routing-boundary-50-lines-writer/auto` で Agent 呼び出しが **0**
（`saw []`）。`16k-plus` では `parent_no_full_read` も付き、親が本体を全文 Read
できてしまっている。`50-lines-writer/auto` では `no_parent_write`（親が Write を実行）。
境界ケースで委譲そのものが発火していないため、優先度は高い。

### 2.5 `deny_bypass` 3件

- `auto-explicit-multifile/sonnet`、`auto-routing-boundary-known-range-deny/auto` —
  親が **Bash で本文を回収**
- `auto-explicit-multifile/auto` — 拒否対象パス `app/models/user.rb` の親 Read が成功

`known-range-deny/auto` は `deny_route`（対象 Read に対応する token-shunt の deny と
失敗結果が reader Agent の前に無い）も併発している。

### 2.6 その他

- `auto-large-writer`: `child_msg_cap` 1266 / 936 字 > 800、`child_format`、
  sonnet で `parent_bash`（`python3 -m unittest large_test` の実行証跡なし）と
  `child_ref_before_write`
- `auto-edit-grep-location`: direct / sonnet で `edit_flow`（Grep→原本 targeted
  Read→Edit の列を踏まない）。前回同様 direct でも落ちる
- `auto-routing-boundary-50-lines`: direct / auto で `accuracy`（`def task_fifty` 欠落）
- `compare-edit-dense-lines/auto`: `accuracy`（`EM-9z8x7` 欠落）
- `reader-batch-ambiguous/auto`: `batch_evidence`（曖昧な TOKEN 関係を confirmed に
  昇格させている）

## 3. `isolation` 8件と direct 側の連鎖失敗

`compare-one-line` と `auto-one-line` の全4モードが `isolation` で落ちた。

```
compare-one-line: delegate=[15544, 15372, 15345] direct=706   fixture=69886
auto-one-line:    delegate=[16273, 16037, 1066]  direct=1084  fixture=69886
```

判定は `delegate_lt_direct_and_fixture`（`judge.py:2094`）で、委譲側は fixture の
69,886 バイトを大きく下回っている（隔離自体は効いている）。落ちた原因は
**direct 側のベースラインが崩れたこと**にある。両ケースとも direct モードが
`parent_reads: no successful parent Read of .../gen/oneline.json` で失敗しており、
親が本文を読まなかったため `direct` が 706 / 1084 バイトまで縮んだ。前回は
`direct=42839` で合格していた。

つまりこの8件は「隔離の退行」ではなく、**direct 実行が対象ファイルを読まなかった
ことによる比較基準の消失**である。一方 `auto-one-line/auto` には
`accuracy: final answer missing: sha256:...` もあり、こちらは実品質の失敗。

## 4. コスト・トークン（4大ケース、単発）

`suite_cost_usd.evidence_complete: true` / `all_modes_evidence_complete: true`
（前回は末尾8実行の欠落で未確定だった総計が、今回は全モード揃った）。

| モード | 合計 USD |
|---|---|
| direct | 0.3006 |
| haiku | 0.5930 |
| sonnet | 0.6637 |
| auto | 0.5608 |

- `auto - direct` = **+$0.2602**、`regression: true`、`release_gate: false`
- `auto - sonnet` = **-$0.1029**（sonnet 常用よりは安いが、direct には負ける）

親トークン I/O 差分は測定4ケースすべてで委譲のほうが多い。

| ケース | `delta_input` | `delta_output` | `delta_io` |
|---|---|---|---|
| auto-bulk-facts | +67,344 | +1,380 | +68,724 |
| auto-one-line | +80,233 | +1,234 | +81,467 |
| auto-explicit-multifile | +267,406 | +2,501 | +269,907 |
| auto-large-writer | +76,069 | +400 | +76,469 |

前回と比べ `auto-explicit-multifile` が +23,736 → +269,907 と大きく悪化し、
`auto-one-line` は +121,436 → +81,467、`auto-large-writer` は +149,486 → +76,469 と
改善した。単発測定のためばらつきが大きく、**リリース判断には反復測定の中央値が要る**。

本文バイトの隔離は効いているが、**トークン・料金の削減は今回も観測されていない**。

## 5. 付随して見つかった計数のずれ

`run.sh` の最終行は `done: pass=45 fail=33 runs=75` を出すが、45+33=78 で実行数と
合わない。正は `last-run.json` の **pass 39 / fail 36**。

原因は2つ:

1. `record()`（`run.sh:23`）が実行以外のプローブ3件（`probe-load`
   `probe-isolation` `plugin-validate`）も PASS に加算する
2. ケース単位の `isolation` 判定は judge のアグリゲート段で全モードを fail に
   書き換える（`judge.py:2106-2109`）ため、run.sh の逐次計上には反映されない。
   今回該当したのは `compare-one-line/haiku` `compare-one-line/sonnet`
   `auto-one-line/haiku` の3実行（他は別理由で run.sh 側も fail 計上済み）

39 + 3（プローブ）+ 3（アグリゲート後付け fail）= 45 で数字が合う。集計は常に
`last-run.json` を正とし、`done:` 行は参考値に留めるか、プローブを別枠で表示すべき。

## 次の一手

1. **ルーティング不発**（`auto-one-line/sonnet`、`16k-plus/auto`、
   `50-lines-writer/auto`）— 委譲が起きていない以上、本製品の目的に直結する。
   transcript で PreToolUse の判定とスキル誘導を確認する
2. **`gold_confirmed` の表記契約**（7実行）— gold と子出力のどちらを直すか決める。
   3ケース共通の文言なので単一修正で消える見込み
3. **`verification_execution`**（13実行）— direct でも落ちるため、ケースの検証要求を
   プロンプト側で踏ませるか、判定条件を実態に合わせるかを決める
4. **`compare-one-line` / `auto-one-line` の direct 実行**が対象を読まない件 — これが
   直れば `isolation` 8件は自然に解消する見込み
5. **`deny_bypass`**（3実行）— 親の Bash 経路と拒否パス Read の取りこぼし。フック側の
   実問題の可能性があり、要 transcript 確認
6. 1〜5 の後に `repeat.sh` を**複数周**回し、コスト・トークンの中央値でリリース可否を
   判断する（現状 `regression: true`）
