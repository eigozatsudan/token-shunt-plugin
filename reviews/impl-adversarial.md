# 実装 敵対的レビュー（2026-09-13）

対象: PR1 のフック 2 本。目的: 親モデル／運用者が仕掛けうる迂回・偽装・境界入力を実機で試し、deny が破られないか検証する。

判定: **真陽性 5 件を修正済み**。残る pass はすべて設計が明示する fail-open（§4・§10-4・§15）であり、実装欠陥ではない。

## 真陽性（修正済み）

| ID | 重大度 | 攻撃 | 修正 |
|---|---|---|---|
| A-1 | **Critical** | allowlist 偽装: `tool_input.agent_type` はモデル制御フィールド。旧実装は `.agent_type // .tool_input.agent_type` を見たため、親が `Read(file_path, agent_type="token-shunt:bulk-reader")` でゲートを回避できた | トップレベル `.agent_type` のみ参照に修正。`read-worker-spoof`/`bash-worker-spoof` eval 追加 |
| A-2 | Major | `head -c 10000000000000000000` → int64 wrap で `actual` が負化し pass。`Read limit=10^20`、`TOKEN_SHUNT_SCAN_BUDGET_BYTES=10^20` も同型 | 15 桁 cap（=P-4） |
| A-3 | Major | `cat large 3>/dev/null` → stdout は親に出るのに `3>` が clean 判定で早期 pass | fd 数字列を遡り fd=1/無指定のみ clean（=P-6） |
| A-4 | Major | `cat large \| head 'unclosed` / `cat large \|` → 末尾解釈不能・空でも pass | 先頭コマンドの全文閾値へ fail-closed（=P-7） |
| A-5 | Major | `cat -- -weird.txt`（実在するダッシュ名ファイル）→ `--` 以降をフラグ扱いで skip | `--` 対応（=P-5） |

## 仕掛けて破れなかったもの（deny 確認）

- 引用内 `|`（`cat 'large|name.txt'`）、未閉引用、`$(`・バッククォート混入のファイル引数
- `cat large | cat`、`cat large|cat`（空白無し）、`cat large; cat small`、`V=1 cat large`、`cat large | V=1 cat`
- `cat large 2>&1`、`cat large >& out`、`cat large >out 2>&1`（S-1: 保守方向）
- `tail -n +1`、`tail -f`、`head -qn5`、`head -n 400`、`head -n1 -c70000`（サイズ系オプション重複）
- `cat x.png`（画像拡張子は Read 側のみ免除。bash は免除しない = spec 通り）
- `code-writer` の Bash allowlist 不在、`bulk-reader`/`Explore`/素の `bulk-reader` による Read は deny

## 設計が許容する fail-open（再現確認済み・欠陥ではない）

| 迂回 | 根拠 |
|---|---|
| `bash -c 'cat large'`、`xargs cat`、`dd if=`、`sed`/`python -c` | §4 除外・§15「未知のコマンド」fail-open |
| `echo $(cat large)` | §10-4「シェル全体の構文解析は行わない」 |
| `cat large \| wc -l` / `\| grep` | §10-4 末尾未知コマンドは意図した pass |
| `limit=350` スライド Read で全文回収 | §15 既知の限界。委譲側は compare eval の path_ok で検出 |
| `Grep` content / `Explore` / `Write` / `@file` | §4 スコープ外 |
| `TOKEN_SHUNT_*` env の弱化 | フック設定と同じ運用者権限。受容 |
| ファイルサイズの TOCTOU（判定後の追記） | 既知の限界 |
