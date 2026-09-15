# `head_limit` 整合性：本文修正と判定側検査（2026-09-15、適用済み）

方針: §26.5 の**手段基準**を維持し、§11.6 の適用が重なる箇所（予算超過の対象）に
同じ制限を明記する。**予算内の編集経路は §11.6 の結果基準のまま。**
機械検証はフックではなく**判定側**に置く。

提案段階の整理は `reviews/head-limit-proposal-2026-09-15.md`（§4 に訂正あり）。

## 1. 本文の変更（7000 B 以内で収めた）

`plugin/skills/bulk-reader/SKILL.md` **6933 → 6997 B**（+64）。
提案時の案は +316 B で上限 7000 を超えたため、説明を重複させず短縮した。
**上限 7400 への変更は不要になった。** 本文も読み込めば課金されるので、
削減方針に沿って追記量を抑えている。

§26.5（数値基準と文脈フラグ禁止をここで一度だけ定義）:

```
-  contract or confirm a known range, with `output_mode=files_with_matches`
-  or a short `head_limit`.
+  contract or confirm a known range,
+  with `files_with_matches`, or `content` with `head_limit`
+  1-20 and no `-A`/`-B`/`-C`.
```

`-A`/`-B` は「フックされない機構」の例示から外し、**形式要件の側で明示的に
禁止**した。判定側だけで規則を強めない、という整合のための移動である。

§11.6 / step 4（形式要件を再説明せず §26.5 を参照）:

```
-  (short unique pattern, line numbers, limited output) or an already
+  (short unique pattern, line numbers, limited output; over budget, the
+  §26.5 form, not one line back) or an already
   verified known range
```

「一意パターンでたまたま1行返った」ことと「呼び出し前に出力量を制限できる」
ことを切り分ける文言で、最後の `limited output` が予算内の基準として残る。

## 2. 「短い」の共通基準

既存規則に数値がなかったため、**検査側だけで決めず本文に書いた**。

| 置き場所 | 値 |
|---|---|
| SKILL.md §26.5 | `head_limit` 1-20、`-A`/`-B`/`-C` なし |
| `evals/compare/flow_checks.py` `POSITION_GREP_HEAD_LIMIT` | 20（上端） |
| `SMALL_TASK_BUDGET` | 16384 |

**`<= 20` ではなく 1〜20 の正の整数**に限定する。0・負数・`True`・
非整数は「呼び出し前に効く上限」ではないため、いずれも非適合とする。

両者が一致することは
`test_position_grep_bound_uses_one_standard_in_body_and_judge` が固定する。
実測された適合例の `head_limit` は 5 で、20 は十分に緩い上限。

## 3. 判定側の検査

`flow_checks.position_grep_errors(tr, target)` → `(applicable, errors)`。
`judge.py` の `edit_flow` ブロックから呼び、チェック名は `position_grep_form`。

- **予算超過の対象にのみ適用。** 対象の実サイズを見て 16384 B 以下なら
  `applicable=False` を返し、チェック自体を記録しない（予算内の編集経路は不問）。
- `output_mode=files_with_matches` は適合。`content` は
  **明示された `head_limit` が 1〜20 の正の整数**のときだけ適合
  （`0` / 負数 / `True` / `'5'` / `1.0` はすべて非適合）。
- **各 content 呼び出しを個別に検査する。** 先行する `files_with_matches` は
  後続の無制限呼び出しを適合扱いにしない（関数内に状態も `break` も持たない）。
- `head_limit` があっても `-A`/`-B`/`-C` が付けば非適合。§26.5 が
  `-A`/`-B` を `head_limit` と並べて挙げており、文脈窓は返却行数を増やすため。
- 対象の判定は Grep の `path` 一致、または返却テキストに対象パスが現れること。
- **対象への content 呼び出しが1件もなければ、チェックを記録しない。**
  「判定すべき呼び出しがない」ことを適合として残さないため。

フックは変更していない。Grep はフックされないままで、検出は判定時に行う。

## 4. 既存トランスクリプトでの検証（追加課金なし）

`tmp/runs/*/transcripts` の全周を対象に、実行済みのフィクスチャ木が
消えている分だけサイズを既知値で補って検査した（道具入力・判定ロジックは無改変）。

| ケース | サイズ | 実行数 | 結果 |
|---|---|---|---|
| `compare-edit-dense-lines` | 80034 B | 24 | **非適合 22 / 適合 2** |
| `auto-known-range` | 25953 B | 52 | **違反対象の呼び出しなし**（予算超過だが content search 0） |
| `auto-edit-grep-location` | 5613 B | 76 | 対象外（予算内） |
| `auto-edit-grep-ambiguous` | 5674 B | 64 | 対象外（予算内） |

`auto-known-range` の 52 件は**適合する検索の実績ではない**。検査対象となる
呼び出しが存在しなかった、というだけである。

- **非適合の形**: `{"pattern":"^EDIT_MARK=", "output_mode":"content", "-n":true}` —
  `head_limit` なし。これが 22 周で一致した。
- **適合の形**（`run.jrXDoIAh` / `run.ucJ95llj`）:
  `files_with_matches` → `content` + `-n` + `head_limit: 5`。
- 予算内の 140 実行は 1 件も検査対象にならず、**予算内の編集経路に
  制限が漏れていない**ことを確認した。

### 4.1 従来の規則違反と、新しい数値基準の区別

過去24実行で観測された content Grep の `head_limit` は
**`None` が 22 件、`5` が 2 件**（`-A`/`-B`/`-C` は 0 件）。したがって:

| 判定根拠 | 件数 | 位置づけ |
|---|---|---|
| `head_limit` を一切付けない | 22 | **従来の §26.5 からも明確に違反**。「files_with_matches か短い head_limit」という形式要件を、数値を問うまでもなく満たしていない |
| 数値基準 1〜20 に違反 | 0 | 今回明文化した基準。過去実行では該当なし |
| `-A`/`-B`/`-C` 併用 | 0 | 今回明文化した基準。過去実行では該当なし |

**今回の数値・フラグ基準によって判定が変わった過去実行は1件もない。**
22件は従来から違反だった形式で、これまで検出されていなかっただけである。
1〜20 と `-A`/`-B`/`-C` 禁止は、今後の判定のために基準を確定させたもの。

### 4.2 提案記録の訂正

提案時に「dense-lines は周1 のみ非適合、周2・3 は既に適合」と書いたが、
**誤り**。arm D の3周（`run.IcUCbRc4` / `run.vaNaRE2i` / `run.xv9H1gDW`）は
いずれも `head_limit` なしの content Grep を1回実行しており、**3周とも
§26.5 に非適合**である。適合の形が現れたのは別の2周。

なお、この検査は **dense-lines 周1 を「今回から非適合にする」ものではない**。
既存の §26.5 に対する非適合を、これまで誰も見ていなかったところで
**明確に検出する**ようにしたもの。

## 5. ハーネス

- `evals/test_reader_call_contract.py`: 44 → **52 tests, OK**
  - `PositionGrepFormTests`（7件）が違反・適合・対象外の3系統を固定。
    先行 `files_with_matches` が後続を免責しないこと、`-A` が制限を破ること、
    予算内が対象外であることを個別に検査。`head_limit` は
    `0 / -1 / True / '5' / 1.0 / 21` を非適合、`1 / 20` を適合として固定し、
    content 呼び出しが無い場合にチェックを記録しないことも固定。
  - 共通基準テスト2件が本文と `flow_checks` の値一致を固定。
- `judge.py --selftest`: 全件 ok。
- `./evals/run.sh`: **pass 125 / fail 0**。

`evals/run.sh` は変更していない（新テストは既存の
`reader_call_contract` スイートに載せた）。

## 6. 残る限界

- **`-A`/`-B` 以外の抜け道は未検査。** Bash の `sed -n`/`awk`/`head -c` で
  本文を取り出す経路は §26.5 が禁じているが、この検査は Grep しか見ない。
- 文言変更で `-A`/`-B` が本文の形式要件側に移ったため、「フックされない機構」の
  例示は `-o` / `head -c` のみになった。禁止の範囲は変わっていない。
- 検査は `edit_flow` を持つケースでのみ走る。編集を伴わない予算超過ケースで
  位置特定 Grep を行う経路は、今のところ対象になっていない。
- 動作面の効果（本文の文言変更で無制限 Grep が減るか）は**未検証**。
  検出はできるようになったが、追加の課金測定は行っていない。
