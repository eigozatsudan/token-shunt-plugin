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

### 2.1 子の返答には引用元の絶対パスがあるか → **おおむねある**

359項目中344（96%）が `confirmed: <絶対パス> — <事実>` 形式。
子が項目を1つも出さなかったのは 85実行中3件。
子側契約（`plugin/agents/bulk-reader.md:56`）の遵守率は高いが、
**完全遵守ではない**（15項目がパスを欠く）。子側の残り15項目は
今回の修正対象外であり、未処理のまま残る。

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
したがって**親の保持義務には到達性の欠陥がある**。今回修正したのは
この欠陥である。

**限定。** 「到達性の欠陥があり、修正した」以上のことは言えない。
契約文字列がトランスクリプトに現れた実行に限っても合格率は上がって
おらず（`auto` 1/23、`compare` 2/9）、**契約が見えていても失敗して
いる**。したがって到達性だけが失敗の原因とは確定できない。
プロンプト自身が `confirmed: items that name matching paths` と要求する
`reader-batch-evidence` が 5/7、要求しない2ケースが 6/78 という差は
到達性の寄与を示唆するが、寄与の大きさも、他の要因の有無も未確定である。
`head_limit` と同じく、**規則への到達は遵守を意味しない**。

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

---

# 追補（2026-09-15）— 転記方式への置換と、短縮箇所の照合

## 6. A案の適用（`61d78ed`、短縮の是正は後続コミット）

description の文言を、結果の要求から**転記手順**へ置き換えた。

```
- In the final answer keep one `confirmed: <absolute path> — <fact>` bullet
- per corroborated fact, path unabbreviated.
+ Copy each worker `confirmed:` line into the final answer verbatim, one per
+ line; collapse only identical lines; a line whose path is not absolute
+ keeps its text but becomes `unconfirmed:`.
```

`pathless` ではなく `path is not absolute` としたのは、実測
`run.qmvXaj0z/sonnet` の失敗が**相対パス風の記述**であって欠落では
なかったため。相対・省略も同じ側に落ちる必要がある。

## 7. 短縮4箇所の照合（変更前後）

7000 B に収めるために短縮した箇所を、**適用条件・禁止事項・再呼び出し
手順が残っているか**で照合した。テストが固定していないことは、
意味が変わらない根拠にはならないので、1件ずつ文面で確認した。

| # | 変更前 → 変更後 | 種別 | 判定 |
|---|---|---|---|
| 1 | `the whole file when the whole file is needed` → `the whole file when all of it is needed` | 適用条件 | **残る**。`it` の先行詞は直前の `the whole file`。ただし明示から代名詞になり、精度はわずかに下がった |
| 2 | `— follow the deny and delegate.` → `— follow it and delegate.` | 手順 | **残る**。`it` は `the deny` とも `the call spec` とも読めるが、どちらの読みでも動作は同じ（deny の指示どおりに委譲する） |
| 3 | `and retry or escalation decisions after a partial.` → `and retry or escalation after partial.` | 参照条件の列挙 | **残る**。「partial 後の再試行・エスカレーションでこのスキルを参照する」という列挙項目としての意味は同じ。`partial` は本文でも冠詞なしの名詞として使われている |
| 4 | `never use it to fetch the answer, nor to discover a range and then claim the known-range exception.` | 禁止事項 | **残る**（下記） |
| 5 | `stay in the parent, and position-only search` → `stay in the parent; position-only search` | 接続のみ | **変化なし**。独立した2節を接続詞からセミコロンに変えただけ |
| 6 | `Re-ask in a NEW invocation, re-sending the same explicit paths.` → `Re-ask in a NEW invocation with the same explicit paths.` | 再呼び出し手順 | **残る**。「同じ明示パスを伴う新規起動」であり、直後の `No resume, no answer index; the re-input is paid.` が再送のコストを明示している |
| 7 | `don't run metadata commands just to get a size.` → `don't run metadata commands for a size.` | 禁止事項 | **意味が変わった → 復元した** |

### 7.1 #4 の詳細（禁止の範囲）

変更後は `never use it to fetch the answer or to discover a range and
claim the known-range exception.`。`never A or B` は否定が両方に及ぶ
ため、2つの禁止はともに残る。`and then claim` から `then` が落ちたが、
`and` が両方の成立を要求する点は変わらないので、
「範囲を発見してから既知レンジ例外を主張する」形は依然として禁止される。
`nor` に比べて係り方の読み違いの余地はわずかに増えた。

### 7.2 #7 は復元した（+8 B）

`just` は「サイズを得ることだけを目的に」という**範囲の限定**を担って
いた。これを落とすと「サイズのためにメタデータ命令を実行するな」という
無条件の禁止に読め、description 冒頭の
`Judge size from metadata (stat/wc -c) before the first Read or content
search` と正面から衝突する。**条件を落とさない**という方針に反するので
復元した。

復元の8 B は、意味を変えない2箇所で相殺した。

- `metadata (stat / wc -c)` → `metadata (stat/wc -c)`（−2）。本文側は
  既に `` `stat`/`wc -c` `` と空白なしで書いており、表記を揃えただけ。
- `after a partial.` → `after partial.`（−2）。#3 のとおり。

SKILL.md は **6999 B**（上限7000 B、変更なし）。

## 8. 検証（すべて静的・オフライン）

| 検査 | 結果 |
|---|---|
| `./evals/run.sh` | 125 pass / 0 fail |
| 契約テスト | 55 tests OK（skipped 3。理由は §8.1） |
| `evals/compare` | 272 tests OK |
| `judge.py --selftest` | all checks passed |

### 8.1 skip 3件の理由

3件とも `BashRenderedDenyTests`（`RenderedDenyTests` の派生）で、
**親クラスの Read 形のケースを Bash 形の文脈で無効化している**もの。
未検証の項目が残っているわけではない。

| テスト | 理由 |
|---|---|
| `test_bad_limit_on_an_oversized_file_carries_the_contract` | `Read-only case`。`limit` 引数は Bash 経路に存在しない |
| `test_oversized_range_carries_the_contract` | `Read-only case`。範囲指定 Read は Bash 経路に存在しない |
| `test_newline_in_filename_is_sanitized_not_injected` | `Read-only case; see the Bash-shaped variant below`。**同じ検査が Bash 形の別テストで実施されている** |

動作上の効果（転記手順で親が実際に `confirmed:` 行を写すか）は
**未検証**。確認には課金を伴う動作測定が要る。
