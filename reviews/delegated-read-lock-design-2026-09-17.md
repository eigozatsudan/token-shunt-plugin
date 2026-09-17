# 機構側で止める・設計（2026-09-17）

`reviews/parent-no-read-shape-2026-09-17.md` を受けて、条文ではなく
hook で止める側の設計。**まだ実装していない。走行もしていない（$0）。**

## 0. 先に言うべきこと

**機構は、起きている漏れの過半には届かない。**

31 件の漏れた path を、hook が使える情報で分類した:

| hook が使える手掛かり | 件数 |
|---|---|
| A: その path 自身が worker に渡っていた | 6 |
| B: 16 KB 超の file を Grep で位置特定 → 部分 Read | 5 |
| **C: どちらでもない** | **20** |

C の 20 件の中身は **129 bytes と 131 bytes の 2 ファイル**である。
時系列で見ても、**27/31 は委譲の前か、委譲が一度も無い arm**で起きている
（launch 前 10、launch 無し 17、launch 後 4）。

**129 bytes の Read を、byte を見る hook が拒否できる理屈は無い。**
size でも、hook 発火条件でも、累積予算（16,384）でも届かない。
C を違反にしているのは case の期待（3 つとも worker へ）だけである。

したがって本設計は **A・B を塞ぐもの**であり、
**C は機構では解けない**。C をどうするかは
`reviews/parent-no-read-shape-2026-09-17.md` §4 の
「case は何を測っているのか」に戻る。ここで隠さずに書いておく。

## 1. hook が見られるもの（既存の前例）

- `reader_scope.py`: stdin の `transcript_path` と `agent_id` から
  **worker の launch prompt を読み**、宣言された path 集合を復元している。
- `check-reader-contract`: `(session_id, agent_id)` を鍵に
  **session をまたぐ state file** を持ち、Read を直列化している。
- `sendback_session.py`: 親の session jsonl と
  `subagents/agent-*.jsonl` の関係を既に解いている。

**必要な材料は全部そろっている。** 新しい観測手段は要らない。

## 2. Lock A — 委譲済み path の Read を拒否

- **書く側**: `check-worker-launch`（PostToolUse / Agent・Task）が、
  launch が成功したとき、その prompt から `reader_scope` と同じ方法で
  絶対 path を取り出し、`(session_id)` を鍵にした state file へ足す。
- **読む側**: 新しい PreToolUse / Read hook が、**親の Read のみ**
  （`agent_id` が無い呼び出しのみ）を見て、対象が state に有れば拒否する。
- **拒否文**: 「この path は worker に渡っている。答えはその報告である。
  続きが要るなら同じ path で新しい worker 呼び出しを立てる」。
  `check-file-size` の拒否文と違い、**targeted Read を代替として案内しない。**

### 2.1 編集契約との衝突

`check-file-size` が targeted Read を通すのは step 4 の編集契約のためで、
Lock A はそこを塞ぐ。現行の case を確認したところ、
**同じ path を委譲しかつ編集する case は 0 件**である
（`child_reads_once` と `parent_targeted_read`/`edit_flow`/`disk_check` の
積は空）。

よって v0.1 では **「委譲した path をその後で親が編集する」を
out of scope と宣言する**。SKILL.md 末尾に既にある
「Out of scope in v0.1」と同じ扱いにする。
黙って壊すのではなく、**書いてから塞ぐ。**

### 2.2 Lock A' は採らない

「worker を立てた後は親の Read を一切拒否する」案も検討したが、
実データで届くのは **4/31** だけで、Lock A の 6/31 より狭い。
副作用（無関係な file の Read まで止まる）の割に得るものが無い。

## 3. Lock B — 範囲探索の禁止を機構にする

SKILL.md の description は既にこう禁じている:

> never use it to fetch the answer or to discover a range and claim the
> known-range exception

`run.WYiYiQXm` の haiku arm はこれを踏んでいる。順に、
22,546 B の `user.rb` に `output_mode=content` の Grep →
`check-grep-bounds` が拒否 → **境界付きで掛け直して通過** →
529 行目を特定 → `Read(offset=525, limit=15)`。
**hook は境界付き Grep を設計どおり通す。**

- **書く側**: `check-grep-bounds` が、通した content Grep について
  `(session_id, path)` と返した行番号を state に残す。
- **読む側**: PreToolUse / Read が、**16,384 B を超える file**への
  親の targeted Read を、その file について直前に content Grep の
  記録が有る場合に拒否する。
- **通すもの**: Grep の記録が無い targeted Read（事前に分かっていた
  既知範囲）はそのまま通す。`files_with_matches` は位置を返さないので
  記録しない。

境界は 16,384（skill の routing 閾値）であって 65,536 ではない。
65,536 は Read hook の閾値で、今回の file はそれを下回るから
`check-file-size` は最初から出番が無い。

## 4. 見込みの覆い（実データ 31 件に対して）

| | 件数 |
|---|---|
| Lock A | 6 |
| Lock B | 5 |
| 残り（C） | 20 |

**漏れ率 21.7% が 14% 程度に下がる見込み**にすぎない。
これは予測であって測定ではない。実際の効果は、実装後に
`reviews/parent-no-read-rate-design-2026-09-17.md` と同じ 20 run で
測らなければ分からない（約 $9、残枠 $21.6）。

## 5. 実装前に書くテスト

`plugin/hooks/` の既存の作法に合わせ、**テストを先に書く**:

1. Lock A: 委譲済み path への親 Read が拒否される。
2. Lock A: **worker 自身**の Read は拒否されない（`agent_id` 有り）。
3. Lock A: 委譲していない path は拒否されない。
4. Lock A: launch が失敗した Agent 呼び出しでは state に入らない。
5. Lock A: state file が読めないときは**何も拒否しない**
   （`reader_scope` の「Nothing known means nothing denied」に倣う）。
6. Lock B: 16 KB 超 + 直前の content Grep + targeted Read → 拒否。
7. Lock B: Grep の記録が無ければ通す。
8. Lock B: 16 KB 以下の file は対象外。
9. Lock B: `files_with_matches` は記録しない。
10. 拒否文が targeted Read を代替として案内していないこと。

## 6. やらないこと

- SKILL.md の 4 度目の書き直しはしない。届く先が増えない。
- `parent_no_read` を case から外さない。release gate は
  「そのまま止める」と決まっている。
- C の 20 件をこの設計で解決したことにしない。
