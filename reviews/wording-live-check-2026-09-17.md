# 新文言が親の Read を止めるかの確認・結果（2026-09-17）

事前登録: `reviews/wording-live-check-design-2026-09-17.md`（`426b780`）。
行: `reviews/data/wording-live-check-2026-09-17.csv`（3 行）。

## 0. 走行

**固定 commit `426b780`。** worktree `/tmp/ts-wl` を detach で固定、
`git status` は空、その中で `judge.py --selftest` 全項目 pass を確認。
走行前 `spend.py --cap 3 --reserve 1.20` → `0.0000`、rc=0。

`SUITE=B`、`SLOTS=auto-explicit-multifile/{haiku,sonnet,auto}`。
run は 1 本、run dir は `run.UIXaDr2A`。
**本段階 $0.5203**（枠 $3）。累計 約 **$118.8 / 上限 $150**。

## 1. 結論

**文言はまだ足りていなかった。**

| mode | `parent_no_read` | cost |
|---|---|---|
| haiku | pass | $0.1057 |
| sonnet | pass | $0.2065 |
| **auto** | **FAIL** | $0.1481 |

事前登録 §3 の読み方どおり、「1 つでも FAIL なら文言はまだ足りない」。
3/3 pass ではないので、直ったかどうかの議論には入らない。

## 2. FAIL の形

`auto` arm の親の tool 呼び出しは、順に:

```
Bash  wc -c user.rb notifiable.rb welcome_email_job.rb
Read  concerns/notifiable.rb
Read  jobs/welcome_email_job.rb
Agent "Read the file .../user.rb in full ..."
```

**deny は一度も出ていない。** metadata で 3 つとも測り
（ここまでは step 1 のとおり正しい）、小さい 2 つを親が読み切り、
大きい `user.rb` **だけ**を worker に渡している。

archive の `run.mnVnW1FU` sonnet arm と**同じ形**で、
違いは deny の有無だけ。あちらは `user.rb` の Read が hook に
拒否されてからこうなった。今回は拒否される前に自分で判断してこうした。

## 3. なぜ新文言が届かなかったか

`66a952f` で入れた条文はこう終わっていた:

> ... they all go in that invocation — **don't read the small ones
> yourself first and delegate only the one that was denied.**

前半で順序の条件を外したのに、**末尾で deny の条件を入れ直していた。**
今回の arm には denied な path が無いので、文末の禁止は誰も指していない。
`c87055a` で直したはずの欠陥（規則を deny に条件付ける）を、
同じ規則の尻尾で再発させていた。

もう一つ、step 1 の small-task check
（「16384 bytes 以下で hook を通るなら親が答える」）を
**path ごとに**読むと、小さい 2 つを親が読むのはむしろ正しい。
どちらが優先するかを条文が言っていなかった。

## 4. 入れた修正

```
The order does not save a Read either, and neither does the small-task
check above: when one question spans several paths and any one of them
routes to a worker, every path of that question goes to the worker in
that invocation. A path being small enough to keep is not a reason to
keep it — split that way the parent ends up holding body the worker was
there to hold, and the relationship answer gets stitched out of two
contexts, which §2 forbids.
```

- deny という語を条文から完全に外した。テストで
  `assertNotIn('denied', ...)` を条文範囲に掛けてある。
- small-task check との優先順位を明示した。
- byte 上限は 8200 → 8500 に理由付きで引き上げ（文言は削っていない）。

**この修正は測っていない。** 同じ設問でもう 1 本走らせない限り、
今度こそ届くかどうかは分からない。

## 5. 見たが結論に使っていないもの（逸脱の記録）

- **`isolation` が 3 arm とも fail した。** `direct=None` が理由で、
  direct arm を billing しない設計の当然の帰結である。設問は
  `parent_no_read` 一つなのでこれは使っていないが、
  **この slot 構成では arm の総合 verdict は原理的に pass しない**。
  総合 verdict を見る設計なら direct arm も要る、という設計上の 教訓
  として残す。
- `haiku` arm の `gold_confirmed` fail（`parent dropped the worker's
  path`）と `auto` arm の `single_invocation` fail は目に入ったが、
  中身は読んでいない。別の設問である。
- 設問は増やしていない。
