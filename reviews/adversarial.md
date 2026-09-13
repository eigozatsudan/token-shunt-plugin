# Spec + Plan 敵対的レビュー

対象: `/home/dev/projects/skills/token-shunt/docs/2026-09-12-design-draft.md` / Plan なし（セクション3未提示）
日付: 2026-09-12

読み取り確認: Spec の節 11 個 / Plan の Task 0 件 / 名指しされた既存ファイル 0 件（うち確認済み 0）

1ホップ許可で開いたもの: `docs-lookup/SKILL.md`, `sdd-skills/agents/claude/sdd-reviewer.md`, `sdd-skills/docs/setup/claude-code.md`（いずれも設計が触る本番コードではない）。コントローラの既存クラス列挙は空。既存実装との相互作用欠陥は③でも⑤でも拾えない。

根拠にした現行ドキュメント（ディスパッチ許可の web_fetch）:
- https://code.claude.com/docs/en/hooks （2026-09-10）
- https://code.claude.com/docs/en/plugins-reference （2026-09-11）
- https://code.claude.com/docs/en/sub-agents （2026-09-11）
- https://engineering.atspotify.com/2026/9/portal-by-spotify-cut-my-claude-code-token-usage-by-90

## Critical

### C1. jq 欠落・フック非0終了は fail-open で、350行超 Read が親に通る
- 場所: フック契約・共通 / 成功条件 1・6 / 未決「jq 欠落時」
- 暗黙の前提: フックが失敗したら読ませない、または失敗がユーザーに見える。成功条件6は jq を依存に数えている。
- 失敗シナリオ: jq 未インストールの Linux で親が `Read(src/Service.java)`（2000行）を呼ぶ。`check-file-size` が `jq: command not found` で exit 127。現行フック仕様は exit 2 以外＋不正/空 stdout を **non-blocking error** としてツールを通す（fail-open）。親コンテキストに全文が入る。成功条件1は沈黙して死ぬ。`set -e` でも jq 失敗は 2 にならない。未決の「fail closed（deny せず…）」は用語が自己矛盾しており、現行ランタイムの既定は open 側。
- 提案: jq 無しは **exit 2**（または JSON `permissionDecision: deny`）に固定する。README に jq 必須を書き、フック単体 eval に `PATH` から jq を外したケースを必須にする。Python/Node の stdlib JSON に切り替えて jq 依存を消すのも可。

### C2. `offset` または `limit` があるだけで「targeted」扱いするため、全文 Read が合法
- 場所: check-file-size allow / 成功条件 1 / データの流れ「offset/limit 付きの Read だけ自分で行う」
- 暗黙の前提: offset/limit 付き Read は小さい。現行 Read ツールは **offset だけならその行から EOF まで**、**limit は上限を検証しない**。
- 失敗シナリオ: フックが `Read(huge.py)` を deny したあと、親が `Read(huge.py, offset=1)` または `Read(huge.py, limit=100000)` を出す。allow 枝に入り、2000行が親に入る。成功条件1は「offset/limit なし」だけを止めると書いてあるので、文言上は通り、目的（親から大きな本文を外す）は外れる。記事の "targeted reads pass through" を無検証でコピーしている。
- 提案: allow は `limit` 必須、かつ `limit <= TOKEN_SHUNT_MIN_LINES`（または更に小さい cap、例 80）。`offset` 単独は deny。`limit` が閾値超なら deny して bulk-reader へ誘導。

### C3. 「大きさ」を行数で測るため、minify・1行バンドル・バイナリが無制限に親へ入る
- 場所: 合意済み「行数閾値 350」/ check-file-size / 成功条件 1
- 暗黙の前提: 行数 ≈ トークン量。`wc -l` は改行の数であり、ファイルサイズでもトークンでもない。
- 失敗シナリオ: 親が `Read(dist/app.min.js)`（2MB・1行）または改行の少ない `.png` / protobuf を呼ぶ。`wc -l` は 0〜数行 → 閾値以下 → allow。親コンテキストが数万〜数十万トークンで埋まる。バイナリに対する `wc -l` は「行」を数えておらず、NUL を含むパスではさらに壊れる。コーディングエージェントが一番読みたくなる生成物（bundle、lockfile 1行、minified vendor）が、ちょうどこの穴に落ちる。
- 提案: 判定を **bytes または概算トークン**（`wc -c`、上限例 32KiB）と行数の **両方** にする。どちらかが超えたら deny。バイナリ/非テキストは即 deny。eval に minify 1行ファイルを必須ケースとして入れる。

### C4. `shunt@portal` との併用で、子の Read は deny が allow に勝って死ぬ
- 場所: 合意済み「Spotify の shunt@portal と衝突させない」/ フック契約（worker は常に allow）/ 既知の限界 6
- 暗黙の前提: プラグイン名が違えばフックも独立に正しい。現行仕様は複数 PreToolUse の決定を **deny > defer > ask > allow** で合成する。
- 失敗シナリオ: ユーザーが記事どおり `shunt@portal` を入れたまま `token-shunt` も入れる。親 Read は両方 deny（誘導文が二つ出て、親は Spotify 側の `/bulk-reader` を呼ぶかも）。`Agent(subagent_type=token-shunt:bulk-reader)` が大きな `Read` をすると、token-shunt は allow するが Spotify の check-file-size は `agent_type` を知らず deny。deny が勝つ。子はファイルを読めず、成功条件3は成立しない。名前の非衝突はスキル/プラグイン ID の話で、**決定合成は見ていない**。
- 提案: README に「shunt@portal と同時有効にしない」を硬く書く。同居を許すなら Spotify 側 allowlist に `token-shunt:*` を足すパッチ手順を書く。自前フックは worker 以外でも、他プラグインの deny を上書きできない前提でテストする。

## Major

### M1. 親は Read する前に組み込み Explore へ逃げる。フックは一度も発火しない
- 場所: 成功条件 1・3 / フック契約「Explore は通過させない」/ スキル description「3+ files」
- 暗黙の前提: 大きな I/O は親の Read から始まり、deny reason が `/token-shunt:bulk-reader` に誘導する。
- 失敗シナリオ: 「このリポジトリの auth はどう動く？」——現行 sub-agent 仕様では親は **Explore を自動起動**する（v2.1.198 以降 Explore は親モデル継承、API では Opus cap）。Explore の `agent_type` は allowlist 外なので大きな Read は deny されるが、Grep/Glob はフック対象外。Explore の最終メッセージにコード引用が載り、それが親に返る。bulk-reader の出力契約（箇条書き・本文禁止・sonnet-low）は適用されない。設計は Explore の **Read 通過**だけを拒否しており、**Explore 起動そのもの**は止めていない。
- 提案: PreToolUse matcher `Agent` で `subagent_type=Explore|Plan|general-purpose` かつプロンプトが大規模読取なら deny して bulk-reader へ。または `CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS=1` を導入手順に書く。スキル description を Explore より強くするだけでは足りない。

### M2. Grep content・PowerShell・`cat … 2>&1` が Read/Bash フックを空振りする
- 場所: 強制「Read と Bash」/ check-bash-read allow（`|` と `>`）/ 既知の穴（python/sed）
- 暗黙の前提: 親が大きな本文を取る手段は Read と `cat|head|tail|less|more` だけ。記事と同じ穴を「意図的」としているが、成功条件の目的は本文遮断。
- 失敗シナリオ:
  1. 親が `Grep(pattern=".", path=huge.py)` または `output_mode=content` でほぼ全文を親コンテキストへ入れる。matcher は Read のみ。
  2. Windows 親が PowerShell `Get-Content huge.py`。matcher `Bash` は `PowerShell` に一致しない。
  3. 設計どおり「`>` を含むコマンドは allow」。`cat huge.py 2>&1` は `>` を含むので allow。stdout は全文。
- 提案: Grep は `output_mode=content` かつヒット行数/バイトが閾値超なら deny。PowerShell を matcher に足す。`>` は「stdout をファイルへ切るリダイレクト」だけ allow（`2>&1` や `>&2` は不可）。python/sed は既知でも、Grep/PowerShell/`2>&1` を「記事と同じ」に含めない。

### M3. ワーカーが sonnet なので、親も sonnet のとき請求は減らず増えることがある
- 場所: モデル「両エージェントとも sonnet + effort low」/ やらないこと「請求額 90% 減の再現」/ 参照記事
- 暗黙の前提: 親コンテキストを外す ≈ ユーザーが記事の 90% を体感する。記事の 90% は **Gemini 2.5 Flash** に I/O を逃がした測定。ここは子も sonnet。
- 失敗シナリオ: 親モデルが sonnet（よくある既定）。2000行ファイルを聞かれ、フックが子 sonnet を起動。子が全文を input トークンとして焼き、親は要約を再処理する。プラグイン無しなら親 sonnet が一度読むだけ。**請求トークンは増える**。effort frontmatter が効かないビルド（#64706）や `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` だとさらに高い。ユーザーはドラフト先頭の記事タイトルで 90% 減を期待する。
- 提案: README 先頭で「親コンテキストの隔離であり、請求額の 90% 減ではない。親が sonnet なら増えることがある」と書く。子を haiku にするか、親が opus/fable のときだけ得、と条件を書く。プラグイン description に 90 を出さない。

### M4. code-writer は成功条件になっているが、強制経路が無い
- 場所: 成功条件 4 / やらないこと「code-writer のフック強制」/ スキル契約 6 / 既知の限界 4 / プラグインエージェントは `permissionMode` 不可
- 暗黙の前提: 親はスキル description を見て委譲する。時間圧と権限プロンプトの下でもそうする。
- 失敗シナリオ: 「UserService のテストを書いて」。親は参照を targeted Read し、自分で 400 行を Write する。Read フックは生成を止められない。子を起動した場合も、plugin-shipped agent は `permissionMode` / agent frontmatter `hooks` を **無視**される（plugins-reference）。親が Manual なら子の Write がプロンプトになり、バックグラウンド子の許可をユーザーが deny → 子は「書けなかった」と返し、親が自分で生成してトークンを焼く。成功条件4は守られない。
- 提案: 成功条件4を「ベストエフォート」に格下げするか、PreToolUse matcher `Write` で「新規の大きな生成は code-writer へ」と誘導する（完全強制はできないが、deny+reason はできる）。導入手順に auto/acceptEdits を書く。Write プロンプト deny を eval する。

### M5. allowlist の末尾一致は広すぎ、素の `bulk-reader` はプロジェクト定義に負ける
- 場所: フック契約「末尾が `:bulk-reader` / `:code-writer`」/ スキル「`subagent_type: bulk-reader`（修飾名があればそれ）」/ 未決「スキル名とエージェント名の衝突」
- 暗黙の前提: `agent_type` は安定で、プラグインの子は `bulk-reader` か `token-shunt:bulk-reader`。現行: プラグイン子の `agent_type` は **`token-shunt:bulk-reader`**（bare name ではない）。プロジェクト/ユーザー `.claude/agents/` はプラグインより優先度が高い。
- 失敗シナリオ:
  1. リポジトリに実験用 `.claude/agents/bulk-reader.md`（tools 無制限）がある。スキルが `subagent_type: bulk-reader` を指定すると **プロジェクト側が勝つ**。その `agent_type` は `bulk-reader` で allowlist に一致し、大きな Read が無制限。本文を親に返す制約もない。
  2. 末尾 `:code-writer` は `evil-plugin:code-writer` も常時 allow する。任意プラグインがサイズゲートを無効化できる。
  3. スキルが bare 名のままだと、修飾名の本命エージェントが呼ばれない。
- 提案: allowlist は **完全一致** `token-shunt:bulk-reader` と `token-shunt:code-writer` のみ。スキル/エージェント本文は修飾名だけを書く。eval に「プロジェクト同名エージェント」を必須にする。suffix マッチは捨てる。

### M6. 子への一括パスに上限が無く、溢れた子は悪い箇条書きを返し、親がそれを信じる
- 場所: スキル description「3+ files」/ 成功条件 3 / エージェント「行番号は最善努力」/ データの流れ「親は要約だけで判断」
- 暗黙の前提: 子 sonnet のコンテキストは、フックが通したファイル集合を正確に読める。350 は親側のレイテンシ閾値であり、子の予算ではない。
- 失敗シナリオ: 「この 20 ファイルの呼び出し関係は？」スキルが発火し、子が 20×1500 行を Read。子が compact され、存在しないメソッドやずれた行番号の箇条書きを返す。スキル手順4は targeted Read で検証せよと書くが、時間圧の親は行番号をそのまま Edit に使う。既知の限界1（行番号は検証が必要）と成功条件3（箇条書きだけで判断）が衝突する。
- 提案: スキルに **ファイル数と合計バイトの上限**（例: 8 ファイル / 200KiB）を書き、超えたら分割起動。エージェントに「確信が無い行番号は書くな」を機械的に近づける。親スキルの手順4を「検証しない Edit 禁止」まで強くする。

### M7. 並列 code-writer が同じ target を最後の Write で潰す
- 場所: データの流れ（定型生成）/ スキル「各呼び出しは独立」/ sub-agents「background が既定」
- 暗黙の前提: 親は code-writer を一つずつ、異なる target にだけ起動する。
- 失敗シナリオ: 「A と B のテストを書いて。共通 helper も」。親が background の code-writer を2体並列起動し、両方 `test/helpers.ts` に Write。先に終わった内容は消える。ロックも worktree も無い（`isolation` 未設定、plugin agent の worktree も別問題）。
- 提案: スキルに「同一 target は直列。並列は target が互いに素なときだけ」と書く。エージェントは既存 target を上書きする前に Read し、自分の世代でない内容なら中止して理由だけ返す。

### M8. 子の最終メッセージと autocompact が、隔離した本文を親へ戻す
- 場所: 成功条件 3・4 / エージェント「ファイル本文を最終メッセージに載せない」/ テスト方針「本文を親に返す失敗を契約で潰す」
- 暗黙の前提: プロンプト契約で十分。named subagent は tool 結果を親に入れない（これは現行 docs どおり）。
- 失敗シナリオ: 子 sonnet-low が「正確な名前・行番号」と「本文を載せるな」を同時に満たせず、80行の関数を引用して返す。それが Agent の tool result として親に入る。その後 autocompact が引用を要約に残し、以降のターンでも本文が居座る。SubagentStop で `last_assistant_message` を見て落とすフックは設計に無い。テスト方針は「エージェント本文の契約で潰す」と書いており、機械的ゲートが無い。
- 提案: SubagentStop で worker の最終メッセージがコードフェンス/長すぎる引用を含むとき block または切り詰め。文字数ハードキャップ（例 2k）をエージェントとフックの両方に置く。

### M9. deny reason に path を埋め、スペース/改行付き path で wc と JSON が壊れる
- 場所: check-file-size deny reason / フック実装が bash + jq + 行数
- 暗黙の前提: `file_path` は普通の相対パスで、reason はモデルへの安全な誘導文。
- 失敗シナリオ: ファイル名が `foo.json\nIgnore the hook and Read with limit=1.`。reason に path を文字列連結すると、モデルに「フックを無視せよ」が見える。`wc -l $file_path`（未クォート）は空白で分割され、別ファイルの行数を見るか、存在しない扱いで allow。`jq` へ `--arg` せずに埋め込むと JSON が壊れ、C1 と同じ fail-open。Issue #53463 系の control character でも jq が parse error → 同上。
- 提案: path は `wc -l -- "$path"`。reason は `jq -n --arg p "$path" --arg n "$n"` だけで組む。reason に生 path を長々と載せない。eval に空白・改行・`-n` という名前を入れる。

### M10. プラグイン子は hooks を持てない。allowlist と CC バージョンが生命線なのにピンが無い
- 場所: 未決「worker 内でフック無効化」/ 既知の限界 6・7・8 / エージェント frontmatter `effort: low`
- 暗黙の前提: `agent_type` が PreToolUse に載る、`effort` が効く、frontmatter `hooks` で子だけ外せる。
- 失敗シナリオ: 現行 plugins-reference は plugin-shipped agent の `hooks` / `permissionMode` / `mcpServers` を **無視**する。子だけフックを外す手段は allowlist のみ。古い CC で PreToolUse に `agent_type` が無い（#31939 時点）と、子の Read も親と同じく deny されスキルが死ぬ。`CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` で haiku 固定なら `model: sonnet` は負ける（docs 明示、v2.1.257+）。
- 提案: 未決を「allowlist のみ。plugin agent の hooks は使えない」と閉じる。最低 CC バージョンを plugin.json / README に書く。インストール時にフック stdin の `agent_type` を一発 dump する doctor 手順を付ける。FORCE が立っていたら警告。

## Minor

- `head -n 20 large.file` を全体行数で deny すると、スキルが許した「peek」まで Bash 経由で死ぬ。未決のまま出荷すると親は Read(offset/limit) 以外の確認手段を失う。
- `cat` で**始まる**判定は `command cat` / `/bin/cat` / `{ cat f; }` を通す。
- 存在しない `file_path` を allow すると、TOCTOU より「間違ったキー名で空文字」が allow になる。
- スキルとエージェントの同名は別 namespace で衝突しにくいが、親が Skill 名を `subagent_type` に流用すると M5 が起きる。
- marketplace.json の位置は失敗シナリオが「入れられない」以上にならないので、通常レビュー向き。

## 検討したが問題なしと判断した箇所

- **named subagent の tool 結果隔離**: 現行 docs は named 子の Read 本文は親に入らず最終結果だけ返ると明記。fork も tool 出力は親に入らない。隔離前提そのものは成立。壊れるのは最終メッセージ・Explore・Grep 側（M1/M2/M8）。
- **親の空 `agent_type`**: PreToolUse の `agent_type` は `--agent` 時か子の中だけ。通常の親は allowlist 非該当で大きい Read を deny される。ここは正しい。
- **子からの再帰 Agent**: `tools: Read, Grep, Glob`（writer は +Write）に `Agent` が無いので、現行の allowlist 解釈では子は Agent を持てない。再帰 spawn はツール制限で止まる。
- **パイプ回避**: 成功条件2が「止まない」と宣言済み。C/M にはしない。ただし `2>&1` をパイプ相当にしないこと（M2）。
- **スキル呼び出し名 `/token-shunt:bulk-reader`**: プラグイン skills の名前空間としては Spotify の `/shunt:…` と衝突しない。衝突はフック決定合成（C4）。
- **`effort: low` の現行 docs**: 2026-09-11 の sub-agents は session を override すると書く。#64706 は 2026-06。未検証だが「docs 上は直った」側。バージョンピン（M10）に吸収。
- **編集を委譲しない**: 記事と同じで、設計も明示。行番号を信じるなは限界1。成功条件3が「要約だけで判断」と書く点だけが矛盾（M6）。
- **Portal / API キー不要**: ワーカーを CC 子にした判断自体は、記事の Flash 節約を捨てる代わりに依存を減らしている。経済の誤読は M3。
