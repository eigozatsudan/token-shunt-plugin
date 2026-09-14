# 実機再検証（2026-09-14 03:05–03:47）

対象: `evals/compare/tmp/repeats/repeat.LrC2RSGP/run-1.json`（transcript は
`evals/compare/tmp/runs/run.mnVnW1FU`）。コードは HEAD b66c13f に、別ハーネス
（Codex）のB・D修正とC強制フック、および本セッションの `check-jq` 修正を加えた
未コミットの作業ツリー。`repeat.sh 1` で全30ケース75実行を1周した。

前回（`run.NckO7koy`）はスイートBの大半が利用上限で未実行だったため、Bの全ケース
が走ったのは今回が初めてである。末尾8実行は新たな8am上限に当たり未測定。

## 集計

| 項目 | 値 |
|---|---|
| pass / fail / runs | 18 / 60 / 75 |
| `selected_run_valid` | false |
| `release_eligible` | false |
| 失敗の内訳（FAIL行は1実行1件のみ表示） | `foreign_hooks` 49、`run`（利用上限）8、`accuracy` 3 |
| `scripts/doctor.sh` | exit 0。plugin と両 agent の登録、haiku→`claude-haiku-4-5-20251001` / sonnet→`claude-sonnet-5` の解決一致を確認 |

`doctor.sh` の haiku プローブで `child final message carried no status/stop_reason
line` が出た。前回は契約行を報告できていたので、単発プローブでの挙動差として記録
する。

## 1. `foreign_hooks` 49実行（最優先）

```
FAIL compare-bulk-facts/haiku: foreign_hooks: PostToolUse:Read,PostToolUseFailure:Read,...
```

`check-reader-contract` は PostToolUse と PostToolUseFailure に登録する
（[reader-contract-and-evaluation-2026-09-13.md](reader-contract-and-evaluation-2026-09-13.md)）
が、設計 §13 の隔離判定は自プラグインのフックとして `PreToolUse:Read` /
`PreToolUse:Bash` / `SessionStart:startup` のみを許可する。これは CLI 2.1.x の
`hook_response.hook_name` がマッチャ名しか返さずコマンドパスで識別できない制約への
対処であり、許可マッチャ以外の hook_event はすべて外来として fail になる。
`PreToolUse:Agent` は許可済みだが PostToolUse 系 2 つが漏れている。

判定器と設計 §13 の許可リストに 2 つを追加すれば解消する。

## 2. 強制フックの deny を子の違反として計上している

`check-reader-contract` は意図どおり動作している。`reader-bounds/auto` の実証跡:

```
Read offset=351 limit=169 → 拒否（Read ツールのトークン上限）
Read offset=400 limit=119 → token-shunt: Read must start at offset=351 with a positive limit.
Read offset=351 limit=50  → token-shunt: Retry at offset=351 with limit=84 (floor half).
Read offset=351 limit=84  → 成功（351–434）
```

飛び越しも誤った半減値も遮断され、子は最終的に契約どおり読んでいる。しかし
`routing_checks.py:114` は「拒否された飛び越しも契約違反」として**試行そのもの**を
数えるため、強制が成功した実行がそろって不合格になる。6 Read 予算の判定も、本文を
1 バイトも返さない deny 試行を消費として数える（フック側も設計として deny を予算
消費に数えている）。

この相互作用により、前回合格していた `reader-bounds` `retry-policy` が新たに失敗した。
`reader-batch-ambiguous/auto` `compare-explicit-multifile` `compare-one-line/haiku`
の `child_reads_once` / `child_extra_read` も同じ構図である。

判定器はネイティブ拒否（`File content ... exceeds maximum allowed tokens`）と
token-shunt 自身の deny を区別し、後者は「違反」ではなく「強制の成功」として扱う
必要がある。予算計上についても、内容を返さない deny を消費に数えるかどうかは
フック側と判定器で同じ定義に揃える。

## 3. 前回16件の解消状況

**解消 7件**

| ケース | 前回の失敗 | 解消理由 |
|---|---|---|
| compare-bulk-facts/sonnet, /auto | `child_reads_once` | 分割手順の遵守 |
| compare-hook-deny-route/auto | `deny_bypass` | `awk 'END{print NR}'` の誤検知を除去 |
| auto-bulk-facts/haiku | `deny_bypass` | 同上 |
| auto-bulk-facts/direct | `parent_reads` | direct プロンプトで Read ツール使用を明記 |
| compare-code-writer-ok/auto | `child_msg_cap` | `agentId` / `<usage>` トレーラを字数から除外 |
| writer-verification-levels/auto | `verification_control` | 装飾付きステータスセルを許容 |

**未解消 9件**（うち数件は原因が変化）

- `compare-bulk-facts/haiku`、`compare-explicit-multifile` haiku/auto、
  `reader-batch-ambiguous/auto` — 主因は §2 の deny 計上
- `compare-one-line` 3モード — 子は `unread line 1` 付きのプレーン行を出力する
  ようになったが、sonnet が `confirmed: none — unable to retrieve payload_sha value.`
  と書いたため、`unreadable_line_partial()` の「`confirmed:` 行があってはならない」
  規則に抵触して accuracy 免除が外れる。空の confirmed ラベルを事実主張と見なさない
  方針（Codex の B 修正）が、この否定形の行までは覆っていない
- `compare-edit-dense-lines/auto` — `child_status`

## 4. スイートBで新たに判明した問題

- **auto-edit-grep-location**: 4モード全部（direct を含む）で `accuracy` +
  `edit_flow` 失敗。`edit_flow: Edit lacks completed target-identifying Grep ->
  original targeted Read evidence`。direct でも落ちるためプラグインの問題ではなく、
  Grep→原本 targeted Read→Edit の証跡列をモデルが踏まないケース設計の問題
- **auto-large-writer**: `child_msg_cap` 1042 / 1910 字 > 800（1910 字は明確な実違反）、
  `child_ref_before_write`（参照 Read 前に Write）
- **auto-routing-boundary-49/50-lines-writer**: `disk` — 生成物が構文・行数・
  モジュール要件を満たさない
- **auto-routing-boundary-50-lines**: direct / auto で `accuracy`（`def task_fifty` 欠落）
- **auto-edit-grep-ambiguous/sonnet**: 曖昧性を報告すべきところ該当語なし

## 5. トークン・費用

親隔離（UTF-8 バイト）は測定できた全ケースで合格。

```
auto-bulk-facts:        delegate=[16760, 17024, 16984] direct=19864 fixture=65669
auto-explicit-multifile: delegate=[18978, 20318, 25132] direct=25339 fixture=67180
auto-one-line:          delegate=[16104, 15594, 17272] direct=42839 fixture=69886
```

一方 `parent_token_deltas` は測定できた4ケースすべてで**委譲のほうが親 I/O トークンが
多い**。

| ケース | `delta_input` | `delta_output` | `delta_io` |
|---|---|---|---|
| auto-bulk-facts | +69,884 | +1,816 | +71,700 |
| auto-one-line | +119,722 | +1,714 | +121,436 |
| auto-explicit-multifile | +21,247 | +2,489 | +23,736 |
| auto-large-writer | +148,847 | +639 | +149,486 |

本文バイトの隔離は効いているが、トークン削減は依然として実測されていない。
`suite_cost_usd.total` は末尾8実行が利用上限で落ちたため未確定。

## 6. 本セッションでの修正

`plugin/hooks/check-jq` が python3 不在で早期 return し、jq 欠落を報告しなくなって
いた（`evals/run.sh` の `sessionstart-jq-missing` が失敗）。欠落依存を全列挙する
実装に変更し、回帰テスト `sessionstart-deps-missing` / `sessionstart-python-missing`
を追加、設計 §7 を実装に合わせた。`evals/run.sh` は pass 116 / fail 0、
`evals/compare` の単体は 212 tests OK。

## 次の一手

1. 設計 §13 と判定器の許可マッチャに `PostToolUse:Read` / `PostToolUseFailure:Read`
   を追加する（49実行）
2. 判定器で token-shunt 由来の deny をネイティブ拒否と分離し、強制の成功として扱う。
   予算計上の定義をフックと judge で揃える（数件〜十数実行）
3. `confirmed: none` 形の否定行を、エージェント側で禁止するか判定器側で許容するかを
   決める（compare-one-line 3実行）
4. 1〜3 の後に再度 `repeat.sh 1` を回し、残る実品質問題（§4）を切り分ける
