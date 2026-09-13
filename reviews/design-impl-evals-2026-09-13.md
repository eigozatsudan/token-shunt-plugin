# Design vs compare-eval implementation (2026-09-13)

正本: `docs/2026-09-12-token-shunt-design.md`（§3 成功 4–11、§13 比較 eval、§14 README、§26.5 A/B、§26.6 PR 順）。
対象: `evals/compare/*`、`README.md` の evals/shipping、`docs/distribution/README.md`。
オフライン検証: `python3 -m unittest discover -s evals/compare -p 'test_*.py'` → 49 ok。`judge.py --selftest` → 12 ok。実機 `claude` 比較は未実行（本レビューの範囲外）。

## Summary

比較 eval の骨格は設計に揃っている。必須 A/B ID は `cases.json` にあり、`run.sh` が全 `modes` を回す。前回レビューの 6 件（欠測合格、再試行誤判定、Edit 順序、生成検証の未実行、生成物持ち越し、曖昧バッチ未接続）は現行コードでは再現しない。`--setting-sources ""` + 空 cwd は §13 の OAuth 代替そのもので、`--bare` 不使用は README の説明どおり矛盾ではない。`selected_run_valid` と `release_eligible` は分離されている。`parent_input_tokens` は `result.usage` から取り、バイト推計では代用しない。isolation は UTF-8 バイト同士。deny 後の limit=350 連続 Read と `cat|head` パイプは selftest で fail になる。

README / 配布 README は 90% を製品削減率として書かず、cost unproven、release-ready ではない、jq 必須、allow 非出力、Claude 欠落は skip-but-not-release と明記する。PR3 の 48 実行未実装は、費用削減をうたっていないので出荷違反に数えない。

残る齟齬は、eval が設計上 fail であるべき transcript を通す経路契約の穴である。

`evals/compare/last-run.json` は実機失敗ログである（組織が Claude Code の subscription を無効化）。現行集計器が書く `selected_run_valid` / `release_eligible` / `parent_token_deltas` が無く、収録ケースは 23/29 で現行 `cases.json` より古い。合格の出荷証拠ではない。

## Previous 6 (re-verified)

| # | 当時の指摘 | 現行 |
|---|---|---|
| 1 | 欠測を合格 | マニフェスト必須。空計画・欠モード・欠ディスク/トークン/隔離証拠は fail。選択成功 ≠ `release_eligible` |
| 2 | 正当な Sonnet 再試行を拒否 / 不正再試行を未検査 | `check_routing`: 初回 Haiku、許可理由の 1 回 Sonnet、resume 禁止、前回結果到着 |
| 3 | Edit 後 Read で edit_flow 成立 | `edit_flow_errors`: 一意 Grep 結果 → 原文 targeted Read 成功 → Edit。先行 Edit は fail |
| 4 | 検証未実行 + complete 報告が合格 | `verification_errors`: 成果物ごとの親 Bash と scoped partial。制御入力の省略/complete は fail |
| 5 | モード間で生成 target が残る | 各モード前に `rm -rf "$TMP"`。オフラインテストで target/参照リセットを確認 |
| 6 | 曖昧バッチが未接続 | `reader-batch-ambiguous` が実行対象。境界 1 回と unconfirmed/partial を検査 |

## Issues

### Issue 1 -- Severity: bug
- File: evals/compare/cases.json:227
- Design: §13 compare-code-writer-no-ref（Agent 最終メッセージに生成コードが無い。fence または 20 行超の本文は fail。理由と参照パスがある）
- Description: ケースは `"fixtures": []` のまま `"child_no_body": true` だけを付ける。`judge.py` の `quote_leak` は fixture 本文との一致しか見ない（`judge.py:851-856`）。参照ファイルが無いので、子が Write せず最終メッセージに生成コード（fence や 20 行超）を載せても `child_no_body` は pass になる。理由・参照パスの有無も見ていない。ディスクの `target_absent` はファイルを作らなければ足りる。
- Suggestion: Agent `tool_result` に fence または 20 行超のコード本文が無いこと、および欠落した参照パスと理由が最終メッセージにあることを独立に fail にする。
- Status: open
- False-positive risk: low — 空 fixtures では `quote_leak` がループ 0 回で `(False, "")` を返す。設計の RED がそのまま通る。

### Issue 2 -- Severity: bug
- File: evals/compare/cases.json:442
- Design: §13 子→親テキスト（4000 文字超、または fixture 本文の 20 行超 / 2KiB 超の連続引用は fail）。§26.5 `reader-batch-evidence` は「本文キャップ」を path_ok に含む。
- Description: 正答側 `reader-batch-evidence` は `child_msg_max: 4000` だけで `child_no_body` が無い。`user.rb` の padding 行は 1 行約 120 バイトなので、21 行連続引用は 4000 字以内に収まる。同じ穴は `reader-bounds`（`cases.json:506`、キャップのみ）と `retry-policy`（`cases.json:524-534`、キャップも引用検査も無し）にもある。曖昧制御 `reader-batch-ambiguous` だけが `child_no_body` を付けている。
- Suggestion: bulk-reader 委譲の A 契約ケースに `child_no_body` と 4000 字キャップを揃える。`retry-policy` にも両方付ける。
- Status: open
- False-positive risk: low for `reader-batch-evidence`（表が本文キャップを明示）。medium for `retry-policy` / `reader-bounds`（主眼は再試行・探索 0 だが、§13 の委譲テキスト契約はモード共通）。

### Issue 3 -- Severity: bug
- File: evals/compare/cases.json:1027
- Design: §26.5 `auto-routing-boundaries` の path_ok は「§26.2 に一致」。16384 超は親が本文を取り込まず bulk-reader へ委譲する。
- Description: `auto-routing-boundary-16k-plus` の委譲 expect は `agent_type` と `child_msg_max` だけである。`parent_no_full_read` / `deny_bypass` / `child_reads_once` が無い。16385 バイトはフック閾値未満なので親の全文 Read は成功する。親がファイルを読んだうえで Agent を呼べば、gold `B16385-MARK` は親 Read 由来でも通り、§26.2 違反の transcript が path_ok になる。直前・一致ケース（`auto-routing-boundary-16k-minus` / `-equal`、`cases.json:968-999`）は `agent_zero` のみで、§26.5 が小仕事に求める「親の Read 成功」が無い。gold はファイル名から推測できる。
- Suggestion: plus 側に `parent_no_full_read`（または許可範囲外の成功 Read を deny_bypass 相当で fail）と child Read 1 回を付ける。minus/equal に `parent_reads` を付ける。marker を path から推測できない値にする。
- Status: open
- False-positive risk: medium — プロンプトの `{WMHINT}` は「If you delegate」と任意に読める。ただし expect は委譲必須であり、境界ケースの合格条件は §26.2 そのものなので、親の成功全文 Read を許すのは表と食い違う。

### Issue 4 -- Severity: suggestion
- File: evals/compare/cases.json:288
- Design: §26.5 `writer-verification-levels` — 親の検証・報告を実機確認。JSON parse のみは syntax+partial、最小チェックは minimal+partial、必須キー検査の成功だけ requirements。制御入力で誤完了・誤拒否を検出する。
- Description: 制御入力（欠キー JSON / 途中欠落 / 正当な末尾 fence）と scoped partial の検査は入った。一方 (1) 親に実行させる検証が製品コマンド（`jq empty` / 最小契約）ではなく `{JUDGE_DIR}/flow_checks.py --verify` であり、スキル手順に従った親は argv 不一致で fail し、eval ヘルパーだけ走らせた親は pass する。(2) requirements の成功経路が無い（プロンプトが requirements 主張を禁止する）。(3) 生成 JSON の `required_key` 有無は syntax ディスク検査では見ない。
- Suggestion: 親検証をスキルが指定するコマンドにし、必須キーを見る受入コマンドを 1 本足して requirements 成功と欠キーの誤完了を対にする。eval ヘルパーは runner 側に残す。
- Status: open
- False-positive risk: medium — 誤 complete と制御入力省略は既に fail になる。残るのは製品検証コマンドとのずれと requirements 正例の欠落。

### Issue 5 -- Severity: suggestion
- File: evals/compare/cases.json:918
- Design: §26.5 `auto-edit-grep-location` — Grep → 原本 targeted Read → Edit を正答ケースにする。Grep が曖昧な制御は非 Edit を期待し、正答ケースと分ける。
- Description: 正答ケース（誤ヒント + `render_header`）は `edit_flow` とディスク期待バイトで実装されている。曖昧 Grep で Edit しない制御ケースは `cases.json` に無い。
- Suggestion: 複数ヒットになる第二ケースを追加し、親 Edit 0 を path_ok にする。
- Status: open
- False-positive risk: low — 設計が正答と制御を分けると書いており、現行は正答のみ。

### Issue 6 -- Severity: suggestion
- File: scripts/doctor.sh:37
- Design: §7 doctor は `agent_type` に加え、呼び出し時モデル、Haiku/Sonnet 実モデル、effort、maxTurns の partial 終了を検証し、最低対応版を記録する。§14 は README に doctor（agent_type / FORCE / jq）を書く。
- Description: README の doctor 項目自体は書かれている。実装は jq、FORCE 警告、`claude --version`、plugin-load 時の agent 登録、stdin dump の手順案内まで。live dump 欠落は fail にしない、と明記しており、§7 のモデル/effort/maxTurns/最低版の記録は無い。
- Suggestion: 対応 CLI で呼び出し時 model / resolvedModel / effort / maxTurns partial を 1 回ダンプして版を README に記録する。未対応なら互換エラーにする（黙って弱めない）。
- Status: open
- False-positive risk: low as suggestion — §14 の README 必須文面は満たす。不足は §7 の doctor 範囲。

### Issue 7 -- Severity: suggestion
- File: evals/compare/cases.json:524
- Design: §26.5 `retry-policy` / `writer-bounds` — 初回 Haiku、許可理由の Sonnet 再試行 1、resume 0、writer は Read/Grep/Glob 合計 20・内容確認最大 16 ファイル、総起動 ≤ 4。§12 code-writer 最終メッセージ 800 字。
- Description: `retry-policy` は不正再試行を offline で落とすが、本ケースは `agent_calls_min: 1` なので初回 Haiku 成功（再試行 0）でも live 合格になる。再試行経路は実機必須ケースとしては未強制。`writer-bounds` は `child_tool_budget: 20` と `agent_calls_max: 4` だけで、800 字キャップ、16 ファイル上限、auto の Haiku→Sonnet 制約を見ていない。
- Suggestion: retry ケースは契約違反の第一応答を誘導するか、min 起動 2 を期待する制御入力を分ける。writer-bounds に `child_msg_max: 800` とファイル数上限、`retry_policy` または `expected_resolved_model` を付ける。
- Status: open
- False-positive risk: medium — 不正 resume / 2 回目 Opus は `check_routing` で落ちる。欠けているのは「再試行が実際に起きる」ことと writer の残りの上限。

## Notes (not issues)

- 必須 ID: A 14 + `reader-batch-ambiguous`、B の列挙 8 + `auto-routing-boundaries` を 7 ID に分割。いずれも `cases.json` にあり full run の `required` マニフェストに入る。ID 名の分割自体は欠落ではない。
- 起動フラグ: `-p --output-format stream-json --verbose --include-hook-events --forward-subagent-text --model sonnet --permission-mode acceptEdits` と `--add-dir` を両モードで共有。直接は `--plugin-dir` なし、委譲は `plugin/`。`--setting-sources ""` + `.claude` の無い一時 cwd は §13 OAuth 代替。
- hook_response を deny の一次証拠にしている（`compare-hook-deny-route`）。`TOKEN_SHUNT_HOOK_LOG` フォールバックと SubagentStop `agent_transcript_path` は未実装だが、無いときは fail（skip にしない）。
- 3 パス 1 起動、Grep→targeted Read→Edit、親 unittest + mutation、fixture リセット、欠測で出荷不可は実装済み。
- README §14: jq、allow 非出力、90% 非製品削減、cost unproven、env、画像/PDF/ipynb、比較 eval の隔離、Claude 欠落 skip、リリースには実機成功が必須。`docs/distribution/README.md` も費用未証明・PR2 ゲート待ち。
- PR3 48-run 費用スイート未実装は、README が費用削減をうたっていないので本レビューの出荷違反にしない。
- `last-run.json` は実機失敗（auth disabled）。現行コードの出荷ゲートを満たした記録ではない。
