# A案（逐語転記）の行動検証（2026-09-15、専用チェックアウト）

対象は `gold_confirmed` のみ。`reviews/gold-confirmed-2026-09-15.md` で
description へ移した保持義務を、**手順（逐語転記）として書き直した版**が
親の振る舞いを変えるかを測る。

## 1. 実行条件

| 項目 | 値 |
|---|---|
| チェックアウト | scratchpad 内の detached worktree（専用） |
| 固定コミット | `9c828e9`（`git status` は生成物の `.pyc` のみ） |
| ケース | `auto-explicit-multifile`、`compare-explicit-multifile` |
| モード | direct / haiku / sonnet / auto（`gold_confirmed` は委譲3モードのみ） |
| 周回 | 3 |
| 実行数 | 24（うち委譲18） |
| 実測費用 | $3.91（1.129 / 1.398 / 1.386） |

**課金測定前の必須確認**: 専用チェックアウトで判定器の selftest
（`python3 evals/compare/judge.py --selftest`）を通すこと。§1.1 の欠陥は
これを先に実行していれば起動前に判明した。

前回（`reviews/behaviour-measurement-2026-09-15.md`）は
**コミット＋保存差分**の構成だった。今回は実行経路に未コミット変更を
一切含まない。したがって前回との差は、文言変更だけでなく
**実行経路の違いも含む**。単独の因果効果は取れない。

### 1.1 HEAD が単独では動かなかった（測定前に判明、課金なし）

最初の起動は3周とも `judge selftest` で即時失敗した。

```
ImportError: cannot import name 'metadata_only_bash' from 'routing_checks'
```

`5f0271a` が `judge.py` 側の import だけをコミットし、
`routing_checks.metadata_only_bash` 本体をコミットしていなかった。
run.sh は作業ツリーの判定器を実行するため、汚れたツリーでは露見しない。
**コミットに固定した測定を行おうとして初めて出た欠陥**である。
当該関数のみを `9c828e9` でコミットして解消した（モデル実行前に
失敗しているため、この試行に課金は発生していない）。

### 1.2 チェックアウト側に残る既知の欠落（測定経路外）

| 事象 | 影響 |
|---|---|
| `evals/test_reader_call_contract.py` の4パス検査が `gen/small3/a.txt` を見つけられない | フィクスチャは run.sh が生成する。測定経路外 |
| `evals/test_review_hooks.py` が `plugin/hooks/write-hook-log` を要求 | 当該フックは主ツリーで未追跡。別機能のため今回は取り込まない |

また、未コミットの `cases.json` プロンプト改訂2件
（`auto-edit-grep-location`、`compare-edit-dense-lines`）は
チェックアウトに存在しない。いずれも今回の対象ではない。
同時に入っている `read_max_output_tokens` キーは未コミット版 run.sh
だけが読むため、コミット版どうしの組は整合している。

## 2. 結果

### 2.1 総合合否（母数つき）

| ケース/モード | pass | fail |
|---|---|---|
| auto-explicit-multifile/direct | 3 | 0 |
| auto-explicit-multifile/haiku | 0 | 3 |
| auto-explicit-multifile/sonnet | 0 | 3 |
| auto-explicit-multifile/auto | 2 | 1 |
| compare-explicit-multifile/direct | 3 | 0 |
| compare-explicit-multifile/haiku | 2 | 1 |
| compare-explicit-multifile/sonnet | 0 | 3 |
| compare-explicit-multifile/auto | 1 | 2 |

`gold_confirmed` は委譲3モードのみが対象で、direct 6実行は対象外
（6件とも pass）。委譲18実行のうち失敗は13件。

| 失敗の内訳 | 件数 |
|---|---|
| `gold_confirmed` のみ | 12 |
| `gold_confirmed` + `single_invocation` + `child_reads_once` | 1（周3 `auto-explicit-multifile/haiku`） |

したがって「全実行の失敗理由が `gold_confirmed` のみ」ではない。
他の契約検査にも1実行で3件同時の失敗がある。

### 2.2 `gold_confirmed` の成立回数（委譲モードのみ）

| ケース | haiku | sonnet | auto | 計 | 前回 |
|---|---|---|---|---|---|
| auto-explicit-multifile | 0/3 | 0/3 | 2/3 | **2/9** | 0/9 |
| compare-explicit-multifile | 2/3 | 0/3 | 1/3 | **3/9** | 6/9 |
| 合計 | 2/6 | 0/6 | 3/6 | **5/18** | 6/18 |

### 2.3 失敗の形（`confirmed_shape`）

| ケース | PASS | PARTIAL | NO-PATH | NO-ITEM |
|---|---|---|---|---|
| auto-explicit-multifile | 2 | 0 | 2 | 5 |
| compare-explicit-multifile | 3 | 3 | 3 | 0 |

`auto-explicit-multifile` の主な失敗は依然 **NO-ITEM**
（`confirmed:` 行が最終回答に1つも無い）。
`compare-explicit-multifile` では NO-ITEM が消え、
項目はあるが絶対パスを欠く／一部だけという形に寄っている。

### 2.4 他の検査

委譲側の契約は、`auto-explicit-multifile/haiku` の
`child_reads_once` と `single_invocation`（各 2/3、落ちたのは同じ周3の
1実行）を除いてすべて 3/3 で成立。`agent_type`・`child_no_body`・
`child_msg_cap`・`parent_no_full_read`・`deny_bypass`・`accuracy` は
全18実行で成立した。モデル解決は要求どおり（auto 経路は haiku 要求）。

## 3. 判断

**A案の行動改善は確認できない。**

- `auto-explicit-multifile` は 0/9 → 2/9。初めて成立した実行が出たが、
  2件とも auto モードに偏っており、n=9 では偶然と区別できない。
- `compare-explicit-multifile` は 6/9 → 3/9 と下がっている。
  ただし前回とは実行経路が違うため、**悪化を文言のせいにもできない**。
- 合計は **5/18 対 6/18**（前回は 0/9 + 6/9）。数値としては下である。
  今回の測定で言えるのは**改善が確認できなかった**ことまでで、
  「差がない」「前回と同等」ではない —— 同等性を確かめる設計の測定では
  ないため、差の不在を主張する根拠がない。

すなわち今回言えるのは、**逐語転記への書き換えでも
`gold_confirmed` の未遵守は解消しなかった**ということまでである。
改善の不在は確認できたが、悪化の不在も同等性も確認していない。

### 3.1 到達性は今回さらに否定材料が増えた

親が SKILL.md 本文を開いた実行は 18件中15件（前回の
`auto-explicit-multifile` は 9件中3件）。本文を開いた実行でも
`gold_confirmed` は落ちている。A案の義務は description にあり本文とは
独立なので、これは本文の到達性が上がっても当該検査が改善しないことを
示すに留まる。今回言えるのは、**この配置（description）と
この転記指示の組み合わせでは遵守を安定させられなかった**ことまでで、
文面一般について結論づけるものではない。

## 4. 残件

| 項目 | 状態 |
|---|---|
| `gold_confirmed` | 文言側の手段（移設・手順化）を2回試して未達。次は強制側（`reviews/enforcement-spec-2026-09-15.md` の枠組み、または B案の Stop フック仕様確認）を検討する段階 |
| Grep フック2件 | 設計済み・実装保留（今回の対象外） |
