# 測定の対ごとの数値

`reviews/*.md` は**結論**を残す。ここは**対ごとの生の数値**を残す。

## なぜ在るか

2026-09-17、Redmine を相手にした 88 対の transcript（94MB）を解析後に削除した。
集計値は review に残ったが、**review が訊かなかった問いで再解析することは
もうできない**（`reviews/redmine-dose-2026-09-17.md`、
`reviews/redmine-effect2-2026-09-17.md`）。
行なら数 KB で済む。**行を残す。**

## 使い方

**run ディレクトリを消す前に**走らせ、review と一緒にコミットする:

```
python3 evals/compare/pairs.py -o reviews/data/<測定名>.csv \
    /path/to/evals/compare/tmp/runs
```

run ディレクトリを後から移した場合は、**走った当時の位置**を渡す:

```
python3 evals/compare/pairs.py --root-base /元の/位置 -o ... /移した先
```

transcript の中は当時の絶対パスなので、移した先で照合すると
**どの腕も 0 バイトになる**。0 は正しい auto 腕の値でもあるため、
**取り違えると findings に見える。**

## 片腕の測定

**`MODES=auto` だけを走らせた測定にも使える。**
worker が何を報告したかを問う測定では direct に worker が居らず、
**寄与しない腕に払う理由が無い**ので、片腕は正しい設計である。

**走らなかった腕の列は空欄になる。0 にはならない。**
**0 バイトは正しい auto 腕が読む値**なので、
「走らなかった」を 0 と書けば findings に見えてしまう。

（この対応が無かったために、片腕の測定 3 回が続けて採点器の書き捨てになった
 — `reviews/fence-bait-2026-09-17.md` §8。）

## 列

`run`, `case`, `direct_read_bytes`, `auto_read_bytes`,
`direct_cost_usd`, `auto_cost_usd`, `direct_accuracy`,
`auto_accuracy`, `direct_pass`, `auto_pass`, `auto_reasons`

- `*_read_bytes` は**親自身**が Read で飲んだ、fixture 配下のバイト数。
  子が読んだ分は含まない（それが製品の目的そのものなので）。
- `*_accuracy` と `*_pass` は、**検査が無かった場合は空欄**。
  空欄と 0 は違う事実である。**走らなかった腕も同様に空欄**である。
- `*_accuracy` は **`accuracy_any` があればそれ、無ければ `accuracy`、
  どちらも無ければ空欄**。case によって 3 通りある。
  **列名は事実（答えが合っていたか）で付けてあり、検査名ではない。**
  どちらの検査だったかは `evals/compare/cases.json` の case 宣言で分かる。
  以前、`accuracy` しか持たない case を空欄と読んで **0/20 と誤報した**
  （`reviews/fence-prevalence-design-2026-09-17.md` §11.2）。
- **case 固有の指標はここに足さない。** それは review に書く。

## 古い CSV

`cf88864` より前に `pairs.py` が書いた CSV は、この列を
**`direct_accuracy_any` / `auto_accuracy_any`** という名前で持つ
（`pairs-tool-trial-2026-09-17.csv`）。**値の意味は当時のまま**で、
`accuracy` しか宣言していない case は空欄になっている。
**書き直さない** — run が無いので作り直せず、手で直せば
「CSV は事後に編集しない」を破ることになる。

`fence-sendback-2026-09-17.csv` と `fence-prevalence-2026-09-17.csv` は
`pairs.py` ではなく書き捨ての採点器が書いたもので、列も別である。

## 注意

- **CSV は事後に手で編集しない。** 直すなら run から作り直す。
- 費用は**その日のモデル価格**に依る。行は比較可能だが、
  別の日の測定と絶対額を並べるときは価格差を勘定に入れること。
