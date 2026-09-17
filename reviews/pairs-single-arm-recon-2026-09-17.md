# `pairs.py` の片腕対応・実データでの突き合わせ（2026-09-17）

対象: `cf88864`（片腕対応）と `785e7c6`（正答列の取り違え）。
どちらも**合成 run でしかテストしていなかった**ので、実物で照合した。

## 1. 何を実データとしたか

**課金していない。** `evals/compare/run.sh` を **CLI double** で回した。
モデルだけが替え玉で、**fixture・transcript・judge・aggregate・
`summary.json` の書式はすべて本物**である。

- `auto-small-files` を **両腕**（`direct` / `haiku` / `sonnet` / `auto`）で 1 run
- 同じ case を **`MODES=auto`** で 1 run

**この case は `gold` を宣言しており、judge が出す検査は `accuracy`**
（`accuracy_any` ではない）。**直したフォールバックが効く実際の case である。**

## 2. 結果

修正前（`54485f4` の `pairs.py`）と修正後を、**同じ run ディレクトリ**に当てた。

**修正前:**

```
run,case,direct_read_bytes,auto_read_bytes,...,direct_accuracy_any,auto_accuracy_any,direct_pass,auto_pass,auto_reasons
run.82weYSnh,auto-small-files,194,194,...,,,1,1,
```

**修正後:**

```
run,case,direct_read_bytes,auto_read_bytes,...,direct_accuracy,auto_accuracy,direct_pass,auto_pass,auto_reasons
run.82weYSnh,auto-small-files,194,194,...,1,1,1,1,
run.zRGzVCoQ,auto-small-files,,194,,0.1234,,1,,1,
```

**2 つの欠陥が両方とも実物で見えた:**

1. **片腕の run（`run.zRGzVCoQ`）が丸ごと消えていた。** 修正後は行になり、
   **走らなかった direct 側は空欄**で、0 ではない。
2. **`accuracy` しか宣言していない case の正答が空欄になっていた。**
   run は `accuracy: true` を記録しているのに、**存在する事実を落としていた。**
   修正後は `1`。

**付随して確かめた値:**

- `*_read_bytes` の **194 = 64 + 64 + 66**（fixture 3 本の実バイト数と一致）。
- `*_cost_usd` は transcript の `total_cost_usd` から **0.1234**。

## 3. これで言えないこと

- **実モデルの挙動は照合していない。** 替え玉は決まった応答を返す。
  照合したのは **`pairs.py` が run.sh の出力形式を正しく読むか**である。
- **case の形は 1 つ**（`auto-small-files`）。`gold_any` 側の case や、
  `child_no_body` を宣言する case では**当てていない**。
- 費用は替え玉が書いた固定値であり、**費用の正しさの検証ではない。**

## 4. なぜ後からになったか

**先に run ディレクトリを消してしまったからである。**
前ブロックの実 run が残っていれば、**それで照合できた。**
メモリ `keep-per-pair-rows` は CSV を残せと言っているが、
**道具を直すときは run そのものが要る。**

**次に測定するときは、道具の変更予定があるなら run を消す前に照合する。**
消した後にできるのは、本記録のような替え玉での照合までである。
