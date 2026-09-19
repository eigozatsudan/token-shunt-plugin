# 「保持要件を deny の外に置く」は既に出荷済みだった。効果を測った（2026-09-20、$0）

`reviews/gold-confirmed-cause-2026-09-20.md` §4 で 2 択を出し、
**選択肢 1（保持要件を deny の外にも置く）**が選ばれた。
**実装は不要である。2026-09-16 の `7f5fb43` が既にそれをしている。**

`plugin/hooks/worker_launch.py` の docstring は、こちらが独立に辿り着いた
診断と同じことを、当時すでに書いていた:

> the rule itself is stated where the parent is furthest from using it: in
> the skill it loaded, and in the deny that started the delegation —— **a
> deny that an explicitly delegated call never sees at all.**

別経路（`reviews/a-suite-failures-9346d19-2026-09-16.md` §1、
「絶対パスを 3 つ受け取った親が basename を 3 つ書いた」）から
同じ穴に到達している。**作るものは無い。残っていたのは「効いたのか」だけである。**

## 1. 効いていない —— リマインダ到達後も 213 ターン中 108 で全滅

判定は**出荷している `sendback_retention.run_all`** そのまま
（`check-final-answer` が send-back を決めるのに使う関数）。
再現: `reviews/data/retention-after-reminder-2026-09-20.py`。

```
turns carrying the reminder: 242
of those, worker items present: 213
  child_items:violation     29
  line_retention:ok        105
  line_retention:violation 108
```

**違反 108 のうち 98 は「1 行も残っていない」。** 部分的な取りこぼしではない。

| | 件数 |
|---|---|
| 全行 drop | **98** |
| 一部だけ残した | 10 |
| `demoted`（絶対パスでなくなった） | 0 |
| `altered`（文言が変わった） | 36 |

違反ターン全体で、worker の `confirmed:` 行 **815 行のうち残ったのは 80 行**である。

**リマインダは届いている**（242 ターンの transcript に文面がある）。
**届いたうえで、約半分のターンで全部落ちている。**

## 2. 直すはずの機構が、アーカイブで 1 度も動いていない

落とした親を差し戻す `check-final-answer` は**プラグインでは既定 on** である
（`plugin/hooks/check-final-answer:8`）。しかし:

- **`evals/compare/run.sh:396` が `export TOKEN_SHUNT_SENDBACK=${SENDBACK:-off}`。**
  評価ハーネスの既定は **off** である。
- アーカイブ全体で send-back の文面
  （`your answer dropped lines the reader worker confirmed`）も
  relapse の文面も **0 件**。

**つまり全アーカイブは、製品が出荷時に持っている修復を切った状態の測定である。**
上の 108 はリマインダ単独の成績であり、**製品の成績ではない。**
逆に言えば、**send-back の実効性はアーカイブからは 1 件も観測できない。**

## 3. 次に決めるべきこと

1. **評価ハーネスの既定を出荷時と揃えるか。** 揃えないなら、
   これまでの全ブロックが「出荷形態ではない構成」を測ってきたことになる。
   揃えるなら、**過去の数字との比較可能性が切れる**（腕が変わる）。
2. **$0 で先に言えること。** send-back の発火条件は `line_retention` であり、
   §1 の 108 ターンはその条件を満たしている。**発火していたはず**とは言えるが、
   **親が差し戻しに従ったかは、走らせないと分からない。**
   ここは再生では埋まらない（差し戻し後の親の応答が transcript に無い）。

## 4. これが言っていないこと

1. **`exists` を上書きしている。** `classify_path` は `os.path.exists` を呼ぶが、
   アーカイブの staged corpus は削除済みなので、そのままでは全件 UNDETERMINED になる。
   `/work/fixtures/` 以下を「在る」とみなして、**走っていた当時の答えを再現した。**
   **ここだけが出荷コードの判断ではない。**
2. **`child_items:violation` の 29 ターンを除いてある。** worker 側が
   items を返していない（または解決できない）ターンは、親の違反ではない。
3. **ケースが少ない。** 母集団は `intake-replay-wide` と同じ 6 ケースである。
4. **課金していない。**
