# 新文言が親の Read を止めるかの確認・事前登録（2026-09-17）

前提: `66a952f`（step 1 に「一つの質問の path は順序によらず一緒に渡す」を
追加）。`reviews/parent-no-read-ab-2026-09-17.md` §6 で「条文の網羅は
確かめたが挙動は未測定」と書いた、その挙動を 1 本だけ測る。

## 1. 設問（一つだけ）

**この run の `auto-explicit-multifile` の delegate arm で、
`parent_no_read` は pass するか。**

他の量は見ない。費用は停止規則のために見るが、結論には使わない。

## 2. 走らせるもの

- **run は 1 本。** 繰り返さない。
- `SUITE=B`、`SLOTS=auto-explicit-multifile/haiku,auto-explicit-multifile/sonnet,auto-explicit-multifile/auto`
- **direct arm は billing しない。** direct は plugin を読み込まないので
  文言の検証に寄与しない。
- **N は 3 arm に固定。** 走らせてから足さない。

対象をこの case に絞る理由: 2026-09-14 の `run.mnVnW1FU` で
漏れが出たのはこの case の haiku arm と sonnet arm であり、しかも
**別々の形**（委譲後に読む／委譲前に読む）で出た。新文言は後者を
塞ぐために書いたので、同じ case の同じ arm を見るのが直接の検証になる。

## 3. 事前に決めた読み方

| 結果 | 書けること |
|---|---|
| 3/3 pass | 「この 3 arm では再現しなかった」まで。 |
| 1 つでも FAIL | 文言はまだ足りない。FAIL の形（委譲前か後か）を見て次を決める。 |

**n=3 で言えないこと**を先に書いておく。3/3 pass でも
rule of three の上限は約 63% で、**漏れ率が下がった証拠にはならない。**
「直った」と書いてよい結果はこの設計からは出ない。出るのは
「直っていない」という結果だけである（片側の検定力しか無い）。
それでも走らせるのは、`66a952f` 以前は同じ case の 2 arm が 2/2 で
漏れていたためで、まず再現するかどうかを見る価値があるから。

## 4. 停止規則

- 走行前に `spend.py --cap 3 --reserve 1.20`、exit 3 で break。
- reserve $1.20 は archive の**最も高い** arm 合計から取った
  （haiku $0.2342 + sonnet $0.5813 + auto $0.1736 = $0.9891、probe 込みで切り上げ）。
- 累計はこの時点で約 $118.3 / 上限 $150。本段階の枠は $3。

## 5. 走行前点検

`billable-measurement-preflight` のとおり:
専用 checkout を `66a952f` に固定 → 生成物を除いて `git status` clean →
**その checkout の中で** `judge.py --selftest` 全項目 pass →
結果と一緒に固定した commit を書く。

## 6. 行の保存

run ディレクトリを消す前に、`run,case,mode,parent_no_read,reason,cost_usd`
を `reviews/data/wording-live-check-2026-09-17.csv` に落としてから
記録を書く（`keep-per-pair-rows`）。この形は pair ではないので
`pairs.py` は使わず、run が自分で書いた `summary.json` から取る。

## 7. 逸脱の扱い

途中で設問を増やさない。増やしたくなったらこの記録に逸脱として書き、
結論には使わない。

---

## 8. 第 2 回の事前登録（同日・`e6f59c1` を対象）

第 1 回（`426b780`、`run.UIXaDr2A`）は auto arm が FAIL。条文の末尾に
deny の条件が残っていたのが原因で、`e6f59c1` で条文から deny を
外した。**同じ設問・同じ slot・同じ N でもう 1 本だけ走らせる。**

- 設問は §1 と同一。増やさない。
- `SUITE=B`、`SLOTS=auto-explicit-multifile/{haiku,sonnet,auto}`、run 1 本。
- `spend.py --cap 3 --reserve 0.60`（reserve は第 1 回の実費 $0.5203 を
  切り上げた値。最も高い直近の 1 run 分）。

### 多重性について先に書いておく

これは**同じ設問の 2 回目**である。「pass するまで直して走らせる」を
続ければ、いつかは 3/3 pass が出る。したがって:

- 3/3 pass が出ても、**それは「直った」ではなく「2 回目で再現しなかった」**
  である。第 1 回で 1/3 FAIL だったことを併記せずにこの結果を引用しない。
- 直ったと言うには、条文を触らずに独立した run を複数本重ねる必要がある。
  本記録はそこまでやらない。
- 3 回目以降に進む場合は、進む前にこの節に回数を書き足す。
