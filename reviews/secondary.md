# Spec + Plan レビュー（通常）

対象: `/home/dev/projects/skills/token-shunt/docs/2026-09-12-design-draft.md` / （Plan なし。設計ドラフト単体）
日付: 2026-09-12
役割: 2次（Claude Code プラグイン / フック / Agent の現行仕様と、Spotify 記事の節約メカニズムとの差分）

読み取り確認: Spec の節 11 個 / Plan の Task 0 件 / 名指しされた既存ファイル 3 件（うち確認済み 3）

開いたパス:
- `/home/dev/projects/skills/token-shunt/docs/2026-09-12-design-draft.md`
- `/home/dev/projects/skills/sdd-skills/agents/claude/sdd-reviewer.md`
- `/home/dev/projects/skills/sdd-skills/docs/setup/claude-code.md`
- `/home/dev/projects/skills/sdd-skills/skills/sdd-design-review/reviewer-prompt.md`（役割プロンプト）

現行ドキュメント照合（2026-09-12 取得）:
- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/plugins
- https://code.claude.com/docs/en/plugins-reference
- https://code.claude.com/docs/en/plugin-marketplaces
- https://code.claude.com/docs/en/sub-agents
- https://code.claude.com/docs/en/tools-reference
- https://code.claude.com/docs/en/skills
- https://engineering.atspotify.com/2026/9/portal-by-spotify-cut-my-claude-code-token-usage-by-90
- https://github.com/sorantis/portal-ai-plugins/tree/add-shunt-claude/plugins/shunt
- https://github.com/anthropics/claude-code/issues/64706

## Critical

### C1. jq 欠落は現行 Claude Code では fail-open。未決のままでは成功条件1が黙死する
- 場所: フック契約「共通」/ 未決「jq 欠落時の fail open vs fail closed」/ 成功条件 1・6
- 問題: ドラフトは「fail closed（deny せず、フック失敗として通すか止めるかは未決）」と書いており、用語と括弧が矛盾している。現行ランタイムでは、jq 不在（exit 127）や JSON を出せない失敗は **ツール実行を止めない**。
- 根拠: Hooks reference「Exit code output」: *“For most hook events, exit code 2 is the only exit code that blocks through the code alone. Without valid JSON on stdout, Claude Code treats exit code 1 as a non-blocking error and proceeds with the action”*。同節: *“when Claude Code tries to parse your stdout as JSON and can't, it reports a non-blocking error on every exit code other than 2”*。Spotify の `check-file-size` は `set -e` / `pipefail` なしで `jq` を呼ぶため、jq 欠落時は空フィールド → `{"decision":"allow"}` 相当で通過する。
- 提案: 未決を閉じる。ハードゲートを保つならフック先頭で `command -v jq` を確認し、欠落時は **stdout 空・stderr に理由・`exit 2`**（fail-closed）。README に jq を必須と書くだけでは足りない。allow するなら成功条件1を「jq がある環境に限る」に格下げする。

## Major

### M1. 親に返るのは「子の最終メッセージ全文」。tool transcript は乗らないが、長い回答なら 90% は消える
- 場所: 成功条件 3・4 / データの流れ / エージェント契約 / 既知の限界 5
- 問題: 90% は「親がファイル本文を読まない」こと。Agent ツールは子の Read/Write 結果を親へ転写しない。しかし最終テキストは **無制限に** 親コンテキストへ入る。code-writer が生成コードを最終メッセージに載せた瞬間、Spotify が script 境界で防いでいた節約が消える。
- 根拠: Tools reference「Agent tool behavior」: *“The subagent works through its task autonomously, then returns a single text result to the parent conversation. The parent doesn't see the subagent's intermediate tool calls or outputs, only that final result.”* Spotify `scripts/code-write` は `--target` 時にコードをディスクへ書き、親の Bash 結果は `Wrote N lines to $target`（stderr）だけ。記事: *“can write directly to disk. Claude never sees the generated code.”* 本設計は同じ保証をエージェント本文の遵守に置いている（テスト方針最終行）。
- 提案: (1) 成功条件3・4に「親へ返るのは Agent の最終テキストのみ。tool result は乗らない。最終テキストが長いと 90% は成立しない」と明記。(2) code-writer に機械キャップを足す（例: 最終メッセージが N 行/トークン超なら SubagentStop または親側 PostToolUse(Agent) で打ち切り・再実行指示）。(3) eval に「子がコードを貼った RED」を必須にする。プロンプト契約だけでは Spotify の節約メカニズムを再現しない。

### M2. プラグイン agent_type は `token-shunt:bulk-reader`。スキルが裸の `bulk-reader` を第一にすると親が Explore に逃げる
- 場所: スキル契約 bulk-reader 手順1 / フック契約「子エージェント通過」/ 成功条件 3
- 問題: フック allowlist はスコープ付き名を含むので、**起動さえすれば** 子の Read は通る。問題は起動文字列。スキルは `subagent_type: bulk-reader`（修飾名があればそれ）と曖昧。プラグイン agent の `agent_type` は裸の `name` ではない。親が Explore / general-purpose に逃がすと Read は deny されるが、そのあと offset/limit 分割 Read で本文が親に入り、節約が消える。
- 根拠: Hooks「SubagentStart」: *“For subagents shipped by a plugin, the agent type is the plugin-scoped identifier such as `my-plugin:reviewer`, not the bare frontmatter name.”* Skills: プラグインスキルは `/plugin-name:skill-name`。同ページの `context: fork` + `agent:` はスキル実行を指定エージェントへ機械的に載せる。ドラフトのスキルは親コンテキストに手順を注入し、親の自律に Agent 起動を任せる（Spotify は `${CLAUDE_PLUGIN_ROOT}/scripts/bulk-read ...` の 1 本）。
- 提案: スキル手順の `subagent_type` を **`token-shunt:bulk-reader` / `token-shunt:code-writer` に固定**。allowlist の第一もこの文字列。可能なら SKILL.md に `context: fork` と `agent: token-shunt:bulk-reader`、`background: false` を付け、親が generic Task/Explore を選ぶ経路を潰す。fork する場合、スキル本文は「親が Agent を呼べ」ではなく **子が実行する質問** に書き換える。

### M3. `head -n 20 large` の記事実装を誤記している。記事 eval では allow（パーサバグ）
- 場所: フック契約 check-bash-read「既知の穴」/ 未決「head -n 20」/ 成功条件 2
- 問題: ドラフトは「`head -n 20` でもファイルが大きければ deny（記事の実装）」と書く。Spotify の実装と eval は逆。フラグ strip のあと最初の非 `-` トークンをパスとみなすため、`head -n 20 large.py` はパス=`20` → ファイルなし → allow。`head -20` / `head -n20`（スペースなし）は large.py を見て deny。
- 根拠: shunt `evals/bash-hook-evals.json` id 17 `head-n-space-count`: `"command": "head -n 5 {{FIXTURES}}/large.txt"`, `"expected_decision": "allow"`, `"reason": "Parser bug: -n and 5 are separate args, 5 is treated as file path — file '5' won't exist so allow"`。id 5 `head -100` は block。
- 提案: 未決をユーザー意図で閉じる。`head -n N` / `tail -n N` で N≤閾値なら allow（targeted）。記事のパーサバグを「踏襲」と書かない。成功条件2は「フラグ無しの cat/head/tail/less/more」に限定する。

### M4. marketplace.json は一段上。plugin.json との同居は公式レイアウトと矛盾する
- 場所: ディレクトリ（予定）/ 未決「marketplace.json を plugin と同ディレクトリに置くか」/ 成功条件 7
- 問題: 予定ツリーは既に正しい（リポジトリ直下 `.claude-plugin/marketplace.json`、プラグインは `plugin/.claude-plugin/plugin.json`）。未決が残ると実装者が `plugin/.claude-plugin/` に両方置く。ZIP 一次成果物は `plugin/` の中身、marketplace add は unzip 後のリポジトリ、という二系統が混線する。
- 根拠: Plugin marketplaces: *“Create `.claude-plugin/marketplace.json` in your repository root.”* *“Claude Code resolves the path relative to the marketplace root, not the `.claude-plugin/` directory.”* Plugins: *“Don't put `commands/`, `agents/`, `skills/`, or `hooks/` inside the `.claude-plugin/` directory. Only `plugin.json` goes inside `.claude-plugin/`.”* `--plugin-dir` はディレクトリでも zip でも可（*“The flag also accepts a `.zip` archive of the plugin directory.”*）。zip 内は `.claude-plugin/` がアーカイブ先頭、または単一トップフォルダの直下。
- 提案: 未決を「一段上」で閉じる。`marketplace.json` の `source` は `"./plugin"`。ZIP は `plugin/` のみ（marketplace.json を入れない）。`--plugin-dir` に渡すのは zip / `plugin/` でありリポジトリルートではない、と成功条件7に書く。

### M5. プラグイン同梱エージェントの frontmatter `hooks` は無視される。worker 内無効化は allowlist 一択
- 場所: 未決「フックを worker 内で無効化する別手段」/ 既知の限界 6 / フック契約「子エージェント通過」
- 問題: 実装者が agent 定義に `hooks:` を書いてプラグイン PreToolUse を内側から消そうとすると、黙って無視される。allowlist を省略すると bulk-reader が自分の Read を deny され、スキルが死ぬ（ドラフト既知の限界6）。
- 根拠: Subagents: *“For security reasons, plugin subagents don't support the `hooks`, `mcpServers`, or `permissionMode` frontmatter fields. These fields are ignored when loading agents from a plugin.”* Plugins reference も同趣旨。Hooks: *“Hooks from settings files, managed policy settings, and plugins also run inside subagents … input carries the `agent_id` and `agent_type`.”*
- 提案: 未決を閉じる。worker 通過は stdin の `agent_type` allowlist のみ。テスト必須（ドラフトの方針どおり）。エージェント md に `hooks:` を書かない。

### M6. `@ファイル` は Read ツールを通らないのでフック不能
- 場所: 成功条件 1 / 既知の限界（未記載）
- 問題: 親が大きなファイルを `@path` で参照すると、PreToolUse(Read) が走らず本文が親プロンプトに入る。成功条件1の「Read すると止める」はツール経路だけ。
- 根拠: Hooks PreToolUse Warning: *“Files you reference with `@` in your prompt are added without any tool call: Claude Code inserts their contents while building the prompt, so no PreToolUse hook fires for them, including hooks matching `Read`.”*
- 提案: 既知の限界に書く。スキル description に「大きなファイルを `@` せず、`/token-shunt:bulk-reader` へ」を足す。Permissions の Read deny で塞ぐのは編集まで壊すので採用しない。

## Minor

- PreToolUse の現行出力は `hookSpecificOutput.permissionDecision` = `allow`/`deny`。Spotify の `{"decision":"block"}` は deprecated だが `"block"`→`"deny"` にマップされる（Hooks「PreToolUse decision control」）。ドラフトが新形式を選んでいるのは正しい。実装者が shunt スクリプトをコピーすると旧形式になるが、現行では動く。
- `effort` frontmatter（issue #64706, Closed）。現行 Subagents は *“Overrides the session effort level”* と書いてある。未検証のまま「直っていなければ子も高い」と残すより、eval で `/tasks` の effort 表示を 1 ケースにする。
- `CLAUDE_CODE_SUBAGENT_MODEL` は v2.1.251 以降、frontmatter より下位。負けるのは `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` のとき（Subagents「Choose a model」/「Run every subagent on one model」）。「env だけで sonnet が負ける」は FORCE 無しでは不正確。
- スキル名とエージェント名の同名はよい。Skill は `/token-shunt:bulk-reader`、Agent は `token-shunt:bulk-reader` でツールが違う。衝突より M2 の呼び出し文字列の方が本体。
- Bash フックの matcher が `Bash` だけだと、Windows で PowerShell ツールが主経路のとき発火しない（Hooks「Match `Bash|PowerShell`」）。今回スコープ外なら限界に一行。
- プラグインフックの `command` で `${CLAUDE_PLUGIN_ROOT}` を使うなら、公式は exec form（`args`）を推奨。Spotify は shell form。パスに空白があると壊れる。
- Grep / `sed` / `python -c` は記事と同じ穴。追加指摘ではない。
- 背景サブエージェントの `outputFile` を親が Read する経路は、公式が「最終結果のみ」と書いている以上、transcript 全漏れとは断定しない。eval で Agent 完了後の親コンテキストにファイル本文が無いことだけ確認すれば足りる。

## Spec カバレッジ

| Spec の要件 | 実装するタスク |
|---|---|
| 成功条件1: 350行超の全文 Read を止め `/token-shunt:bulk-reader` へ誘導 | フック契約 check-file-size。C1（jq）と M6（`@`）が未カバー |
| 成功条件2: cat/head/tail/less/more も止める。パイプとリダイレクトは通す | フック契約 check-bash-read。M3 で記事挙動が誤記。未決のまま **なし** に近い |
| 成功条件3: 子は大きなファイルを読める。親には箇条書きだけ。本文は親に入らない | フック allowlist + エージェント契約。M1（最終メッセージ長さ）と M2（起動名）が未固定 |
| 成功条件4: code-writer はディスクへ書き、親にはパス・行数・要約だけ | エージェント契約のみ。Spotify の script 境界に相当するタスクは **なし** |
| 成功条件5: デバッグ・編集・設計判断・350行以下は委譲しない | スキル description。フックは 350 行以下を通す |
| 成功条件6: Portal 不要。依存は Claude Code と jq | 合意済み。jq 欠落時の契約は C1 で **なし** |
| 成功条件7: ZIP を `--plugin-dir`、または marketplace add → install | ディレクトリ予定。M4 の未決を閉じるまで実装者が二系統を混ぜうる |
| やらないこと: code-writer のフック強制 | 明示済み。スキル description 依存 |
| やらないこと: 請求額 90% 減の再現 | 明示済み。ただし親コンテキスト 90% も M1 なしでは検証不能 |
| モデル: 両エージェント `sonnet` + `effort: low` | エージェント frontmatter。FORCE=1 時は負ける（Minor） |
