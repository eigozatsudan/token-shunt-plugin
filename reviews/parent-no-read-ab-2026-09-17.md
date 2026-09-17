# `parent_no_read` を release suite A/B に広げた件（2026-09-17）

前提: `c87055a`（suite X の 17 case に `parent_no_read` を宣言、SKILL.md
step 1 を deny 非依存に書き換え）。そこでは「A/B への拡大は回帰が無いことを
走らせて確認してから」と保留していた。本記録はその確認と拡大。

**費用 $0.0000。** 新しい live run は行っていない。

## 1. 結論

**広げた。既に合格していた arm は一つも落ちていない。**

保管済みの live run 2 本に `parent_no_read` を後から当てたところ、
**完走した 37 arm 中 35 pass・2 FAIL**。FAIL 2 件はいずれも
**当時すでに fail していた arm** で、そこに理由が一つ増えただけである。
当時 pass だった arm は 3 つしか無く、その 3 つは今も pass。

> **訂正（同日）。** 本記録の初版（`10ec54d`）は §4.1 で FAIL 2 件を
> 「当時、全 check pass で合格している」と書いた。**誤りである。**
> 保管された verdict では両 arm とも `verdict: fail` で、
> `child_reads_once` と `foreign_hooks` が既に落ちていた。
> 初版はその verdict を読まずに再判定の結果だけを見て書いていた。
> 合わせて、初版の「live pass 率は未確立・release を落としうる」という
> 危険側の書き方も、根拠の提示としては強すぎた。§7 に置き換える。

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

当時の verdict との対応（`verdicts/*.json` と突き合わせ）:

| 当時 → 今 | arm |
|---|---|
| pass → pass | 3 |
| fail → pass | 32 |
| fail → FAIL | 2 |
| fail → 判定に届かず | 9 |

**pass → FAIL は 0。** ただしこの archive は 46 arm 中 43 が既に
fail しており（多くは `foreign_hooks` の環境要因と `child_reads_once`）、
「既存の合格を壊さない」という主張の台としては弱い。

届かなかった 9 arm はすべて `run.NckO7koy`（2026-09-13）側で、理由は
`result is_error: You've hit your session limit`。当時走り切っていないので
この 9 arm は賛否どちらの証拠でもない。**分母は 37。**

### 4.1 FAIL 2 件

いずれも `run.mnVnW1FU` の `auto-explicit-multifile`、haiku arm と
sonnet arm。漏れたファイルは同じ 2 つ（`concerns/notifiable.rb` と
`jobs/welcome_email_job.rb`、どちらも 7 行の小ファイル）だが、
**形は別物だった。** transcript 上いずれの Read も
`parent_tool_use_id` が `null`（worker の Read は Agent の
tool_use_id にぶら下がる）なので、親のものと確定できる。

**haiku arm — 委譲した後で読んだ。**
3 path を Agent に渡し、worker に SendMessage を送った後で、
その 2 つを親が読んでいる。Django の `run.o9sZc80u` と同じ形。

**sonnet arm — 委譲する前に読んだ。**
順に、`user.rb` の Read が hook に拒否され
（`bytes=67180/65536`）、続けて小さい 2 つを親が読み切り、
その後で `user.rb` **だけ**を worker に渡している。
つまり 3 path の関係質問を、親が 2 つ抱えたまま 1 つだけ委譲した。

## 5. 文言は足りていたか（追記・同日）

この 2 本は **`c87055a` の SKILL.md 修正より前**の run なので、
そのまま「新文言が効かない証拠」にはならない。だが 2 つの形を
新しい step 1 の条文に当ててみると、**片方しか塞げていなかった。**

`c87055a` で入れた条文はこう始まる:

> once a path has gone to a worker, that worker's report is the answer

- **haiku arm は塞がる。** 委譲済みの path を後から読む形そのもので、
  「to check it, to finish it」がそのまま当たる。
  （この arm は加えて停止した worker への SendMessage も打っており、
  §3 の禁止にも触れている。）
- **sonnet arm は塞がらない。** 条文は「worker に渡った後」という
  順序で書かれている。sonnet arm は **一度も委譲する前に**小さい 2 つを
  読み終えている。当たる条文が無い。
  §2 の「関係質問の path は同じ invocation に渡す」は Agent 呼び出しの
  形の規則で、親が自分で抱える分については何も言っていない。

**よって文言は足りていなかった。** step 1 に次を足した:

> The order does not save a Read either: when one question spans several
> paths and any one of them routes to a worker, they all go in that
> invocation — don't read the small ones yourself first and delegate
> only the one that was denied.

`test_worker_resume.py` に到達性のテストを 1 件追加し、byte 上限は
7900 → 8200 に理由付きで引き上げた（文言は一語も削っていない）。

## 6. これで確かめられたこと・確かめられていないこと

確かめられたのは **条文の網羅**であって、**挙動**ではない。
本節までの作業はすべて保管済み transcript の再読解で、$0。
新しい文言が実際に親の Read を止めるかどうかは、
**live run を 1 本走らせない限り分からない。** 未測定である。

`release_eligible` の門は今回いじっていない。

## 7. 記録した逸脱

- §4.1 の事実誤認を同日中に訂正した（本記録冒頭の引用ブロック）。
  再判定の出力だけを見て「当時合格していた」と書き、同じ run 内に
  ある `verdicts/*.json` を読んでいなかった。以後、
  「当時どうだったか」を書くときは verdict を必ず突き合わせる。
- 設問自体は 1 つに固定し、transcript から他の量は読んでいない。
