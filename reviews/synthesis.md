# レビュー突合（2026-09-12）

1次: Critical 4 / Major 7
2次: Critical 1 / Major 6
敵対: Critical 4 / Major 10

3本一致の Critical: jq 欠落は現行 Claude Code で fail-open（exit 2 以外はツールが通る）。

## 採用する修正（推奨）

| ID | 指摘 | 裁定 |
|---|---|---|
| jq | 3本 Critical | **fail-closed**: jq 無し・JSON 不正は stdout 空 + exit 2。eval 必須。Python 化は任意（jq 必須のまま可） |
| agent_type | 1次 C2/C3, 2次 M2, 敵対 M5 | **同名のまま**。呼び出しと allowlist は完全一致 `token-shunt:bulk-reader` / `token-shunt:code-writer` のみ。suffix マッチ禁止。スキルに `agent:` を固定 |
| head -n | 1次 C4, 2次 M3 | **N≤閾値なら allow**。記事のパーサバグは踏襲しない。フラグ無し head/cat はファイル行数 |
| offset/limit | 1次 M1, 敵対 C2 | **limit 必須かつ limit≤閾値**。offset 単独は deny |
| marketplace | 2次 M4, 1次 M6 | **一段上**。`source: "./plugin"`。ZIP 一次は `plugin/` のみ |
| worker hooks | 2次 M5, 敵対 M10 | allowlist のみ。plugin agent に `hooks:` を書かない。最低 CC バージョンを README に |
| 最終メッセージ | 2次 M1, 1次 M5, 敵対 M8 | 成功条件に「親へ入るのは最終テキストのみ」と明記。エージェントに文字数キャップ。eval でコード貼り RED |
| 2>&1 / /usr/bin/cat | 1次 M2, 敵対 M2 | `>` は stdout ファイルリダイレクトだけ allow。basename で判定 |
| @ファイル | 2次 M6 | 既知の限界。スキルに「大きなファイルを @ するな」 |
| 90% 請求 | 敵対 M3 | プラグイン description に 90 を出さない。README で親コンテキスト隔離と明記 |
| shunt 併用 | 敵対 C4 | README: 同時有効にしない。決定合成は deny が勝つ |
| パス安全 | 敵対 M9 | `wc -l -- "$path"`、reason は jq --arg のみ |
| 子の上限 | 敵対 M6 | スキルにファイル数・合計バイト上限（例 8 / 200KiB）、超えたら分割 |
| 3+ files vs 350 | 1次 M3 | フックは単一ファイル閾値。スキルは 3+ ファイル横断も可。diff は親がファイル化したパスだけ（Bash は子に渡さない） |
| code-writer 強制 | 敵対 M4 | 成功条件4はベストエフォートのまま（ユーザー既決） |
| Explore 起動 | 敵対 M1, 1次 M4 | 既知の限界。Explore 自体は deny しない。deny reason に「親で bulk-reader を使え」 |
| Grep 全文 | 敵対 M2 | 既知の限界（記事の python/sed 穴と同型）。今回は Read/Bash のみ |
| 1行 minify | 敵対 C3 | **行数とバイトの両方**。どちらか超で deny |
| 並列 Write | 敵対 M7 | スキル: 同一 target は直列。上書きは可（記事の --target と同じ） |
| スキル/エージェント改名 | 1次 C3 | **却下**。2次どおり namespace が違う。問題は呼び出し文字列 |

## ユーザー裁定が要る分岐

1. バイト閾値を足すか（敵対 C3。記事には無い）
2. Read の limit 上限をフックで強制するか（記事は targeted を無条件通過）
3. jq を残すか、フックを Python 3 stdlib にして jq 依存を消すか
