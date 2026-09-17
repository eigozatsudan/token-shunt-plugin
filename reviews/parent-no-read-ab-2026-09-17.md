# `parent_no_read` を release suite A/B に広げた件（2026-09-17）

前提: `c87055a`（suite X の 17 case に `parent_no_read` を宣言、SKILL.md
step 1 を deny 非依存に書き換え）。そこでは「A/B への拡大は回帰が無いことを
走らせて確認してから」と保留していた。本記録はその確認と拡大。

**費用 $0.0000。** 新しい live run は行っていない。

## 1. 結論

**広げた。ただし「回帰は無い」とは書けない。**

保管済みの live run 2 本に対して `parent_no_read` を後から当てたところ、
**完走した 37 arm 中 35 pass・2 FAIL**。FAIL は本物の漏れで、
`parent_no_read` が拾うために作られたものそのものだった。

## 2. 対象

`child_reads_once` を持ち、`parent_targeted_read`・`edit_flow` を持たない
（= 編集契約のための親 Read が要らない）case を read-only とみなす。
A/B で該当したのは 11 case:

- A: `compare-bulk-facts` / `compare-one-line` / `compare-explicit-multifile`
  / `reader-batch-evidence` / `reader-batch-ambiguous` / `reader-bounds`
  / `retry-policy`
- B: `auto-bulk-facts` / `auto-one-line` / `auto-explicit-multifile`
  / `auto-routing-boundary-16k-plus`

各 case の `parent_no_read` は `child_reads_once` と同一。編集する case は
従来どおり `parent_no_full_read`（ターゲット読みは許す）のまま。

## 3. 方法

`~/token-shunt-evidence/live-rerun-2026-09-13/run.NckO7koy.tar.gz` と
`live-rerun-2026-09-14/run.mnVnW1FU.tar.gz` を展開し、各 run が自分で
書いた `specs/<case>.<mode>.json` の `expect.delegate` に
`parent_no_read = child_reads_once` を差し込んで、
`judge.py <transcript> <spec> <mode>` を delegate mode（haiku/sonnet/auto）
だけ再実行した。transcript は当時のまま、judge は現行。

**事前に決めた設問は一つだけ**: 「この 11 case の delegate arm で、
委譲した path への親の Read が成功しているものはあるか」。
同じ transcript から他の量は読んでいない。

行: `reviews/data/parent-no-read-ab-2026-09-17.csv`（46 行）。

## 4. 結果

| | arm |
|---|---|
| pass | 35 |
| FAIL | 2 |
| 判定に届かず（`run` check が先に落ちる） | 9 |
| 計 | 46 |

届かなかった 9 arm はすべて `run.NckO7koy`（2026-09-13）側で、理由は
`result is_error: You've hit your session limit`。当時走り切っていないので
この 9 arm は賛否どちらの証拠でもない。**分母は 37。**

### 4.1 FAIL 2 件

いずれも `run.mnVnW1FU` の `auto-explicit-multifile`、haiku arm と
sonnet arm。3 ファイルを worker に渡した後、親が自分で
`concerns/notifiable.rb` と `jobs/welcome_email_job.rb` を読んでいる。
transcript 上、この 2 つの Read は `parent_tool_use_id` が `null`
（worker の Read は Agent の tool_use_id にぶら下がる）。

Django の `run.o9sZc80u` と同じ形。小さいファイルなので
`check-file-size` は設計どおり通し、当時の SKILL.md は禁止を
「After a denied Read」に条件付けていたので、どこにも引っかからなかった。
**この 2 arm は当時、全 check pass で合格している。**

## 5. 広げることの意味

この 2 本は **今日の SKILL.md 修正（`c87055a`）より前**の run である。
新しい文言がこの挙動を止めるかどうかは、**まだ測っていない**。
したがって現状は次のとおり:

- release suite A/B は、実際の漏れを 2 件捕まえた実績のある check を
  今日から持つ。
- その check の **live pass 率は未確立**。次の A/B run で
  `auto-explicit-multifile` が落ちる可能性は現実にある。落ちたら
  それは check の誤りではなく、文言がまだ足りていないという結果である。

`release_eligible` の門を今回いじってはいない。

## 6. 記録した逸脱

無し。設問は 1 つに固定し、他の量は読んでいない。
