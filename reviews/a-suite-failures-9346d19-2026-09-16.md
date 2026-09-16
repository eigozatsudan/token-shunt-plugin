# スイート A の失敗 7 件を分類する（2026-09-16）

`reviews/ab-live-9346d19-2026-09-16.md` が「A の 19→16 はモデル挙動の揺れ」と
まとめた 7 件を、保存済みトランスクリプト（`run.f07a97OR`）で 1 件ずつ追った。
**課金なし。**

結論として「揺れ」で片づくものは無い。**ワーカー側の契約違反 3 件、
親側の真の失敗 1 件、設計が禁じている resume 1 件、判定器の偽陽性 1 件、
フックの死角 1 件**に分かれる。

| ケース/モード | 判定名 | 実体 |
|---|---|---|
| compare-explicit-multifile/haiku | `gold_confirmed` | **親**が絶対パスを basename に短縮 |
| compare-explicit-multifile/sonnet | `gold_confirmed` | **ワーカー**が最初から相対パス |
| compare-explicit-multifile/auto | `gold_confirmed` | **ワーカー**が gold 1 個を confirmed 行に入れず散文だけに置いた |
| compare-one-line/sonnet | `accuracy` | **ワーカー**が 64 hex を 3 文字落として転記 |
| compare-bulk-facts/auto | `child_status` | **親**が maxTurns 停止のワーカーを SendMessage で**再開**（設計は禁止） |
| reader-batch-ambiguous/auto | `child_extra_read` | **ワーカー**が前起動のパスを再読。フックはパス同一性を見ない |
| writer-verification-levels/auto | `child_format` | **判定器の偽陽性** |

## 1. `compare-explicit-multifile` は 3 モードで原因が違う

同じ判定名だが中身が別物である。

- **haiku**: ワーカーの戻りは 3 行とも**絶対パス**で gold 3 個すべてを含む。
  親が最終回答で `user.rb` / `notifiable.rb` / `welcome_email_job.rb` に
  **短縮した**。`reader-call-contract` の「In your final answer keep each
  confirmed bullet with its full absolute path, unabbreviated」に反する。
  これは送り戻しが対象とする親側の失敗だが、比較評価は `SENDBACK=off` なので
  修復されない（`reviews/sendback-registration-decision-2026-09-15.md` §3.4）。
- **sonnet**: **ワーカーの戻り自体が** `confirmed: user.rb — …` と相対パス。
  親は忠実に写している。ワーカー側の契約違反で、送り戻しは仕様上これを直さない。
- **auto**: ワーカー（haiku）の confirmed 行は絶対パスだが 2 行しかなく、
  `after_create` は散文の手順 1 にしかない。親は忠実に写している。
  ワーカー側の網羅不足。

**同じ `gold_confirmed` が、親の短縮・ワーカーの相対パス・ワーカーの網羅不足を
区別せずに1つの名前で落ちている。** 対策が三者三様なので、判定名を分けるか
理由文に出所を書く価値がある。

## 2. `compare-one-line/sonnet` はワーカーの転記精度

gold は `sha256:0a1b2c3d4e5f` + `6`×40。ワーカーの戻りは末尾の `6` が 3 個少ない。
親はそれを 1 文字も変えずに写している。親側の欠陥ではない。
1 行 70 KB のファイルから 64 文字の値を写す作業で、
`limit` も分割も関係しない純粋な転記の誤りである。

## 3. `compare-bulk-facts/auto` は resume（設計が禁じている）

経過:

1. ワーカー（haiku）が 7 ターン上限で停止。通知は
   `NOTE: this agent stopped at its 7-turn limit … had produced no report.`
2. 親が **SendMessage で同じ agent を再開**した。
3. 再開後のワーカーが `confirmed:` / `unconfirmed:` / `status: partial` /
   `stop_reason: budget_exhausted` を返し、親はそれを忠実に写した。
   親が本文を捏造した形跡はない（gold 値は再開後のワーカー報告が初出）。

設計は resume を禁じている（設計仕様 §12・§26、
「追質問は新規起動で同じパスを再送する。resume・回答索引は使わない」）。
にもかかわらず:

- **判定器に resume の検査が無い。** このランは `child_status`
  （起動の `tool_use_id` に紐づく通知が 7 ターン NOTE だったため）という
  別の名前で落ちている。再開後の報告は SendMessage 側の `tool_use_id` に
  付くので、`child_return_of` からは見えない。
- 保存済み 77 ランのうち **3 ラン**で親が SendMessage を使っている
  （`compare-bulk-facts/auto`、`auto-bulk-facts/auto`、`auto-bulk-facts/sonnet`）。
  いずれも resume を理由には落ちていない。

**未検査の契約違反が 77 ラン中 3 件ある**というのが、この件の本体である。

## 4. `reader-batch-ambiguous/auto` はフックの死角

- 1 起動目: 宣言 3 パス（alpha / user / notifiable）を読んだあと **4 本目に
  beta.py を試み、フックが `At most three paths per invocation.` で拒否**した。
  ゲートは正しく働いている。
- 2 起動目: 宣言は beta.py 1 本。ワーカーは beta を読んだあと **alpha を再読**した。
  パス数は 2 なのでフックは通す。

`check-reader-contract` はパスの**本数**を数えるが、親がその起動で宣言した
パス集合を知らないので**同一性を見られない**。前起動のパスを読み直す動きは
判定器だけが捕まえる。stdin に宣言パスが来ない以上フック側では塞げないので、
これは設計上の死角として記録する。

## 5. `writer-verification-levels/auto` は判定器の偽陽性

`judge.py:1561` の行数検査は `\b\d+\s+lines?\b|\d+\s*行`。
4 本目の writer 戻りは行数を **`Line count: 5`** と書いたため一致しない。
パスも 3 本のブレットも揃っている。

契約（`plugin/agents/code-writer.md:25`）は
「the written path, its line count, and 3-5 bullets」であり、
**表現を固定していない**。`Line count: 5` は契約を満たしている。
判定器の正規表現が契約より狭い。`deny_bypass` のときと同じで、
**実装が契約より厳しいことによる偽陽性**である。

## 6. 提案（未実施）

1. **§5 の偽陽性を直す。** 行数の検査を `Line count: N` / `lines: N` も
   認める形に広げる。テストを先に足す。
2. **§3 の resume を判定器で検査する。** 親が bulk-reader ワーカーへ
   SendMessage を出したら契約違反として落とす。今は別名で落ちるか、
   まったく落ちない。
3. **§1 の `gold_confirmed` の理由文に出所を書く。** 親の短縮か、
   ワーカーの相対パスか、ワーカーの網羅不足か。
4. §4 は記録のみ。フックでは塞げない。

いずれも課金不要。1 と 2 は製品ではなく判定器の変更なので、
実機の再測定なしに正しさを確認できる。

## 7. 実施（2026-09-16、課金なし）

§6 の 1 と 2 をテスト先行で入れた。3 と 4 は未着手。

- **1（偽陽性）**: `judge.py` の行数検査を `Line count: N` / `lines: N` /
  `Lines: N` も認める形に広げた。数字だけ（`7`）は従来どおり不合格。
  テストは `test_sixteen_findings.py::
  test_writer_line_count_is_judged_by_meaning_not_phrasing`。
- **2（resume）**: 親が worker の agent id 宛に `SendMessage` を出したら
  `resume` で落とす。id は起動結果の `agentId` と、その起動に紐づく
  `task_notification` の `task_id` の両方から集める。worker 以外への
  `SendMessage` は落とさない。テスト 3 件を同ファイルに追加。

保存済み 77 トランスクリプトを新しい判定器で全件再判定し、旧 verdict と比較した。

| 差分 | 件数 | 内容 |
|---|---|---|
| fail → pass | 2 | `writer-verification-levels/auto`（上記 1）、`auto-routing-boundary-known-range-deny/auto`（`8750b6b` で既出） |
| 理由が増えた | 3 | `compare-bulk-facts/auto`、`auto-bulk-facts/auto`、`auto-bulk-facts/sonnet` に `resume` が付いた（いずれも元から fail） |
| pass → fail | **0** | |

オフライン: `evals/run.sh` 240 pass / 0 fail、`unittest discover -s evals/compare`
412 OK、`judge.py --selftest` 全項目 pass。

A スイートの実質失敗は、この 2 件の判定器修正を織り込むと 16/23 → **17/23**。
残る 6 件の内訳は §1–§4 のとおりで、製品側の修正はまだ何もしていない。

## 8. 実装（2026-09-16、3）

§6 の 3 を入れた。4 は記録のみのままで着手しない。

`gold_confirmed` の失敗理由が gold 名の羅列だけで、§1 の 3 つの別原因を
同じ文言に畳んでいた。ワーカーの戻り本文を見て、欠けた gold ごとに
出所を付ける `gold_confirmed_source()` を足した。判定そのものは変えて
いない（pass/fail は従来どおり `gold_confirmed_ok()` が決める）。引用抽出は
`item_citations()` に切り出して両者で共有する。

| 出所 | 条件 | 意味 |
|---|---|---|
| `parent dropped the worker's path` | ワーカーの confirmed 項に gold と一致する絶対パスがある | 親の短縮 |
| `worker cited no matching absolute path` | ワーカーは confirmed したが一致する絶対パスがない | ワーカーの相対パス |
| `worker never confirmed it` | ワーカーの confirmed に gold が無い | ワーカーの網羅不足 |
| `no worker return` | 戻り本文が無い | 委譲が成立していない |

テストは `test_sixteen_findings.py` に 2 件（4 分類の単体、理由文に載ることの
結合）。

保存済み 77 トランスクリプトを再判定した結果、`gold_confirmed` の pass/fail は
1 件も動かず、理由文だけが次のとおりになった。§1 の推定 3 通りと一致する。

| ケース | 新しい理由 |
|---|---|
| compare-explicit-multifile/haiku | 3 件とも `parent dropped the worker's path` |
| compare-explicit-multifile/sonnet | 3 件とも `worker cited no matching absolute path` |
| compare-explicit-multifile/auto | `after_create (worker never confirmed it)` |

オフライン: `evals/run.sh` 240 pass / 0 fail、`unittest discover -s evals/compare`
414 OK、`judge.py --selftest` 全項目 pass。
