# 設計・実装照合の偽陽性チェック（2026-09-13）

正本: `docs/2026-09-12-token-shunt-design.md`。下書きと過去レビューは現行要件にしない。
一次レビュー: `reviews/design-impl-hooks-2026-09-13.md` / `design-impl-skills-2026-09-13.md` / `design-impl-evals-2026-09-13.md`。
本ファイルはそれらの指摘をコードで再確認した裁定である。実装は変更していない。

検証: `evals/run.sh` 98 pass / 0 fail。`python3 -m unittest discover -s evals/compare -p 'test_*.py'` 49 ok。`judge.py --selftest` は evals レビュー側で 12 ok。実機 Claude 比較は未実行（`last-run.json` は組織が subscription を無効化した失敗ログ）。

## 結論

フック・マニフェスト・ZIP・スキル本文の主契約は設計と一致する。前回の評価 6 件（欠測合格、再試行誤判定、Edit 順序、生成検証、生成物持ち越し、曖昧バッチ未接続）は現行コードでは再現しない。

残る真陽性は評価の経路穴 3 件と、指示文・README・doctor の欠文である。スキル/エージェントの「bug」3 件は文面の係りであり、実行時契約を壊すコード欠陥ではないので降格した。

## 一致している範囲（再掲しない）

- フックアルゴリズム（jq fail-closed、env 既定、トップレベル `agent_type` 完全一致、`limit=1` 例外なし、`undetermined=deny`、除外拡張子、空 stdout 通過、Bash の引用/パイプ末尾/複合先行/stdout リダイレクト、`check-jq` が jq を呼ばない）
- marketplace / plugin.json / hooks.json exec form / ZIP 実行ビット
- スキルに `agent:` / `context: fork` なし。`--worker-model` 必須文面。3 パス 1 Read、編集契約、検証段階、agent frontmatter
- A/B 必須 ID は `cases.json` にある（`auto-routing-boundaries` の 7 分割を含む）
- `--setting-sources ""` + 空 cwd は §13 の OAuth 代替。`--bare` 不使用は README どおり矛盾ではない
- 90% を製品削減率と書かない。費用未証明。`release_eligible` と選択実行は分離
- PR3 の 48 実行未実装は、費用削減をうたっていないので現行の出荷違反にしない

## 真陽性

### 1. [bug] 参照なし生成で、子がコードを返しても評価が通る

- 一次: evals Issue 1
- 箇所: `evals/compare/cases.json` の `compare-code-writer-no-ref`（`fixtures: []` + `child_no_body`）、`judge.py` の `quote_leak`
- 設計: §13「Agent 最終メッセージに生成コード（fence または 20 行超の本文）が無い。理由と参照パスがある」
- 確認: `quote_leak` は fixture 本文との一致だけを見る。fixture が空だとループ 0 回で `(False, "")`。fence 検出も理由・参照パス検査も無い。`target_absent` はファイルを作らなければ足りる
- 裁定: 真陽性。設計の RED がそのまま通る
- 修正: fixture 非依存で fence / 20 行超を落とし、欠落参照パスと理由を必須にする

### 2. [bug] 16KiB 超の境界で、親の全文 Read 成功が path_ok になる

- 一次: evals Issue 3
- 箇所: `auto-routing-boundary-16k-plus` の expect が `agent_type` と `child_msg_max` のみ
- 設計: §26.2 / §26.5「16384 超は本文を親へ取り込まず bulk-reader」。16385 バイトはフック閾値未満なので全文 Read は成功する
- 確認: `parent_no_full_read` / `child_reads_once` / `deny_bypass` が無い。親が読んだうえで Agent を呼べば gold `B16385-MARK` は親由来でも通る。minus/equal は `agent_zero` だけで `parent_reads` が無く、gold がファイル名から推測できる（`b16383.txt` → `B16383-MARK`）
- 裁定: 真陽性。境界ケースの合格条件は §26.2 そのもの
- 修正: plus に親の成功全文 Read 禁止と子 Read 1 回。minus/equal に親 Read 成功。marker を path から推測できない値にする

### 3. [bug] バッチ正答ケースに本文隔離検査が無い

- 一次: evals Issue 2（`reader-batch-evidence` 部分）
- 箇所: `child_msg_max: 4000` のみ。`child_no_body` なし
- 設計: §26.5 は本文キャップを path_ok に含む。§13 は 20 行超または 2KiB 超の連続引用を fail
- 確認: `user.rb` の padding は連続する一意行で、21 行 ≈ 2500 字で 4000 字以内に収まる。`reader-bounds` もキャップのみ
- 裁定: 真陽性（`reader-batch-evidence` / `reader-bounds`）。`retry-policy` まで同じ穴とするのは主眼が再試行なので降格（下記）
- 修正: bulk-reader 委譲の A 契約に `child_no_body` と 4000 字を揃える

## 真陽性（suggestion）

| # | 一次 | 内容 | 裁定 |
|---|---|---|---|
| 4 | skills 1 | code-writer の 16 ファイル / 20 回が「既存 target を Read」の括弧に係る | 文面の係りは事実。新規 target 本線では上限が読み取れない。`writer-bounds` は 20 回を見るので false-pass ではない。bug から降格 |
| 5 | skills 2 | bulk-reader が status を 4000 字の内側と書いていない。強制停止時 partial も無し | code-writer だけ「inside the 800」と明記。評価は結果全体を数えるので、従うと超過しうる。bug から降格 |
| 6 | skills 3 | bulk-reader に走中の Shared cap / 上限後 partial / 別 agent 名禁止が無い | 起動前の 4 回制限はある。12 パス開始後の Sonnet 再試行が 5 回目になり得る。code-writer 側にはある。bug から降格 |
| 7 | skills 4 | README Skills 節に maxTurns 4 と、関連探索・再利用が v0.1 対象外である一文が無い | §14 必須文の欠文。本体にはある。真陽性 |
| 8 | hooks 1 / evals 6 | doctor が §7/§12 の実モデル・effort・maxTurns partial・最低版記録をしない | §14 の短い doctor リスト（jq / FORCE / agent_type 案内）は満たす。§7 の検証契約は未実装。suggestion のまま |
| 9 | evals 4 の一部 | `writer-verification-levels` に requirements 成功の正例が無い | 制御入力の誤 complete は既に fail。欠けるのは「必須キー検査の成功 → requirements」の片側。真陽性 |
| 10 | evals 5 | `auto-edit-grep-location` に Grep 曖昧 → 非 Edit の制御が無い | 設計が正答と制御を分けると書いており、現行は正答のみ。真陽性 |
| 11 | evals 7 の一部 | `writer-bounds` が 16 ファイルと 800 字を見ない | 20 回と起動 ≤4 はある。残りの上限が未検査。真陽性 |

## 偽陽性・降格・対象外

| 指摘 | 裁定 | 理由 |
|---|---|---|
| `--bare` 不使用 | 偽陽性 | §13 の OAuth 代替そのもの。README が CLI 2.1.x の理由を書いている |
| `auto-routing-boundaries` を 7 ID に分割 | 偽陽性 | 入力（16KiB 直前/一致/直後、49/50 行、既知区間 deny）は全部実行対象 |
| PR3 の 48 実行が無い | 対象外 | README は費用削減をうたわない。§26.6 の PR3 |
| 走査時間を awk 後に適用 | 対象外 | §15 の timeout fail-open 残差。hooks レビューも再掲していない |
| `3>` を早期通過にしない | 対象外 | 設計文言は曖昧。実装は stdout のみで fail-closed。過去レビューで受容 |
| 15 桁整数 cap | 対象外 | wrap 回避。設計ケースの合否は変えない |
| 未知末尾パイプの通過 | 対象外 | §4 / §15 の意図した fail-open |
| evals Issue 4 (1) 親検証が `flow_checks.py` | 偽陽性 | 本文を stdout に出さないための計測用。製品コマンド不一致だけで設計違反にはしない |
| evals Issue 7 の「retry-policy は min 2 にせよ」 | 偽陽性 | 初回 Haiku 成功は方針どおり。不正 resume / 超過再試行は offline で落ちる。欠けているのは正例の実機強制であり、違反の false-pass ではない |
| evals Issue 2 の retry-policy 部分を bug 扱い | 降格 | 主眼は再試行。本文契約は batch-evidence 側を bug に残す |
| skills 1–3 の Severity: bug | 降格 | 指示文の係り。フックや判定器が設計の deny/pass を逆転しているわけではない |
| `last-run.json` の失敗を実装齟齬とする | 対象外 | 認証無効。README は release-ready ではないと明示 |

## 未検証

- 実機 A/B 比較（この環境では Claude Code の subscription が無効）
- `result.usage` が対象 CLI で親のみの累積であることの照合（前回レビューと同じ保留）
- doctor の live dump（認証オフでは実行不能。欠落を fail にしない方針は README どおり）
