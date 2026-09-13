# Spec + Plan レビュー（通常）

対象: `/home/dev/projects/skills/token-shunt/docs/2026-09-12-design-draft.md` / Planなし（セクション3未提示）
日付: 2026-09-12

読み取り確認: Design の節 11 個 / Plan の Task 0 件 / 名指しされた既存ファイル 4 件（うち確認済み 4）

開いたパス:
- `/home/dev/projects/skills/token-shunt/docs/2026-09-12-design-draft.md`（Design 11節）
- `/home/dev/projects/skills/docs-lookup/SKILL.md`（スキル形式例）
- `/home/dev/projects/skills/sdd-skills/agents/claude/sdd-reviewer.md`（エージェント形式例）
- `/home/dev/projects/skills/sdd-skills/docs/setup/claude-code.md`（許可1ホップ）
- `/home/dev/projects/skills/sdd-skills/agents/claude/sdd-implementer.md`（許可1ホップ）
- `/home/dev/projects/skills/sdd-skills/skills/sdd-design-review/reviewer-prompt.md`（役割）

許可ファイルからは Claude Code の PreToolUse stdin/stdout・`agent_type`・Agent ツールの親への戻り値・`effort` frontmatter・`/plugin:skill` の公開規則は検証不能。未検証の API 挙動は発明していない。

## Critical

### C1. jq 欠落時が「fail closed」と「deny せず」で同時に書かれ、未決のままフックを実装できない
- 場所: フック契約 / 共通; 未決; 成功条件 6; 既知の限界 9
- 問題: 依存は `jq` 必須と書きつつ、欠落時の分岐が未決。しかも「fail closed」と「deny せず」は反対の意味で、実装者は allow も deny もフック失敗による停止も選べない。
- 根拠: 「依存: `jq`。無いときは fail closed（deny せず、フック失敗として通すか止めるかは未決。要レビュー）。」成功条件 6 は `jq` を依存に数えている。
- 提案: 用語を1つに固定する。推奨は (a) `jq` 無しはフックを即座に exit 0 相当で通過させ stdin を読まない（インストール手順で `jq` を必須化）か、(b) stderr に「jq required」を出して deny。どちらにするかを成功条件 6 と一致させ、stdin JSON を parse する前の分岐と eval ケース（`command -v jq` 失敗）を書く。

### C2. PreToolUse の入出力スキーマと `agent_type` の実値が無く、フック本体と allowlist を書けない
- 場所: フック契約 / 共通; check-file-size; 既知の限界 6; テスト方針
- 問題: 出力は `hookSpecificOutput.permissionDecision` とだけ書かれ、stdin の JSON 例が無い。`tool_input.file_path` / `offset` / `limit` / Bash のコマンド欄 / `agent_type` のキー名と実値が未確認。ここを外すと限界 6 のとおり bulk-reader が自分の Read を deny されスキルが死ぬ。許可ファイル（claude-code.md 含む）にフック契約は無い。
- 根拠: 「出力: 現行 Claude Code の形式。`hookSpecificOutput.permissionDecision` を `allow` または `deny`。」「子エージェント通過: stdin の `agent_type` が次のいずれかなら **常に allow**」。テスト方針は「stdin JSON → allow/deny」とだけある。
- 提案: セクション3を待たず、現行 Claude Code で PreToolUse の stdin を1回キャプチャした fixture を正典にする（親 Read / 子 bulk-reader / Explore）。stdout の最小 JSON も同じファイルに置く。allowlist はその fixture の実値だけに縮小し、推測の修飾名一覧で実装しない。検証不能なら「現行形式」と書かず「要キャプチャ」と未決に残す。

### C3. スキル名とエージェント名の衝突が未決で、誘導先 slash と `subagent_type` が実装不能
- 場所: 合意済み決定; 成功条件 1; スキル契約; エージェント契約; 未決
- 問題: プラグイン `token-shunt`、スキル `bulk-reader` / `code-writer`、エージェント同名、誘導 `/token-shunt:bulk-reader` が同時に定義されている。同名でよいかが未決のままでは `plugin/skills/` と `plugin/agents/` の `name:` も、親が呼ぶ文字列も決められない。許可したエージェント例はスキル名とエージェント名を分けている（`sdd-reviewer` vs スキル `sdd-design-review`）。衝突時に slash がスキル本文を飛ばしてエージェント直起動になると、「本文を親が貼らない」手順が消える。
- 根拠: 「プラグイン skills の `name` とエージェント `name` の衝突（同名でよいか）」が未決。成功条件 1 は `/token-shunt:bulk-reader`、手順は `subagent_type: bulk-reader`（「プラグイン修飾名があればそれ」）。
- 提案: 名前を分ける。例: スキル `shunt-read` / `shunt-write`、エージェント `bulk-reader` / `code-writer`、slash `/token-shunt:shunt-read`。フック allowlist はキャプチャしたエージェント側の `agent_type` のみ。スキル description は slash 用、エージェント description は `subagent_type` 用と役割を明記する。`commands/` が別途必要ならディレクトリ予定に足す。

### C4. 成功条件 2 は head/tail を一律停止としつつ、`head -n 20` の判定基準が未決
- 場所: 成功条件 2; フック契約 / check-bash-read; 未決
- 問題: 成功条件は「`cat` / `head` / `tail` / `less` / `more` で読もうとしても同様に止まる」。既知の穴は「`head -n 20` でもファイルが大きければ deny（記事踏襲か未決）」。実装者は (A) ファイル全体行数で deny（成功条件 2 どおり、targeted な head も死ぬ）と (B) 実際に読む行数で allow（成功条件 2 が偽）のどちらでも仕様違反になる。
- 根拠: 成功条件 2「親が同じファイルを `cat` / `head` / `tail` / `less` / `more` で読もうとしても同様に止まる。」未決「`head -n 20 large.file` をファイル全体行数で deny するか、実際に読む行数で allow するか」。
- 提案: 成功条件 2 を書き換えて一意にする。推奨: `head`/`tail` は `-n`/`-c` が閾値以下なら allow、省略時・閾値超は deny。`cat`/`less`/`more` はファイル行数で判定、とコマンド別に書く。eval に `head -n 20 large` / `head large` / `tail -n 5 large` を必須ケースで入れる。

## Major

### M1. offset/limit が1つでもあれば全文 Read を通すため、フック強制が形骸化する
- 場所: 成功条件 1・3; フック契約 / check-file-size; データの流れ
- 問題: deny されるのは offset/limit なしの Read だけ。拒否された親が `limit: 100000` や `offset: 1` でリトライすると 350 行超が親コンテキストに入る。成功条件 1 の文言は満たせるが、目的「大きなファイル読みを親から外す」と「強制」は満たさない。
- 根拠: 「`tool_input.offset` または `tool_input.limit` がある（targeted read）」を無条件 allow。成功条件 1 は「offset/limit なしで Read すると」だけを止めている。
- 提案: allow 条件を「指定レンジの行数が閾値以下」（例: `limit` ありなら `limit <= 閾値`、`offset` のみなら `行数 - offset + 1 <= 閾値`）に変える。成功条件 1 に「閾値を超える limit も deny」を追記する。

### M2. Bash allow 規則が成功条件 2 を空洞化する（`2>`、絶対パス、先頭空白）
- 場所: 成功条件 2; フック契約 / check-bash-read
- 問題: 「`>` を含む → コンテキストへ読まない」は `cat large 2>/dev/null` や `&>` にもマッチし、stdout は親に返る。「`cat|head|...` で始まらない → allow」は `/usr/bin/cat large` と先頭空白を通す。パイプ許容は意図どおりでも、これらは「同様に止まる」の反例になる。
- 根拠: allow「リダイレクト `>` を含む（コンテキストへ読まない）」「`cat|head|tail|less|more` で始まらない」。既知の穴は `sed`/`awk`/`python` のみ。
- 提案: `>` は stdout のファイルリダイレクト（`>` / `>>` の左が `2` でない）に限定するか、stdout が残るなら size check を続ける。コマンドは空白 trim のうえ basename が `cat|head|tail|less|more` なら判定対象。eval に `2>/dev/null` と `/usr/bin/cat` を入れる。

### M3. 成功条件 5「350行以下は委譲しない」と bulk-reader トリガー「3+ files / large diff」が矛盾し、diff はツール不足で実行不能
- 場所: 成功条件 5; スキル契約 / bulk-reader description; エージェント契約 / tools
- 問題: 成功条件は 350 行以下を委譲しない。description は 3 本以上なら行数無関係に Use、および large diff の要約でも Use。後者はエージェント tools が `Read, Grep, Glob` のみで `git diff` も Bash もできない。description 規則（トリガーのみ）自体は満たせるが、そのトリガー文が成功条件とエージェント契約に対して実装不能。
- 根拠: 成功条件 5「デバッグ・編集・設計判断・350行以下は委譲しない。」description「Use when reading files over 350 lines, answering a question across 3+ files, or summarizing a large diff。」tools: `Read, Grep, Glob`。
- 提案: description から「3+ files」「large diff」を消すか、成功条件 5 を「単一ファイル 350 行以下は委譲しない。複数ファイル横断と diff ファイル化されたものだけ可」に変える。diff を扱うなら (a) 親が diff をファイル化してパスだけ渡す手順を本文に書くか (b) エージェントに Bash を足す（回避穴が広がるので非推奨）。

### M4. Explore / Plan / general-purpose で大きな Read を拒否したあとの戻り経路が無い
- 場所: フック契約 / 共通; 成功条件 1; データの流れ; 既知の限界 10
- 問題: 親が Explore / general-purpose に大きなファイルを読ませると子の Read は deny される（allowlist 外）。子は `/token-shunt:bulk-reader` を親の代わりに起動できるかが未記載（許可ファイルからも検証不能）。失敗した子が python/sed（既知の穴）や Grep 全件で本文を親に返す経路も閉じられていない。Plan モードが別ツール経路かも未記載。
- 根拠: 「親の Explore / general-purpose 等は通過させない（大きな Read を Explore に逃がさない）。」deny reason は親向け誘導のみ。
- 提案: 期待動作を一文で固定する。例: 子への deny reason は「親で `/token-shunt:bulk-reader` を使え。このエージェント内では大きな Read はできない」。親向けスキル本文に「Explore に大きな Read を頼まない。deny が子から返ったら自分で bulk-reader を起動する」を書く。Grep で本文ダンプする穴を既知の限界に明示する。

### M5. code-writer の「親は生成コードを見ない」は Agent 戻り値も Write deny も未定義で成功条件 4 を担保できない
- 場所: 成功条件 4; やらないこと; スキル契約 / code-writer; エージェント契約; 既知の限界 4; テスト方針
- 問題: 成功条件 4 は「生成本文は親に貼らない」と断言する。やらないことはフック強制しない。限界 4 はスキル遵守依存。許可ファイルからは Agent が親に返すのが最終メッセージだけか、Write の payload / diff も含むか検証不能。Write が permission deny されたときの契約が無く、子が本文を返信に載せるのが自然なフォールバックになる。テスト方針は「エージェント本文の契約で潰す」だけで、ハーネスがツール結果を親に転送する場合を見ていない。
- 根拠: 成功条件 4「生成本文は親に貼らない。」やらないこと「code-writer のフック強制」。エージェント「参照が読めない / spec がコード生成でない場合は Write せず、理由だけ返す。」（Write 失敗は無い）。sdd-implementer も「返信にコード片を貼らない」は規約でありツール制限ではない。
- 提案: 成功条件 4 を「最終メッセージに生成コードを載せない（eval で検証）。ハーネスがツール結果を親に返す場合は未担保」に弱めるか、検証不能なら「親コンテキストに入らない」を成功条件から外す。エラー経路を足す: Write deny / ファイル既存 / 参照 Read 失敗時はコードを返信せず理由とパスだけ。親が general-purpose や自分の Write で生成し始めたら止めない、は成功条件からも除外する。

### M6. セクション3未提示のため ZIP・marketplace・hooks.json・plugin.json・テストが実装不能
- 場所: 状態行; ディレクトリ（予定）; 成功条件 7; テスト方針; 未決
- 問題: 配布とテストが成功条件に入っているのに、ZIP の中身、`hooks.json` の matcher 形式、`plugin.json` の必須キー、marketplace.json の置き場所、eval の入力例が無い。成功条件 7 は「ZIP を `--plugin-dir` または marketplace add」の両方可と読めるが、marketplace.json は `plugin/` の外に描かれており ZIP 一次成果物に入らない。
- 根拠: 「セクション3（ZIP・テスト・限界の詳細）は未提示。」未決「marketplace.json を plugin と同ディレクトリに置くか、一段上に置くか」。成功条件 7。
- 提案: セクション3で (1) `--plugin-dir` 用 ZIP = `plugin/` の中身、(2) marketplace 用はリポジトリ root の `.claude-plugin/marketplace.json` で path が `./plugin`、と配布経路を分ける。`hooks.json` と `plugin.json` の全文を設計に貼る。フック eval の stdin fixture を C2 と共有する。

### M7. エージェント description でも直起動でき、スキル本文の禁止事項を飛ばせる
- 場所: スキル契約 / 手順; エージェント契約 / description
- 問題: スキル手順は「本文を貼るな」「行番号は targeted Read で確認」など親向け契約。エージェント description は「Use when the parent must not ingest file bodies」「Writes to disk; does not return generated source」と独自トリガーを持ち、親がスキルを開かず Agent 直呼びできる。code-writer はフック強制が無いのでこの経路が本線になりうる。
- 根拠: データの流れ「親が bulk-reader スキルを開き、Agent を起動」。エージェント description が別文で Use when を宣言している。
- 提案: エージェント description をルーティング不能な短い識別文にするか、「必ず対応スキル経由。親はこのエージェントを直接選ばない」と書く。スキルとエージェントの公開面を C3 の改名と揃える。

## Minor

- スキル description の「over 350 lines」は `TOKEN_SHUNT_MIN_LINES` と同期できない。フック deny をトリガーに残すのはよいが、数値は「the configured line threshold (default 350)」にする。
- 合意済み決定の「強制 | スキル + PreToolUse（Read と Bash）」は code-writer 非強制と読み違えられる。行を「bulk-reader のみフック強制」に分ける。
- `TOKEN_SHUNT_MIN_LINES` が `0` / 負 / 小数 / 空のときの正規化が「非数なら 350」しか無い。
- `cat f1 f2` の「対象ファイル」が複数のとき、どれを測るか未記載。
- code-writer の target が既存ファイルのときの上書き可否が未記載。
- バイナリ / ディレクトリ / 最終改行無しの `wc -l` が未記載。
- 入力リダイレクト `<` は `>` と対称に扱われていない（`cat < large` は size check 対象になりうるが明文化なし）。
- `effort: low` は許可したエージェント例に無く、既知の限界 8 のまま確認タスクが無い。
- bulk-reader description はトリガーのみで手順を含んでおらず、docs-lookup 例の「いつ使う / いつ使わない」形には載せられる。問題は M3 のトリガー内容側。

## Spec カバレッジ

Plan が無いため、要件を実装タスクに指せない。対応する設計節のみ示す。

| Spec の要件 | 実装するタスク |
|---|---|
| 成功条件 1: offset/limit なし 350 行超 Read を止め `/token-shunt:bulk-reader` へ | **なし**（フック契約に記載。C3/M1 で不完全） |
| 成功条件 2: cat/head/tail/less/more も止める。パイプとリダイレクトは止めない | **なし**（C4/M2 で不完全） |
| 成功条件 3: 子は大きなファイルを読める。親には箇条書きのみ | **なし**（C2 の agent_type 未確認） |
| 成功条件 4: code-writer はパス・行数・要約のみ。生成本文を親に貼らない | **なし**（M5 で担保不能） |
| 成功条件 5: デバッグ・編集・設計判断・350 行以下は委譲しない | **なし**（M3 と矛盾） |
| 成功条件 6: Portal 不要。依存は Claude Code と jq | **なし**（C1 で jq 欠落時未決） |
| 成功条件 7: ZIP を `--plugin-dir` または marketplace で導入 | **なし**（M6・セクション3未提示） |
| やらないこと: Portal/AiKA/外部 API | 実装しない（設計どおり） |
| やらないこと: code-writer のフック強制 | 実装しない（成功条件 4 と緊張、M5） |
| やらないこと: 親モデル変更 / Cursor・Codex / 請求額 90% 減 | 実装しない（設計どおり） |
| スキル description はトリガーのみ | 文面は手順を含まない（M3 のトリガー内容が不適） |
| フック worker allowlist | **なし**（C2 の実値待ち） |
| Explore/Plan/general-purpose 非通過 | **なし**（M4 の戻り経路なし） |
| エラー経路: jq 欠落 | **なし**（C1） |
| エラー経路: ファイル欠落 | フック契約で allow（存在しない → 通す） |
| エラー経路: agent spawn 失敗 | **なし** |
| エラー経路: Write permission deny | **なし**（M5） |
