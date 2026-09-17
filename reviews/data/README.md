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

## 列

`run`, `case`, `direct_read_bytes`, `auto_read_bytes`,
`direct_cost_usd`, `auto_cost_usd`, `direct_accuracy_any`,
`auto_accuracy_any`, `direct_pass`, `auto_pass`, `auto_reasons`

- `*_read_bytes` は**親自身**が Read で飲んだ、fixture 配下のバイト数。
  子が読んだ分は含まない（それが製品の目的そのものなので）。
- `*_accuracy_any` と `*_pass` は、**検査が無かった場合は空欄**。
  空欄と 0 は違う事実である。
- **case 固有の指標はここに足さない。** それは review に書く。

## 注意

- **CSV は事後に手で編集しない。** 直すなら run から作り直す。
- 費用は**その日のモデル価格**に依る。行は比較可能だが、
  別の日の測定と絶対額を並べるときは価格差を勘定に入れること。
