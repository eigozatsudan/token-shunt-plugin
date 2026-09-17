# フェンス違反がどこで起きるかの測定・結果（2026-09-17）

事前登録: `reviews/fence-prevalence-design-2026-09-17.md`
（`18ed4bc`、修正 `b52d2d1` §11、逸脱 `fe8d20e` §12）。
per-run の行: `reviews/data/fence-prevalence-2026-09-17.csv`（91 行）。

## 1. 結論

**フェンス違反が出た case は、測れた 17 case のうち 1 case（`redmine-last-helper`）。**

事前登録 §7 の 3 分岐のうち、**「1〜2 case でしか出ない」に当たる。**
したがって書き方も事前に決めたとおり:

> **事象は特定の case に偏っている。偏りの理由は本測定では分からない。**

次の効果測定は**どの case でも組めるわけではなく、事象が出る case に絞って
N を積むしかない。** ただし後述のとおり、**どの case に偏っているのかも
本測定では特定できていない**（§4）。

**分母は事前登録の 19 ではなく 17 である。私の駆動スクリプトの欠陥で
3 case が走らなかった**（§6.1）。これは製品の所見ではなく、私の誤りである。

## 2. 走らせたもの

| | |
|---|---|
| 固定コミット | `fe8d20e`（`/tmp/ts-prev` 専用チェックアウト） |
| run 数 | **91**（計画 105） |
| 実費 | **$20.1815**（枠 $22、reserve $0.30） |
| 設定 | `MODES=auto`、`SENDBACK=off` |
| 判定 | `judge.py` の `has_code_fence`（フック自身の検出器ではない） |

CSV の `cost_usd` は auto transcript の額のみで**合計 $14.5440**。
差額 $5.64 は probe と judge の分で、`spend.py` の $20.1815 に含まれる。

## 3. 主要（§5）

**5 run 中 1 件以上のフェンス run が出た case 数: 1 / 17。**
検定は事前登録どおり置かない。

| case | n | フェンス | 実費 |
|---|---|---|---|
| `redmine-last-helper` | 5 | **1** | $0.6062 |
| `redmine-last-query` | 5 | 0 | $0.6090 |
| `redmine-last-journal` | 5 | 0 | $0.5112 |
| `redmine-last-method` | 5 | 0 | $0.6359 |
| `redmine-last-user` | 5 | 0 | $0.5614 |
| `redmine-visible-scope` | 5 | 0 | $0.7583 |
| `reader-batch-ambiguous` | 5 | 0 | $1.1233 |
| `reader-batch-evidence` | 5 | 0 | $0.8874 |
| `reader-bounds` | 5 | 0 | $0.6054 |
| `reader-followup-scope` | 5 | 0 | $1.1011 |
| `compare-one-line` | 5 | 0 | $1.2854 |
| `compare-bulk-facts` | 5 | 0 | $0.8400 |
| `compare-explicit-multifile` | 5 | 0 | $0.6185 |
| `compare-edit-dense-lines` | 5 | 0 | $2.0125 |
| `compare-hook-deny-route` | 5 | 0 | $0.4659 |
| `auto-routing-boundary-known-range-deny` | 5 | 0 | $0.5773 |
| `auto-bulk-facts` | **1** | 0 | $0.1347 |
| — 以下は走らなかった（§6.1） | | | |
| `auto-one-line` | **0** | — | — |
| `auto-explicit-multifile` | **0** | — | — |

**`auto-bulk-facts` は 1 run しかない**（機構確認の 1 run のみ）。
**0/1 は 0/5 より弱い。** この case を「出なかった」と数えるのは
他の 16 case と同じ重みではない。表の数字のまま読むこと。

事前登録 §3.1 のとおり、**case ごとの率は n=5 では推定できない。**
0/5 の Wilson 95% 上限は **43.4%** で、**「この case は安全」とは言えない。**

## 4. 予測との突き合わせ

| 読み | 事前予測（/19） | 実測（/17） |
|---|---|---|
| 違反は問い一般に起きる（率 11%） | 約 8 | — |
| `redmine-last-query` に固有 | 約 1 | — |
| **実測** | | **1** |

**数としては「約 1」に近い。だが場所が違う。**
予測は `redmine-last-query` に固有というものだったが、
**本ブロックの `redmine-last-query` は 0/5 で、出たのは `redmine-last-helper` だった。**

つまり本測定が支持するのは「**どこか一部の case でだけ起きる**」までであって、
**「`redmine-last-query` に固有」ではない。**
**n=5 では、1 件が出た case と 0 件だった case を区別できない**（§3）。
**「`redmine-last-helper` に固有」と読み替えてはならない。**
それは同じデータで仮説を作り直すことであり、事前登録 §6 が禁じている。

## 5. 副次（§5-1〜6、すべて事前に決めたもの）

1. **bulk-reader 17 case をまとめたフェンス率: 1/81 = 0.0123。**
   **Wilson 95% 区間 0.0022 .. 0.0667。**
   これが次の効果測定の power 計算に使う数字である。
   **上限 6.7% は、前提にしていた 11% を含まない。**
   **各腕 24 run で 25% を前提にした前回の設計は、この数字の上では成り立たない。**
2. **code-writer の 2 case: 10 run、フェンス 0**
   （`compare-code-writer-ok` 5/0、`compare-code-writer-no-ref` 5/0）。
   0/10 の Wilson 95% 上限は 27.8%。**フックの適用範囲の外に事象は観測されなかった**
   が、**10 run では「無い」とは言えない。**
3. **`redmine-last-query`: 本ブロック 0/5。** 既存の別ブロックは 4/36。
   **プールしない**（別ブロック・別日）。並べて記す。
4. **`child_no_body` がフェンス以外の理由で落ちた run: 0。**
   本文の漏れは、本ブロックではフェンス以外の形で現れなかった。
5. 全 91 run:
   - **正答**（`accuracy_any` → 無ければ `accuracy` → 空欄、§11.2）:
     **1 が 70、0 が 1、空欄 20。**
     0 は `run.zQUbrFSv`（`reader-bounds`）。
     空欄はその検査を宣言していない 4 case（`compare-code-writer-ok`,
     `compare-code-writer-no-ref`, `reader-batch-ambiguous`, `reader-followup-scope`）。
   - **`child_status`: 90/91**（落ちたのは `run.pxVY5UXi`、`compare-edit-dense-lines`）。
   - **`child_msg_cap`: 91/91。**
   - `status_partial`: 25 run。6 case に集中している
     （`compare-code-writer-no-ref` 5, `reader-followup-scope` 5,
     `redmine-visible-scope` 5, `reader-batch-evidence` 4, `reader-bounds` 3,
     `reader-batch-ambiguous` 3）。**本測定の outcome ではない。**
6. **case ごとの実費は §3 の表。** 1 run の最大は **$0.6721**
   （`run.6j93fhqE`, `compare-edit-dense-lines`）。
   **次の設計の reserve はこの値から取る**（平均ではなく直近の最大、
   メモリ `billable-stop-rule-needs-a-mechanism`）。

**`isolation` は §11.2 のとおり読み取りから除外した**（片腕では定義上評価できない）。
参考として fail は 91 run 中 26 件。**本測定の outcome ではない。**

## 6. 逸脱

### 6.1 **駆動スクリプトの欠陥で 3 case が走らなかった（分母 19 → 17）**

`/tmp/ts-prev/drive.sh` の「この case は何 run 済みか」を数える部分:

```sh
done_count() { grep -l "\"$1\"" evals/compare/tmp/runs/*/summary.json | wc -l; }
```

**すべての `summary.json` は `suite_cost_usd.cases` に
`auto-bulk-facts` / `auto-explicit-multifile` / `auto-large-writer` /
`auto-one-line` の 4 つを常に持つ**（走っていない case も null 値で載る）。
したがって `grep -l '"auto-one-line"'` は **91 ファイル全部に一致し**、
`done_count` は 91 を返し、**5 以上なので 1 周目から飛ばされた。**

結果:

- `auto-one-line` **0 run**、`auto-explicit-multifile` **0 run**
- `auto-bulk-facts` は機構確認の **1 run** のみ
- 合計 91 run（計画 105）、駆動器は `ALL-CASES-AT-N` と報告した

**これは私の scripting の誤りであって、製品の所見ではない。**
**`ALL-CASES-AT-N` は嘘の報告だった。** 走った run 自体は正しく、
**採点済みの 17 case の数字は影響を受けていない。**

**欠けた 14 run は後から足さない**（事前登録 §4・§6）。
足せば「結果を見てから N を伸ばす」ことになる。

**教訓は run の数え方を run の成果物の substring 一致で行ったことにある。**
数えるなら `summary.json` の `cases` キー（実際に走った case）を見るべきだった。

### 6.2 中間解析（`fe8d20e` §12.1）

走行中に採点器を実データに当て、その時点の主要 outcome を見た。
**何も変更していないが、見てよかったことを意味しない。** 記録として残す。

### 6.3 reserve を超えた run（`fe8d20e` §12.2）

`compare-one-line` の 1 run が $0.4806。設定時の実測最大 $0.2423 に対する
reserve $0.30 を超えた。**走行中は変更しなかった。**
最終的な実費 $20.1815 は枠 $22 に収まっている。

## 7. ここから何が言えないか

- **利用実態の推定ではない**（事前登録 §8）。case 集合は eval のものである。
- **`SENDBACK=off` で測ったので、これは「文言だけで守られる率」**である。
- **どの case に偏るのかは特定できていない**（§4）。
- **`auto-one-line` と `auto-explicit-multifile` については何も測っていない**（§6.1）。

## 8. 次にすること（本測定の外）

- **`drive.sh` 相当の run 計数を substring 一致でやらない。**
  道具にするなら `summary.json` の `cases` を読む。
- **効果測定の設計は、率 1.2%（上限 6.7%）の上で組み直す必要がある。**
  前回の「各腕 24 run」は成り立たない。**枠の見直しが要る**
  （事前登録 §4.1 のとおり、本測定で残額のほとんどを使った）。
- `pairs.py` が片腕測定に使えない件は**2 回続けて**効いた。3 回目が来る前に直す。
