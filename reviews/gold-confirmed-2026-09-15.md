# `gold_confirmed` の原因確認と修正（2026-09-15、追加課金測定なし）

`reviews/residual-two-2026-09-15.md` §4.1 の未解決項目。
既存トランスクリプトの再解析のみで原因を特定し、最小修正を適用した。

## 1. 照合対象

`specs/<case>.<mode>.json`（各実行が実際に判定された置換済み spec）を
入力とし、`expect.<mode>.gold_confirmed` が立つ実行だけを対象にした。
`cases.json` ではなく実行ごとの spec を使うのは、`fixture_root` が
実行固有であり、期待パス集合を再現するには実物が要るため。

**陳腐化した spec の除外。** 対象132実行のうち47実行は、`gold_paths` が
basename（`user.rb`）なのに `fixtures` が入れ子（`rails/app/models/user.rb`）
という古い spec で判定されていた。この組み合わせでは期待パスが
`<fixture_root>/user.rb` となり実在しないため、親が正しい絶対パスを
書いても必ず失敗する。これは**仕様側の陳腐化であって親の非適合ではない**
ので、以下の集計から外した。残り85実行が現行 spec による判定である。

## 2. 三点照合の結果

| ケース | n | 子の `confirmed:`（うち絶対パス付き） | 親の `confirmed:`（同） | pass |
|---|---|---|---|---|
| `auto-explicit-multifile` | 57 | 213（200） | 24（3） | 1 |
| `compare-explicit-multifile` | 21 | 76（74） | 56（17） | 5 |
| `reader-batch-evidence` | 7 | 70（70） | 56（42） | 5 |

子の返答は、Agent の `tool_result` ではなく `parent_tool_use_id` を持つ
サブエージェント側 assistant メッセージから取った（非同期 Agent の
`tool_result` は起動メタデータしか含まない）。

### 2.1 子の返答には引用元の絶対パスがあるか → **ある**

359項目中344（96%）が `confirmed: <絶対パス> — <事実>` 形式。
子が項目を1つも出さなかったのは 85実行中3件のみ。
子側契約（`plugin/agents/bulk-reader.md:56`）は守られている。

### 2.2 親が落としているのか、契約が届いていないのか → **親が落としている**

85実行中**69実行**で「子は絶対パス付き項目を返したのに、親の最終回答には
絶対パス付き項目がゼロ」。落とし方は2種類ある。

| 形 | 内訳 |
|---|---|
| 親が `confirmed:` 項目自体を書かない | `auto-explicit-multifile` 45/57 |
| 項目は書くが `.../app/models/user.rb` と省略する | `compare-explicit-multifile` 16/21 |

### 2.3 判定器の要求形式と応答契約は一致しているか → **一致していない**

親に保持を義務づける文は2箇所しかなく、どちらも
3パス単一起動の `*-explicit-multifile` には届かない。

| 文 | 位置 | 届かない理由 |
|---|---|---|
| `In your final answer keep each confirmed bullet with its full absolute path, unabbreviated.` | `plugin/hooks/reader-call-contract:15` | hook deny を受けるか、SKILL.md の「Explicit delegation」節を開いた場合のみ親の文脈に入る。親が最初から委譲すれば deny は起きない |
| `Preserve one `confirmed: <path> — <fact>` item per corroborated fact in the final answer` | SKILL.md §2 **Inter-batch evidence contract** 段落内 | 「4+ paths を3件ずつに分割した場合の統合規則」の段落。3パス単一起動には適用されない読みになる |

description には保持要求が一切なかった。
すなわち §2.1.1・worker-model・content search・検索前メタデータ確認と
**同型の到達性欠陥**である。

**裏付け。** プロンプト自身が `confirmed: items that name matching paths` と
要求する `reader-batch-evidence` は 5/7 合格、要求しない2ケースは
6/78 合格。要求が親の文脈にあるかどうかで結果が分かれている。

**限界。** 契約文字列がトランスクリプトに現れた実行に限っても合格率は
上がらなかった（`auto` 1/23、`compare` 2/9）。`head_limit` と同じく、
**規則への到達は遵守を意味しない**。今回の修正は到達性を直すもので、
行動が変わるかは別問題である。

## 3. 適用した修正（SKILL.md 6996 → 6972 B）

保持義務を、分割時にしか適用されない §2 の段落から、常に親の文脈にある
description へ移した。

```
description:
+ In the final answer keep one `confirmed: <absolute path> — <fact>`
+ bullet per corroborated fact, path unabbreviated.

§2 Inter-batch evidence contract:
- Preserve one `confirmed: <path> — <fact>` item per corroborated fact
- in the final answer; don't drop evidence labels when summarizing.
```

本文に併記しない。description は本文が読み込まれている間も文脈にあるため、
両方に書けば同じ規則を二重に支払うことになる。結果として **24 B 減**
（テスト上限 7000 B は変更なし）。

## 4. 検証（すべて静的・オフライン。課金を伴う動作測定は未実施）

| 検査 | 結果 |
|---|---|
| `./evals/run.sh` | 125 pass / 0 fail |
| 契約テスト（`evals/test_reader_call_contract.py`） | 55 tests OK（3 skipped）。新規1件 |
| `evals/compare` ユニットテスト | 272 tests OK |
| `judge.py --selftest` | all checks passed |
| 既存トランスクリプト再解析 | 132実行（うち現行 spec 85件）。新規実行なし |

確認の種類の区別は `reviews/residual-two-2026-09-15.md` §5 に従う。
`evals/compare` の 272 件は判定器・ランナーのユニットテストであり、
親の振る舞いの確認ではない。

新規テスト
`test_evidence_retention_is_stated_where_the_parent_can_see_it` は、
description が保持義務を持つことと、本文が同じ規則を重複して持たないことを
同時に固定する。

## 5. 残る未検証

- 文言変更によって親が実際に絶対パス付き `confirmed:` 項目を残すように
  なるかは**未測定**。確認には課金を伴う動作測定が要る。
- 旧 spec による47実行の失敗は、今回の修正とは無関係の陳腐化であり、
  再判定しても意味がない（期待パスが実在しない）。
