# 保留していた動作確認（2026-09-15、課金測定あり）

`reviews/residual-two-2026-09-15.md` §4.2 と
`reviews/gold-confirmed-2026-09-15.md` §5 の動作検証待ち項目を、
5ケース×3周でまとめて実測した。

## 1. 実行条件

| 項目 | 値 |
|---|---|
| 固定コミット | `f866711` |
| 実行対象 | `auto-explicit-multifile` / `compare-explicit-multifile` / `auto-edit-grep-location` / `auto-small-files-four` / `compare-edit-dense-lines` |
| モード数 | 4 + 4 + 4 + 2 + 1 = 15／周、3周で45実行 |
| 実行ディレクトリ | `run.9drN4ts4` / `run.qmvXaj0z` / `run.W7zG2Vat` |
| 実測費用 | **$4.68**（$1.56 / $1.54 / $1.58） |

### 1.1 実行前確認

- 5ケースすべてが現行 `cases.json` に存在。`fixtures` と `gold_paths` の
  期待パスはすべて実在を確認した。
- HEAD の `cases.json` は `gold_paths` が basename のままだった。これは
  本測定の主対象そのものなので、その差分だけを選択的にコミットしてから
  実行した（`f866711`）。

### 1.2 固定の限界（重要）

`evals/compare/run.sh` は `--plugin-dir $ROOT/plugin` で**作業ツリーの
plugin を読み込む**。作業ツリーには測定に影響する未コミット変更が残る
（`plugin/hooks/check-jq`、`plugin/hooks/check-reader-contract`、
`plugin/skills/code-writer/SKILL.md`、`plugin/agents/code-writer.md`、
`evals/compare/run.sh`、`cases.json` の2ケース分のプロンプト改訂）。
したがって実行されたのは HEAD ではなく **`f866711` + 保存済み差分**
（sha256 `65f793b844b91d26b9a00be675bc239d72cda7de2031fee4ccf1e46deb5cd3e1`、
60748 B）である。`token-shunt.zip` は実行経路に入らないため無関係。

古い spec（`gold_paths` が basename）で判定された47実行は、期待パスが
実在せず親が何を書いても失敗するため、以下の比較に含めない。

## 2. 確認項目ごとの成立回数

総合合否は 45実行中 **30 pass / 15 fail**。ただし総合合否は
「どの契約が成立したか」を隠すので、項目別に数える。

| ケース | 確認項目 | 母数の内訳 | 成立 | 変更前 |
|---|---|---|---|---|
| `auto-explicit-multifile` | `gold_confirmed`（絶対パス付き項目の保持） | 委譲3モード（haiku/sonnet/auto）×3周 = 9 | **0 / 9**（haiku 0/3・sonnet 0/3・auto 0/3） | 1 / 57 |
| | `agent_type`（委譲先） | 同上 = 9 | 9 / 9 | — |
| | `single_invocation`（1起動3パス） | 同上 = 9 | 9 / 9 | — |
| | `deny_bypass` | 同上 = 9 | 9 / 9 | — |
| | `requested_model` が具象（`auto` を渡さない） | 同上 = 9 | 9 / 9（haiku×6, sonnet×3） | — |
| `compare-explicit-multifile` | `gold_confirmed`（絶対パスの省略解消） | 委譲3モード×3周 = 9 | **6 / 9**（haiku 2/3・sonnet 1/3・auto 3/3） | 5 / 21 |
| `auto-edit-grep-location` | content search 前のメタデータ確認 | 委譲3モード×3周 = 9（`direct` はプラグイン非ロードのため対象外、別に 0/3） | **0 / 9**（haiku 0/3・sonnet 0/3・auto 0/3） | 0 / 9 |
| | `edit_flow`（§11.6 編集契約） | 全4モード（direct 含む）×3周 = 12 | 12 / 12 | — |
| `auto-small-files-four` | `agent_zero`（不要な委譲なし） | 2モード（direct/auto）×3周 = 6 | **6 / 6**（direct 3/3・auto 3/3） | 未測定 |
| | `parent_reads`（4件を親が読む） | 同上 = 6 | 6 / 6 | 未測定 |
| `compare-edit-dense-lines` | `position_grep_form`（各 content Grep の形式） | 1モード（auto）×3周 = 3 | **0 / 3** | 0 / 24 |

母数が 9・12・3・6 と揃わないのは、ケースごとに設定されたモード数と、
検査の適用条件が違うためである。`gold_confirmed` は `direct`（委譲なし）
には課されないので 9、`edit_flow` は `direct` にも課されるので 12、
`compare-edit-dense-lines` は `auto` のみの1モードなので 3、
`auto-small-files-four` は `direct`/`auto` の2モードなので 6 になる。

「変更前」列は `reviews/gold-confirmed-2026-09-15.md` §2 および
`reviews/head-limit-consistency-2026-09-15.md` の既存実測の再解析値。
周回数が違うため割合の比較であり、有意差の検定ではない。

## 3. 項目別の所見

### 3.1 `auto-explicit-multifile` — 解消せず（0 / 9）

3周9実行すべてで、親は `confirmed:` 項目を**1件も書かなかった**
（NO-ITEM 9/9）。一方で子は36項目を返し、**全36項目が絶対パス付き**
だった。落としているのは依然として親である。

description への移設は**行動を変えなかった**。補助的な観測:

| 観測 | 値 |
|---|---|
| 親が skill を開いた | 3 / 9 |
| `reader-call-contract` の文言が文脈に入った | 1 / 9 |

skill を開いた3実行でも NO-ITEM だった。**規則が見えていても書かない**
という §1.2 の限定が、今回の実測でも再現している。

委譲とモデル指定は維持されている（`agent_type` 9/9、`single_invocation`
9/9、`requested_model` は3周とも具象で `auto` は渡していない）。
つまり今回の変更は**他の契約を壊していない**。

### 3.2 `compare-explicit-multifile` — 部分的に改善（6 / 9）

| モード | 成立 | 失敗の内訳 |
|---|---|---|
| auto | 3 / 3 | — |
| haiku | 2 / 3 | `run.W7zG2Vat`: 子は絶対パス付き3項目を返したが親が NO-ITEM |
| sonnet | 1 / 3 | `run.9drN4ts4`: 親が NO-ITEM／`run.qmvXaj0z`: **子が**パスなしの3項目を返し、親はそれを忠実に写した（NO-PATH） |

比率は 5/21 → 6/9 に上がったが、n が小さく、**改善と断定できる差では
ない**。`qmvXaj0z/sonnet` の失敗は親ではなく**子側の非遵守**であり、
`reviews/gold-confirmed-2026-09-15.md` §2.1 で「完全遵守ではない」と
記録した残り15項目と同種の事象が、新しい実測でも1件出た。
このケースは全9実行で skill を開いている（`auto-explicit-multifile` の
3/9 と対照的）。

### 3.3 `auto-edit-grep-location` — 解消せず（0 / 9）

委譲3モード9実行すべてで、メタデータ命令（`stat`/`wc -c`）は
content Grep より**後に来ないどころか、1度も実行されていない**。
description を `before the first Read or content search` に広げた
`83e1c91` の修正は、行動を変えなかった。

**総合合否では見えない。** このケースは12実行すべてが総合 pass で、
`edit_flow` も 12/12 成立している。項目別に数えて初めて
「編集契約は守るが、ルート判断はメタデータに基づいていない」ことが
分かる。対象ファイルは 5613 B で予算内のためルート自体は正しく、
実害は出ていない。

### 3.4 `auto-small-files-four` — 成立（6 / 6）

4パス・合計234 B・明示委譲なしで、`direct`/`auto` 両モード3周とも
親が4件を自分で読み、Agent を起動しなかった。
`03f9fb4`（description を C 案に）の意図どおりの振る舞いである。
**今回唯一、明確に成立した動作確認**。

ただしこれは「C 案が誤読を減らした」ことの証明ではない。変更前の
同条件の実測がないため、C 案なしでも同じ結果だった可能性は排除できない。

### 3.5 `compare-edit-dense-lines` — 解消せず（0 / 3）

3周とも1本目の content Grep が `head_limit` なしだった。

```
Grep #1 on dense_edit.txt (80032 B, over budget) used output_mode=content
with no head_limit; §26.5 requires files_with_matches or head_limit 1-20
```

§26.5 に数値基準（1〜20、`-A`/`-B`/`-C` 禁止）を明文化した
`5f0271a`/`7fed1c3` は、判定側の検出を可能にしたが、**親の行動は
変えなかった**。`edit_flow` は 3/3 成立しており、編集自体は正しい。

## 4. まとめ

| 項目 | 結果 |
|---|---|
| 不要な委譲なし（`auto-small-files-four`） | **成立 6/6** |
| 絶対パスの省略解消（`compare-explicit-multifile`） | **部分 6/9**（n 小、断定不可） |
| 絶対パス付き項目の保持（`auto-explicit-multifile`） | **不成立 0/9** |
| 検索前メタデータ確認（`auto-edit-grep-location`） | **不成立 0/9** |
| content Grep の形式遵守（`compare-edit-dense-lines`） | **不成立 0/3** |

**文言変更による行動改善は、4件中3件で確認できなかった。**
description への到達性修正は、規則を親の文脈に載せるところまでは
達成しているが、遵守には結びついていない。「規則への到達は遵守を
意味しない」という既存の限定が、今回の課金測定で裏づけられた。

既存の契約（`agent_type`、`single_invocation`、`requested_model`、
`edit_flow`、`deny_bypass`、`child_*`）はすべて 3周とも成立しており、
今回の一連の変更が他の振る舞いを壊していないことは確認できた。

## 5. 観測条件についての注意

本測定は「コミット + 保存差分」の構成での観測である。実行経路には
`plugin/hooks/*` や `code-writer` 側の別変更も入っているため、
**各修正単独の効果としては扱えない**。次回は専用チェックアウトを用意し、
実行対象を固定して測る。

## 6. 残件

- 不成立3件は、文言をさらに強めるか、機械的な強制（フック側）に
  移すかの設計判断が必要。**本記録では判断していない。**
- `compare-explicit-multifile` の子側非遵守1件（`qmvXaj0z/sonnet`）は
  子側契約の問題であり、親の保持義務とは別件。
- `gold_confirmed` の古い spec 47実行は、引き続き比較から分離する。
