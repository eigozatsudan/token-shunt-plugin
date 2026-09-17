# 送り返しの機構を誘発 case で測る・結果（2026-09-17）

事前登録: `reviews/fence-bait-design-2026-09-17.md`（`3ed2fdc`）。
case の実装: `9a8ce5b`。per-run の行: `reviews/data/fence-bait-2026-09-17.csv`（8 行）。

## 1. 結論

**誘発できなかった。機構は未検証のままである。**

事前登録 §4.1 の門（pilot 4 run 中 3 run 以上でフェンス）に
**2 案とも届かなかった**ので、**§7-5 のとおり A/B に進まずここで終える。**

| 案 | 問い | フェンス | 実費 |
|---|---|---|---|
| **V1** `fence-bait-helper` | 名前・**引数名**・def 行番号（機会 1） | **0 / 4** | $0.5197 |
| **V2** `fence-bait-helper-3` | 上記を**3 メソッド分**（機会 3） | **0 / 4** | $0.6991 |

**3 案目は作らない**（事前登録 §3・§7-5）。作れば「出るまで試す」ことになる。

**本段階 $1.6958**（枠 $4.5、reserve $0.70）。**累計 約 $95.3 / 上限 $100。**

## 2. 誘発が効かなかった様子

V2 の worker 報告（`run.CVsrOyxH`、抜粋）:

```
confirmed: .../application_helper.rb — wiki_helper (line 1962): method name wiki_helper, no arguments, def at line 1962
confirmed: .../application_helper.rb — remove_double_quotes (line 1969): method name remove_double_quotes, argument name: identifier, def at line 1969
confirmed: .../application_helper.rb — autocomplete_data_sources (line 1974): method name autocomplete_data_sources, argument name: project, def at line 1974
```

**引数名は prose で述べられており、def 行は貼られていない。**
**`confirmed:` の書式が装飾の置き場所を残さなかった** — というのが
**見えたことの記述**であって、**検証された説明ではない**（§4）。

8 run すべてで `accuracy_any` 1、`child_status` 1、`child_msg_cap` 1、
partial 0、`child_no_body` の失敗は**フェンス以外の理由でも 0 件**。

## 3. 0/8 が言えること・言えないこと

**言えるのは「本設計の A/B に必要な高い率には届かない」だけである。**
門を 3/4 に置いたのは、**各腕 6 run で Fisher p = 0.0022 を成立させるには
ほぼ 100% の率が要る**からで、**0/8 はその率が無いことを示す。**

**「誘発に効果が無かった」とは言えない。**
0/8 の Wilson 95% 上限は **32.4%**、三の法則でも **37.5%**。
**自然発生率 1.2% のもとで 8 run に期待される件数は 0.1 件**であり、
**そもそも 8 run では「増えたかどうか」を見分けられない。**
**誘発の効果の有無は本測定では分からない。**

## 4. 仮説を作り直さない

§2 の「`confirmed:` が置き場所を残さなかった」は**観察の記述であって、
本測定が検証した主張ではない。** 同じデータから次の誘発案を組み立てれば、
**出るまで案を替える手続き**になる。**しない。**

**元の観測 1 件（`run.9ooxkL0s`）が何によって起きたのかは、依然として分からない。**

## 5. 送り返し機構の現状

**実機での裏付けは、いまも偶然観測された 1 件だけである** —
`reviews/fence-sendback-2026-09-17.md` §2 の `run.dYCTbv4H`
（block → reblock_suppressed → 言い直しの鎖が端から端まで見えた 1 件）。

**`6d2c9c2`（フックの修正）と `fcf97ee`（送り返し文の位置指示）は入れたままにする。**
オフラインのテストは通っており、**害が観測されていない**
（本ブロックでも `child_status` / `child_msg_cap` は 8/8）。
**「効くと確かめた」とは書かない。** n=1 は裏付けではない。

## 6. 枠

**残り約 $4.7。課金測定はここで終わりである**（事前登録 §5 に書いたとおり）。
これ以上の測定には**総枠の見直しが要る。**

見直す場合に必要な額は、前段の結論から出ている:
**自然発生率 1.2% で効果測定を組むなら各腕 400 run 前後、$70 以上。**

## 7. 残した case をどうするか

`fence-bait-helper` / `fence-bait-helper-3` は **suite X に置いたまま残す。**
release run には入らず（experiment 扱い）、**8 run 分の baseline が付いている。**
**誘発に失敗した case であることを `note` と本記録が示している。**

## 8. 道具の借金

**`pairs.py` が片腕測定に使えないのは 3 回目である。**
今回も `bait.py` を scratchpad に書き捨てた（`dose.py`, `fence.py`,
`prevalence.py` に続いて 4 本目）。**測定のたびに採点器を書き捨てている。**

**次にやるのは測定ではなく、これを直すことである。**

### 8.1 今回守れたこと

- **採点器は合成データだけで検証した**（`test_bait.py` 15 件）。
  **実データには門の判定まで当てていない**（前段 §12.1 の再発防止）。
- **run 計数は `summary.json` の `cases` から読んだ**。substring 一致はやめた
  （前段 §6.1 の再発防止）。**今回、数え落としは無い。**
- `spend.py --cap 4.5 --reserve 0.70` を run ごとに通した。**枠内。**

### 8.2 記録しておく瑕疵

**最初の起動で `GUARD rc=2` が出た** — 新規チェックアウトに
`evals/compare/tmp` が無く、`spend.py` が「not a directory」で止まった。
**課金は発生していない。** driver に `mkdir -p` を足して再開した。
**停止規則が動いた結果ではなく、私の driver の初期化漏れである。**
