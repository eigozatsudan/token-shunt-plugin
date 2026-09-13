# token-shunt 設計ドラフト（レビュー対象）

日付: 2026-09-12
状態: セクション1・2までユーザー合意。セクション3（ZIP・テスト・限界の詳細）は未提示。
参照記事: https://engineering.atspotify.com/2026/9/portal-by-spotify-cut-my-claude-code-token-usage-by-90

## 合意済み決定

| 項目 | 決定 |
|---|---|
| 目的 | Claude Code の親コンテキストから、大きなファイル読みと定型生成を外す |
| ワーカー | Claude Code の子エージェント。Portal / AiKA / 外部 API は使わない |
| モデル | 両エージェントとも `model: sonnet` + `effort: low` |
| 強制 | スキル + PreToolUse フック（Read と Bash） |
| 配布 | Claude Code プラグイン1本を ZIP（とローカル marketplace）で配る |
| プラグイン名 | `token-shunt`（Spotify の `shunt@portal` と衝突させない） |
| スキル名 | `bulk-reader` / `code-writer`（呼び出しは `/token-shunt:bulk-reader` 等） |
| 行数閾値 | 既定 350。環境変数 `TOKEN_SHUNT_MIN_LINES` |
| 置き場所 | `/home/dev/projects/skills/token-shunt/` |

## 成功条件

1. 親が 350 行超のファイルを offset/limit なしで Read すると、フックが止め、`/token-shunt:bulk-reader` へ誘導する。
2. 親が同じファイルを `cat` / `head` / `tail` / `less` / `more` で読もうとしても同様に止まる。パイプとリダイレクトは止まない。
3. bulk-reader 子は大きなファイルを読める（フックが子の `agent_type` を通す）。親には構造化箇条書きだけが返る。ファイル本文は親コンテキストに入らない。
4. code-writer 子は参照ファイルの流儀で target に書き、親にはパス・行数・3〜5行の要約だけ返す。生成本文は親に貼らない。
5. デバッグ・編集・設計判断・350行以下は委譲しない。
6. Portal CLI / API キーは不要。依存は Claude Code 本体とフック用の `jq`。
7. プラグイン ZIP を `claude --plugin-dir ./token-shunt.zip` または marketplace add → install で入れられる。

## 明示的にやらないこと

- Spotify Portal / AiKA 連携
- Gemini 等の外部ワーカー API
- code-writer のフック強制（生成は Write の前に親がトークンを焼くため、Read フックでは止められない）
- 親モデル自体の変更
- Cursor / Codex 向け配布（今回の対象は Claude Code）
- 「請求額が記事の 90% 減」の再現（記事の 90% は親コンテキスト。本設計の 90% も親コンテキスト。子の sonnet 分は別請求）

## データの流れ

```
親（高価なモデル）
  │ 大きな Read
  ▼
PreToolUse hook（check-file-size / check-bash-read）
  │ block + reason: /token-shunt:bulk-reader を使え
  ▼
親が bulk-reader スキルを開き、Agent(subagent_type=bulk-reader) を起動
  │ 渡すもの: 質問文 + パス一覧（ファイル本文は渡さない）
  ▼
子（sonnet, effort: low）が Read/Grep/Glob で読む
  │ 返すもの: 構造化箇条書きのみ
  ▼
親は要約だけで判断。編集が必要なら offset/limit 付きの Read だけ自分で行う

定型生成:
親が code-writer スキルを開き、Agent(subagent_type=code-writer) を起動
  │ 渡すもの: spec + 参照ファイルパス + target パス
  ▼
子が参照を Read し、target に Write
  │ 返すもの: パス、行数、3〜5行の要約。生成コードは返さない
  ▼
親は要約を見て、必要な箇所だけ targeted Read → 外科的 Edit
```

## ディレクトリ（予定）

```
token-shunt/                          # このリポジトリ内のパッケージ
  README.md
  docs/
    2026-09-12-design-draft.md        # 本ファイル
  reviews/                            # レビュー結果
  evals/
  .claude-plugin/
    marketplace.json                  # ローカル marketplace
  plugin/
    .claude-plugin/plugin.json
    skills/bulk-reader/SKILL.md
    skills/code-writer/SKILL.md
    agents/bulk-reader.md
    agents/code-writer.md
    hooks/hooks.json
    hooks/check-file-size             # bash + jq
    hooks/check-bash-read             # bash + jq
```

ZIP の一次成果物は `plugin/` の中身（先頭に `.claude-plugin/plugin.json`）。
`claude --plugin-dir` はディレクトリでも zip でも可。marketplace.json は unzip 後の `/plugin marketplace add` 用。

## フック契約

### 共通

- イベント: `PreToolUse`
- 出力: 現行 Claude Code の形式。`hookSpecificOutput.permissionDecision` を `allow` または `deny`。deny 時は `permissionDecisionReason` に誘導文。Spotify の古い `{"decision":"block"}` には依存しない。
- 依存: `jq`。無いときは fail closed（deny せず、フック失敗として通すか止めるかは未決。要レビュー）。
- 閾値: `TOKEN_SHUNT_MIN_LINES`。非数なら 350。
- 子エージェント通過: stdin の `agent_type` が次のいずれかなら **常に allow**:
  - `bulk-reader`
  - `code-writer`
  - `token-shunt:bulk-reader`
  - `token-shunt:code-writer`
  - 末尾が `:bulk-reader` または `:code-writer` の修飾名
- 親の Explore / general-purpose 等は通過させない（大きな Read を Explore に逃がさない）。

### check-file-size（matcher: Read）

allow:
- `tool_input.offset` または `tool_input.limit` がある（targeted read）
- `file_path` が空、またはファイルが存在しない
- 行数 <= 閾値
- 上記の worker `agent_type`

deny:
- それ以外の全文 Read。reason は行数と閾値、`/token-shunt:bulk-reader` への誘導、編集なら offset/limit を使え、を含む。AiKA / Portal とは書かない。

### check-bash-read（matcher: Bash）

allow:
- コマンドが空
- パイプ `|` を含む（targeted）
- リダイレクト `>` を含む（コンテキストへ読まない）
- `cat|head|tail|less|more` で始まらない
- 対象ファイルが無い / 行数 <= 閾値
- worker `agent_type`

deny:
- 上記以外の `cat/head/tail/less/more` による大きなファイル読み。

既知の穴（記事と同じ）:
- `sed -n '1,999p' file` や `awk` や `python -c` での全文読みは止めない。
- `head -n 400 large.py` はフラグを strip したあとファイルを見て、行数 > 閾値なら deny する（記事の実装はフラグを無視してファイル全体行数で判定する。`head -n 20` でもファイルが大きければ deny される）。この挙動を踏襲するかは未決。

## スキル契約

### bulk-reader

description（トリガーのみ、手順は書かない）:
Use when reading files over 350 lines, answering a question across 3+ files, or summarizing a large diff. Use when a Read/Bash hook blocked a large-file read. Do not use for debugging, architectural decisions, or edits that need exact file contents in context.

手順（本文）:
1. Agent を `subagent_type: bulk-reader`（プラグイン修飾名があればそれ）で起動する。
2. プロンプトに質問とパスだけを渡す。ファイル本文を親が読んで貼らない。
3. 各呼び出しは独立。続きは同じパスで再起動。
4. 返ってきた行番号・値を編集に使う前に、親が offset/limit 付き Read で確認する。
5. デバッグ・設計判断では使わない。フックが止めても、編集に必要な該当セクションは targeted Read してよい。

### code-writer

description:
Use for tests, config, docstrings, type stubs, or generation where more than 80% is predictable from a reference file. Do not use for novel logic, debugging, or safety-critical code.

手順:
1. 参照ファイルパスは必須。無ければスキルを使わず親が書く。
2. Agent を `subagent_type: code-writer` で起動。spec + reference + target を渡す。
3. 子が target に Write する。親は生成コードを受け取らない。
4. 続きは、今書いたファイルを次の `--reference` 相当として渡す。
5. 親は要約を見て、5–20% を targeted Read + 外科的 Edit する。
6. フック強制は無い。親が自分で生成し始めたら止められない。スキル description に依存する。

## エージェント契約

### agents/bulk-reader.md

```
---
name: bulk-reader
description: Precise code analyst for large-file questions. Use when the parent must not ingest file bodies.
model: sonnet
effort: low
tools: Read, Grep, Glob
---
```

本文の要点:
- 与えられたパスを読み、質問にだけ答える。
- 出力は構造化箇条書きのみ。挨拶・前置き・要約段落なし。
- 各 bullet は正確な名前・型・行番号で始める。詳細はネスト。
- 聞かれていないことは書かない。
- ファイル本文・大きなコード引用を親への最終メッセージに載せない。
- 行番号は最善努力。不確かなときはその旨を書く。

### agents/code-writer.md

```
---
name: code-writer
description: Boilerplate generator that matches a reference file. Writes to disk; does not return generated source to the parent.
model: sonnet
effort: low
tools: Read, Write, Grep, Glob
---
```

本文の要点:
- 参照ファイルのパターン・命名・スタイルに正確に合わせる。
- 曖昧なら参照の流儀で決める。
- target にコードだけを書く。markdown fence で包まない。
- 親への最終メッセージは: 書いたパス、行数、3〜5個の bullet（何を生成したか）。生成コードを貼らない。
- 参照が読めない / spec がコード生成でない場合は Write せず、理由だけ返す。

Bash / Edit は渡さない。

## 既知の限界（記事 + 本設計固有）

1. 編集は委譲できない。行番号は検証が必要。targeted Read はフックが通す。
2. 推論は委譲しない。安価モデル（ここでは sonnet low）は表面パターン向き。
3. 子起動のレイテンシがある。350 行閾値はそのため。
4. code-writer はスキル遵守に依存。無視されると親が生成トークンを焼く。
5. 親コンテキスト節約 ≠ 請求額 90% 減。子 sonnet は別途請求。
6. フックはサブエージェント内でも走る。worker allowlist を外すと bulk-reader が自分の Read を deny され、スキルが死ぬ。
7. `CLAUDE_CODE_SUBAGENT_MODEL` / `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` が haiku 等に固定されていると、frontmatter の sonnet が負ける可能性（要確認）。
8. `effort` frontmatter が Agent 起動で無視される既知バグがあった（2026-06 issue #64706）。現行版で直っているかは未検証。直っていなければ親が max のとき子も高くなる。
9. jq 非インストール環境。
10. Bash 回避（python/ruby/sed）は意図的に未カバー。

## テスト方針（未詳細・セクション3予定）

- フックは Claude 無しで stdin JSON → allow/deny を eval（Spotify shunt の hook-evals に相当）。
- worker allowlist（agent_type 付き JSON）を必須ケースにする。
- スキルは writing-skills の RED/GREEN: スキル無しで親が大きな Read をする baseline、スキル+フックで委譲する treatment。
- code-writer が生成本文を親に返す失敗を、エージェント本文の契約で潰す。

## 未決（レビューで潰したい）

- jq 欠落時の fail open vs fail closed
- `head -n 20 large.file` をファイル全体行数で deny するか、実際に読む行数で allow するか
- marketplace.json を plugin と同ディレクトリに置くか、一段上に置くか
- プラグイン skills の `name` とエージェント `name` の衝突（同名でよいか）
- フックを worker 内で無効化する別手段（agent frontmatter の hooks）があるか、allowlist だけでよいか
