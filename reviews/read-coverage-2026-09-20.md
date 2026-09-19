# targeted Read 被覆率計器を実機で 3 回回した（2026-09-20、$1.7261）

行データ: `reviews/data/read-coverage-2026-09-20.csv`
（sha256 `08364260cbe40136c2418f7bf029fd0c256b79c8e9244ec5bc26dde1e6dbe1b6`）。
transcript は `~/measurements/coverage-2026-09-20/` に sha256 つき（`SHA256SUMS`）。
**リポジトリに transcript を入れていない。**

計器: `plugin/hooks/record-coverage` + `evals/compare/read_coverage.py`。
設計は `docs/superpowers/specs/2026-09-19-targeted-read-coverage-design.md`。
**拒まない。判定に影響しない。閾値を持たない。**

## 1. 何を買ったか

| run | ケース | 読み方 | 判定 | 費用 |
|---|---|---|---|---|
| run.8bpx1reV | django-multiturn-context/auto | 4 ターンの会話 | fail (child_reads_once) | $1.4045 |
| run.LWkKswLK | auto-edit-grep-location/auto | Grep → 原本の targeted Read → Edit | pass | $0.1362 |
| run.Duox7sd0 | django-plan-trace-bare/auto | 大きい 3 ファイルを bulk-reader へ委譲 | pass | $0.1854 |

run.8bpx1reV の fail は **worker が 6 Read を超えた**ことによるもので、**計器とは無関係**である。

## 2. spec §9 が「未検証」と書いた 2 つの境界に答えが出た

1. **worker は `agent_id` と `agent_type` の両方を運ぶ。**
   `agent_id=a8772f0658bb1a12f`, `agent_type=token-shunt:bulk-reader`。
   §3 が「両方を記録する」と決めた根拠（`intake_ledger.py:134`）は実機で正しかった。
2. **`--resume` は `session_id` を変えない。** 4 ターンの hooklog すべてが
   `568daeca-…` の 1 つだけで、多セッション警告は出なかった。
   **§8.7 の前提はこの 1 会話では成立している**（n=1 である）。

## 3. 親と worker を分けたのは理論ではなかった

| | files | reads | covered | total | coverage |
|---|---|---|---|---|---|
| **親** | 2 | 2 | 35 | 718 | **0.0487** |
| worker | 6 | 6 | 2,284 | 2,284 | 1.0000 |

**混ぜた rollup は (35+2284)/(718+2284) = 0.773 になる。親だけなら 0.0487 —— 16 倍の水増しである。**
worker 行は 6 本とも coverage 1.0・`full_file_reads=1` に張り付き、§6 の予告どおりの形になった。
最終レビューがこれを見つけていなければ、**最初に出た数字は 0.773 で、
「親がファイルの 8 割を回収している」と読まれていた。**

## 4. 一番大事な所見 —— 逐次回収は 1 度も起きていない

**親がスライスを繋いでファイルを組み立てた例は、3 本の中に 1 つも無い。**
親の読み取りは 2 回だけで、どちらも `segments=1`、`overlap=0`、`reads=1`:

- `edit_hint.py` の 401 行中 **5 行**（0.012）—— §26.5 の編集契約どおり、Edit の前に原本を確認した。
- `writer.py` の 317 行中 **30 行**（0.095）。

**この計器が作られた理由（アーカイブの親 corpus Read 21 回中 18 回が targeted で、
32 KB を targeted Read だけで取り込む会話に Lock B は何もしない）に対して、
今回の 3 本は「その形は起きなかった」と言っている。**

## 5. これが言っていないこと

1. **n=3 である。** 率でも傾向でもない。**1 会話・1 ケース・1 腕ずつの観察である。**
2. **direct 腕は観測できない**（§8.8）。`run.sh` は direct にだけ `--plugin-dir` を渡さないので、
   フックが 1 度も走らない。**「direct の被覆率が 0」は成果ではなく計器の不在である。**
   本測定の 3 本はすべて auto であり、**腕の比較を一切していない。**
3. **Bash 経由・Grep の content 出力・worker の最終メッセージは見えない**（§8.3、設計 §15）。
   親の context 汚染は被覆率 0 でも起こりうる。**「coverage が低い = 親がきれい」ではない。**
4. **行数が変わらない Edit は見えない**（§8.9）。今回は親の読み取りが各ファイル 1 回なので
   `total_changed` は原理的に発火しえない。
5. **費用で成果を語らない。** 上の表は予算の記録であって、結果ではない。

## 6. 予算の逸脱（記録）

見積りはアーカイブの auto 1 会話あたり平均 $0.3724・最大 $0.5014 から取ったが、
**multiturn の実測は $1.4045 で 3.8 倍外れた。** 単発の 2 本は $0.14 と $0.19 で、
**外れたのは複数ターンのケースだけ**である。次に複数ターンを買うときはこの実測から取る。

また、3 本を別々の `--cap` で出そうとして 2・3 本目が走らずに止まった。
`drive.sh` は毎回**同じ run ディレクトリ**を `spend.py` に見せるので、
**cap は呼び出しごとではなく累積である。** 1 セントも無駄にしていない（走る前に止まった）。
再開時は cap を「その時点の実支出 + 1 本分」として `spend.py` から動的に取った。
