# 実装 1次レビュー（2026-09-13）

対象: PR1 実装（`plugin/hooks/` 3 本、manifests、`scripts/build-zip.sh`、`evals/`）。基準: 設計書 §6〜§13（承認済み、hash `e553872`）。

判定: **条件付き合格 → 下記全件修正済みで合格**。レビュー中に実機で再現した欠陥はすべて本セッションで修正し、eval を拡張して回帰化した。

## 検出した欠陥（すべて修正済み）

| ID | 重大度 | 指摘 | 状態 |
|---|---|---|---|
| P-1 | Critical | `local s=$1 i=0 n=${#s}` は `s` 代入前に `${#s}` を展開し `n=0` → `scan_ops`/`tokenize` が入力を一切走査せず、Bash フックが全コマンドを通過 | 修正済（代入分離） |
| P-2 | Critical | `is_redirect_tok` の `>` を含む正規表現を `[[ =~ ]]` に直書き → syntax error で全 Bash が exit 2（fail-closed だが全ブロック） | 修正済（regex を変数経由） |
| P-3 | Major | 引用内文字で `have` が立たず、`cat 'large\|name.txt'` の被演算子が消失して pass | 修正済（quote/escape 開始で `have=1`） |
| P-4 | Major | 整数オーバーフロー: `head -c 10^19`・`Read limit/offset`・`TOKEN_SHUNT_*` env が int64 wrap で負/0 化 → 偽陰性 | 修正済（15 桁 cap で不達→既定値/全文閾値） |
| P-5 | Major | `--` end-of-options 未対応（`collect_file_args`/`ht_parse`/`pipe_tail_ok`）→ `cat -- -weird.txt` のダッシュ名実ファイルをフラグとして skip し偽陰性 | 修正済 |
| P-6 | Major | `N>` リダイレクト: `3>` を clean 判定し `cat large 3>out` が偽陰性。Spec 文言「直前が `2` でも `&` でもない」は stdout=fd1 の意図に対し不完全 | 修正済（`>` 直前の数字列を遡り fd=1 または無指定のみ clean。設計の意図に忠実な厳格化。文言修正は synthesis 参照） |
| P-7 | Major | パイプ末尾が解釈不能（未閉引用・`$(`・空）のとき `*) pass` に落下。§10-4 は先頭コマンドの全文閾値判定（fail-closed）を要求 | 修正済 |
| P-8 | Minor | detached `>\|` / `&>>` / `N>\|` が `is_redirect_op` 非対応 → リダイレクト先を被演算子として誤収集（保守方向） | 修正済 |
| P-9 | Minor | 全量判定が UNDETERMINED のとき deny reason に scan-budget 句が無かった | 修正済 |

## 適合確認済みの主要契約

- §8 出力契約: pass = 空 stdout + exit 0（`permissionDecision` を出さない）、deny = `hookSpecificOutput.permissionDecision` JSON（`jq -nc --arg` 生成でインジェクション安全）、jq 欠落・JSON 不正 = stderr + exit 2
- §9: `limit` 必須・正の整数・offset 単独 deny・`limit=1` 例外無し・両閾値判定・区間実測
- §10-4〜10-7: 引用考慮の演算子走査、パイプ末尾判定（`-c N≤MIN_BYTES` のみ通過）、複合全区間・全文閾値、`>`/`>>` 早期通過（特殊リダイレクト非存在時）、basename 判定、`VAR=` 前置除去
- worker allowlist: 完全一致、Bash 側は `bulk-reader` のみ
- 拡張子除外は Read 側のみ（`cat x.png` は免除しない）
- marketplace: 一段上レイアウト + `source: "./plugin"`、hooks.json exec form + timeout
- ZIP: `plugin.json` ルート、フック実行ビット

## 注意事項（修正不要・記録）

- P-10: `elapsed_ms` は走査後適用（§8.6 は走査中打ち切り）。バイト予算が作業量を束縛するため最終 deny 結果は同一。遅い FS の残余は §15 の fail-open 制約（フック timeout）と併記済み
- P-11: 共通コード（`int_env`/`now_ms`/`file_size`/`range_scan`/`full_file_verdict`/reason）を両フックに複写。設計 tree に lib が無いため許容だが、今後の変更は両方に同期必須
- P-12: `jq -e .` は JSON `null`/`false`/`0` を不正扱い → exit 2。spec リテラル
- P-13: 既存だが読み取り不可のファイルは probes 失敗 → pass → 実 Read が error。実害なし
