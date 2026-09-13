# token-shunt 設計仕様

日付: 2026-09-12
状態: ユーザー承認済み（2026-09-13）。再レビュー反映。読取経路は Claude Code の named subagent に確定（§26.0）。目的・制約・手段の階層を §1.1 に明示し、費用ゲートを出荷区分から内部回帰チェックへ格下げ（§26.5）。目的への穴 4 件を設計変更として反映（`limit=1` 例外の削除、パイプ末尾判定、複数明示パス 1 起動、code-writer の汎用フォールバック検証）。§13〜§15・§26 の旧文（1 起動 1 ファイル、`limit=1` 通過、パイプ全通過、費用最適化版）を同じ正本へ揃えた。2026-09-13 偽陽性チェック反映: 生成の検証段階、親トークン測定、バッチ間の根拠、Bash 判定を補正。判定記録は末尾 §27。実装・費用削減率は未検証。
参照: https://engineering.atspotify.com/2026/9/portal-by-spotify-cut-my-claude-code-token-usage-by-90
レビュー: `reviews/primary.md` / `secondary.md` / `adversarial.md` / `synthesis.md`

## 1. 目的

Claude Code の親スレッドから大きなファイルの全文と定型生成の本文を外し、回答と編集の正確性を保つ。大量 I/O は Claude Code の named subagent が行い、親には短い結果だけを返す。

Spotify の shunt と同じ分離（hooks + skills + workers）だが、Portal / AiKA は使わず、Claude Code の named subagent を使う。軽量モデルへの振り分けは、この目的を安く達成するための手段として扱う（§1.1）。

### 1.1 目的・制約・手段の階層

この階層が設計判断の優先順位である。**下位が上位を上書きしてはならない。**

| 段 | 内容 | 扱い |
|---|---|---|
| 目的 | 親コンテキストのノイズ削減と、回答・編集の正確性 | リリースゲート。`isolation_ok` / `accuracy` / `path_ok`（§13） |
| 制約 | 親子合計の推定費用を直接処理より悪化させない | 内部の回帰チェック。悪化したら手段を改訂する（§26.5）。出荷区分や製品ラベルにはしない |
| 手段 | (1) Haiku / Sonnet のモデル選択、(2) 小さい仕事の親による直接処理、(3) 子の作業量制限 | 目的を損なわない範囲で採る。単独で目的にも出荷条件にもならない |

費用最適化は手段であり目的ではない。**手段が目的の適用範囲を削る場合は手段を改訂する**（例: 起動上限でファイル横断質問が非対応になり、ユーザーが親での全文 Read に戻るなら、上限ではなく上限の置き方が誤り）。手段が目的をわずかに損なう場合は、費用ではなくノイズ予算で正当化する（§26.2）。

変更のない調査結果の再利用は v0.2 以降の任意検討（§26.4）。既定は Haiku を第一候補とする `auto`。Sonnet への切り替えとやり直しを含めて評価する。

請求額の 90% 減は保証しない。description と README 先頭に「90%」と書かない。記事の約 90% は親 Claude の input トークン削減であり、安価ワーカー側は別会計。本プラグインの親子合計費用の削減率ではない。効果が出やすいのは親が Sonnet / Opus のとき。親が Haiku なら isolation のみを期待し、費用削減は期待値に含めない。モデルの単価・キャッシュ・再試行・検証を含む実測で判断する。定額契約では使用量が減っても月額料金が下がるとは限らない。

## 2. 決定一覧

読取・生成とも Claude Code の named subagent を採用する（§26.0）。

| 項目 | 値 |
|---|---|
| プラグイン名 | `token-shunt` |
| スキル | `bulk-reader` / `code-writer` |
| エージェント | 同名。呼び出しと `agent_type` は `token-shunt:bulk-reader` / `token-shunt:code-writer` のみ |
| ワーカー | Claude Code 子エージェント。frontmatter は `model: haiku` / `effort: low`。親が Agent の `model` で Haiku / Sonnet を選択（§26.1） |
| モデル方針 | SKILL.md の入力規約 `--worker-model auto / haiku / sonnet`（表記は §26.1）。既定 auto。初回 Haiku、条件付き Sonnet 再試行は 1 回まで |
| 小仕事 | 読み取り合計 ≤ 16384 バイトで各 Read が通過するなら原則直接。定型生成は見積もり 50 行未満かつ参照合計 ≤ 16384 バイトなら直接 |
| 子の予算 | bulk-reader は Read のみ・`maxTurns: 6`。1 起動につき**明示された最大 3 パス**を読み、**各領域は 1 回だけ**（通常は 1 パス 1 Read、Read ツール自身がトークン上限で全文を拒否した場合のみ連続・非重複の分割）。探索・重複再 Read・指定外パスなし。code-writer は §26.3 |
| 再利用 | v0.1 対象外。索引・fingerprint・resume を実装しない |
| 強制 | PreToolUse は親と非 allowlist の子の Read / Bash をサイズゲートする。allowlist は bulk-reader（Read と Bash）と code-writer（Read のみ）（§8.4）。モデル方針・小仕事判定・作業量制限はスキル遵守（ベストエフォート） |
| 配布 | プラグイン ZIP + ローカル marketplace |
| 置き場所 | `/home/dev/projects/skills/token-shunt/` |
| 行閾値 | `TOKEN_SHUNT_MIN_LINES` 既定 350 |
| バイト閾値 | `TOKEN_SHUNT_MIN_BYTES` 既定 65536 |
| 走査予算 | `TOKEN_SHUNT_SCAN_BUDGET_BYTES` 既定 8388608（8MiB）、`TOKEN_SHUNT_SCAN_BUDGET_MS` 既定 2000。判定不能は deny |
| 単一行 Read | `limit=1` も区間バイト閾値に従う（**例外を置かない**）。単一行が `MIN_BYTES` を超えるなら deny（§9.7） |
| JSON | `jq` 必須。欠落・不正 JSON は PreToolUse で fail-closed（stdout 空、stderr に理由、exit 2）。SessionStart で 1 回警告する（block 不可） |
| Read 除外拡張子 | 画像・PDF・`.ipynb` はサイズゲートしない（公式 Read が視覚/ページ/セル経路） |
| 対象ハーネス | Claude Code のみ |

## 3. 成功条件

1. 親の Read は §9 のアルゴリズムで deny するか、決定なしで通過する。deny の reason は `/token-shunt:bulk-reader` を指す。AiKA / Portal / 90% とは書かない。通過時に `permissionDecision: "allow"` は出さない。
2. 親の Bash は §10 のアルゴリズムで deny するか、決定なしで通過する。対象外コマンドも同様（サイズ制御が権限確認を省略しない）。
3. `agent_type` が `token-shunt:bulk-reader` のとき Read と Bash はサイズゲートを適用せず決定なしで通過する。`token-shunt:code-writer` は Read のみ（Bash は tools に無いので Bash フックの allowlist に載せない）。子は大きなファイルを読める。権限確認は省略しない。
4. bulk-reader の親への最終メッセージにファイル本文を載せない（eval で検証）。親へ入るのは Agent の最終テキストのみ（中間 tool 結果は乗らない）。
5. code-writer は参照ファイル必須、target に Write し、親への最終メッセージはパス・行数・3〜5 bullet のみ。フック強制はしない（ベストエフォート）。親は生成本文の全文を vis せず、spec の検証コマンド（無ければ §11 の汎用フォールバック）を Bash し、§11 の minimal / syntax / requirements を区別して完了判定する。比較 eval の必須ケースで、参照ありの生成成功（親が検証を実行し成功、eval ランナーが生成テスト 1 件以上＋ mutation）と参照失敗時の非 Write を実機検証する。
6. デバッグ・編集・設計判断は委譲しない。単一ファイルが両閾値以下ならフックは Read を止めない（要求 `limit` が `MIN_LINES` を超えていても、ファイルに実際に含まれる行・バイトが両方以下なら止めない）。編集はフックを通る原本 targeted Read が成功し、編集対象の原文を確認できる場合だけ（§11.6）。`limit=1` も区間バイト閾値に従うので、単一行が `MIN_BYTES` 超なら deny され、その編集は v0.1 対象外。ファイル数だけで委譲しない。小仕事の判定は §26.2 に従う。
7. Portal CLI と追加の外部 API キーは不要。基本実行時依存は Claude Code と `jq`。Claude Code 自体の認証を使い、プラグインから外部 API を直接呼び出さない。再利用用ハッシュ依存は追加しない。
8. `plugin/` を zip した成果物を `claude --plugin-dir ./token-shunt.zip` でロードできる。リポジトリルートの marketplace.json は公式必須フィールド（`name` / `owner.name` / `plugins`）を満たし、`claude plugin validate`（または同等の marketplace 検証）と `/plugin marketplace add` → install の対象になる。
9. 同一の大きなファイル質問について、直接処理と bulk-reader 委譲を比較する eval がある。起動は `claude -p --output-format stream-json --verbose --include-hook-events --forward-subagent-text`。**直接モードは token-shunt をロードしない。委譲モードはロードする。** 親モデル・権限・fixture は揃え、設定ソースと cwd は §13 の隔離契約に従う。合格条件は (a) gold 事実、(b) transcript 上の経路（直接は親 Read が**成功**、委譲は `subagent_type=token-shunt:bulk-reader`、子→親テキストの本文契約、複数ファイル委譲は指定パスへの子の Read。横断 3 パスは **1 起動**）、(c) フック deny から委譲へ移る実機ケース（一次証拠は `--include-hook-events` の `hook_response`）、(d) 代表的な大容量ケースでは委譲の `parent_added_utf8_bytes` が直接より小さく、かつ fixture の UTF-8 バイト数より小さいこと（親隔離。推定費用は記録し §26.5 の回帰に使う）、(e) 原本 targeted Read による編集の実機ケース。保証経路のケースは原本への Edit が成功し、対象箇所以外が不変であることまで見る。値を答えるだけで Edit していない状態は不合格。
10. Claude CLI が無い開発機では比較 eval を skip してよい。Claude があるのにプラグインをロードできないとき、または直接モードで token-shunt が載っているときは fail。ZIP の出荷条件は A 全必須ケースと B 全ケース（auto、`direct` ベースライン付き）の経路・品質・隔離、および必須親トークン測定（§26.5）。**費用は記録し回帰チェックに使うが、出荷可否の条件にしない。** 実機 skip は不可。

11. §26.5 の手段の検証（モデル選択、小仕事の直接処理、作業量制限）に合格する。リリースゲートは正確性・経路・隔離の実機検証と §26.5 の必須親トークン測定であり、親子合計の推定費用は測定・記録して手段の改訂判断に使う（§26.5）。

検証不能な「親コンテキストに絶対入らない」は成功条件にしない。担保するのはフック deny、worker allowlist、最終メッセージの契約、transcript 付きの比較 eval。

## 4. やらないこと

- Portal / AiKA / Gemini、外部 API を直接呼ぶワーカー。その実装・比較・フォールバック
- code-writer の Write フック強制
- Explore / Grep / `@ファイル` / `sed` / `python -c` による本文取得の封鎖（パイプは末尾コマンドだけ §10-4 で判定する。パイプ全体の解析はしない）
- Cursor / Codex 向け配布
- 請求額 90% 減の再現や、その数字を製品文面に書くこと
- Spotify `shunt@portal` との共存（同時有効にしない）
- 原本 targeted Read で取れない編集。byte-span、dd+temp、未読 Edit 例外による補完
- bulk-reader の関連探索・Grep・Glob、結果再利用・fingerprint（v0.2 以降の検討）

## 5. データの流れ

親の全文 Read → PreToolUse deny → 親が `/token-shunt:bulk-reader` を開く → `Agent(subagent_type=token-shunt:bulk-reader, model=haiku|sonnet)`。渡すのは質問・**読むファイルの明示パス**・必要な短い診断だけ。親は本文を取り込まない。子は 1 起動につき明示された**最大 3 パス**を読み、各領域は 1 回だけ Read して回答で終了する（Read のみ、maxTurns 6。分割条件は §12）。関連先は追わず `unconfirmed` として返す。複数ファイル横断は親が全パスを指定した場合に限り、**同一起動にまとめて渡す**（ファイル間の関係は子が同一コンテキストで見る。親が partial を縫って推測する形にしない）。4 パス以上は 3 パスずつ起動を分け、§26.3 の総起動上限と §11 のバッチ間根拠契約に従って親が統合する。記事の tools なし 1 完了と同一ではなく、認証・権限・実行履歴を Claude Code 内で扱う採用方式である（§26.0）。モデル選択と小仕事判定は §26。編集するなら親が原本へ targeted Read し、成功した本文を確認して Edit する（§11.6）。

定型生成は親が `/token-shunt:code-writer` を開き `Agent(subagent_type=token-shunt:code-writer)`。渡すのは spec・参照パス・target・検証コマンド。子が参照を Read して target に Write。返すのは短い要約。親が検証コマンドを Bash し、§11 の検証段階に従って完了判定する（全文は vis しない）。同一 target への並列起動はしない。上書きは可。

## 6. ディレクトリ

```
token-shunt/
  README.md
  docs/2026-09-12-token-shunt-design.md
  docs/history/2026-09-12-review-decisions.md
  docs/distribution/README.md
  reviews/
  evals/
    run.sh
    hook-evals.json
    bash-hook-evals.json
    fixtures/
    compare/
      run.sh
      cases.json
      gold/
      last-run.json.example
      fixtures/rails/app/models/user.rb
      fixtures/rails/app/models/concerns/notifiable.rb
      fixtures/rails/app/jobs/welcome_email_job.rb
      fixtures/codegen/greeter.py
      fixtures/codegen/out/.gitkeep
      fixtures/edit/.gitkeep
  scripts/build-zip.sh
  .claude-plugin/marketplace.json
  plugin/
    .claude-plugin/plugin.json
    skills/bulk-reader/SKILL.md
    skills/code-writer/SKILL.md
    agents/bulk-reader.md
    agents/code-writer.md
    hooks/hooks.json
    hooks/check-file-size
    hooks/check-bash-read
    hooks/check-jq
```

ZIP 一次成果物は `plugin/` の中身（アーカイブ先頭または一段のフォルダ直下に `.claude-plugin/plugin.json`）。marketplace.json は ZIP に入れない。`--plugin-dir` に渡すのは zip または `plugin/` であり、リポジトリルートではない。

## 7. マニフェスト（全文）

### `.claude-plugin/marketplace.json`

```json
{
  "name": "token-shunt",
  "owner": {
    "name": "skills"
  },
  "metadata": {
    "description": "Delegate large-file reads and boilerplate generation to Claude Code subagents so the parent context stays small."
  },
  "plugins": [
    {
      "name": "token-shunt",
      "source": "./plugin",
      "description": "Hooks block oversized Read/Bash and route to bulk-reader / code-writer subagents."
    }
  ]
}
```

公式 marketplace スキーマの必須は `name`、`owner`（少なくとも `owner.name`）、`plugins`。`owner.name` を欠く JSON は成功条件 8 を満たさない。`email` / `url` は任意で、この仕様では置かない。

### `plugin/.claude-plugin/plugin.json`

```json
{
  "name": "token-shunt",
  "displayName": "Token Shunt",
  "version": "0.1.0",
  "description": "Keep large-file contents and boilerplate output out of the parent context by delegating to Haiku/Sonnet subagents. Requires jq. Do not enable alongside Spotify shunt.",
  "keywords": ["delegation", "context", "hooks"]
}
```

`version` は 0.1.0 で固定する（この仕様の初版）。最低 Claude Code は README に「PreToolUse の stdin に `agent_type` が載る版」と書き、インストール手順でフック stdin を 1 回 dump する doctor を載せる。数値ピンはここに書かない（未実測のため）。doctor は agent_type だけでなく、呼び出し時モデル指定、Haiku/Sonnet の実モデル、effort、maxTurns の partial 終了も検証し、実装時に最低対応版を記録する。

### `plugin/hooks/hooks.json`

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/check-jq",
            "args": [],
            "timeout": 5
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Read",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/check-file-size",
            "args": [],
            "timeout": 10
          }
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/check-bash-read",
            "args": [],
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

`"args": []` は present なので公式どおり **exec form**（shell 無しで `command` を直接 spawn）。3 本ともシェバン（`#!/usr/bin/env bash`）と Unix 実行ビットが必須。`timeout` の単位は秒。

公式: タイムアウトした PreToolUse の command hook は tool call を **block しない**（通常の権限フローへ進む = fail-open）。10 秒は上限であり「必ずそれより早く終わる」保証には使えない。走査は区間閾値の早期打ち切りに加え、§8.6 の走査予算（読み取りバイトと経過時間）で打ち切る。判定不能は deny。予算は timeout より短く取る。遅い FS で予算チェックより先に timeout へ達した場合の素通りは既知の限界（§15）。timeout を延ばして全走査する設計にはしない。

Windows PowerShell ツールは対象外（既知の限界）。

`check-jq`（SessionStart。公式に block 不可、`additionalContext` 可）。**jq を呼んではいけない**（欠落検知そのものが目的。警告 JSON は heredoc で書く）:

1. `command -v jq >/dev/null` なら stdout 空、exit 0。
2. 無ければ exit 0 で次を出す（セッションは止めない。PreToolUse 側が exit 2 で全 Read/Bash を止める）:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "token-shunt: jq is not on PATH. PreToolUse hooks fail-closed (exit 2) on every Read and Bash until jq is installed."
  }
}
```

決定の出し方（PreToolUse。公式 Hooks に合わせる）:

- **通過（サイズゲート非該当・閾値以下・worker）:** stdout 空、exit 0。JSON を出さない。`permissionDecision` を出さない。これは「決定なし」であり、通常の権限確認・他フックの deny/ask がそのまま評価される。
- **deny:** exit 0 で次の JSON だけを出す。Spotify の `{"decision":"block"}` は使わない。

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "<jq --arg で組んだ短文>"
  }
}
```

`permissionDecision: "allow"` は使わない。公式仕様では `"allow"` はインタラクティブな権限確認を省略する。本プラグインの matcher はすべての Read とすべての Bash に付くため、通過を `"allow"` にすると `git status` まで自動承認する。`"ask"` も出さない。

## 8. フック共通

スクリプト先頭（PreToolUse の 2 本。`check-jq` は §7）:

1. `command -v jq >/dev/null` でなければ stderr に `token-shunt: jq is required` を書き、stdout 空、exit 2。
2. stdin を JSON として `jq` で読む。失敗も exit 2。
3. 環境変数:
   - `TOKEN_SHUNT_MIN_LINES`: 空または非整数（符号付き整数以外）なら 350。整数ならその値。`0` は 0。負は 350。
   - `TOKEN_SHUNT_MIN_BYTES`: 同様。既定 65536。負は 65536。
   - `TOKEN_SHUNT_SCAN_BUDGET_BYTES`: 空または非整数なら 8388608。整数ならその値。`0` は 0（直後に打ち切り）。負は 8388608。
   - `TOKEN_SHUNT_SCAN_BUDGET_MS`: 同様。既定 2000。負は 2000。`0` は直後に打ち切り。
   - `TOKEN_SHUNT_HOOK_LOG`: **本番は未設定。** 判定を変えない。非空なら決定を 1 行 JSON 追記するフォールバック（比較 eval が `--include-hook-events` の `hook_response` を取れない古い CLI 用）。一次証拠は CLI フラグ側（§13）。
4. worker allowlist（完全一致。suffix マッチしない。素の `bulk-reader` はサイズゲート対象のまま）:
   - `check-file-size`: `token-shunt:bulk-reader` または `token-shunt:code-writer` → **通過**。
   - `check-bash-read`: `token-shunt:bulk-reader` のみ → **通過**。`code-writer` は tools に Bash が無いのでここに載せない。
5. path はクォートして扱う。reason に生 path を長く載せない。載せるなら jq `--arg` のみ。
6. 行範囲は **平均行長で推計しない**。ヘルパー `range_scan(path, start_line, line_count)` を使う。判定に全走査は不要。区間閾値の早期打ち切りは、巨大ファイルの **開始行までの読み飛ばし** を制限しない。読み飛ばしを含めた走査量と時間に別予算を置く。
   - `start_line` は 1 始まり。区間は `[start_line, start_line + line_count)`。EOF を超えた分は含めない。
   - ファイルをバイト列として `\n` で行に分け、各行のバイト数は内容＋その行が持つ改行バイト（最終行に `\n` が無ければ付けない）。
   - **区間閾値:** 対象区間について走査中に `lines > MIN_LINES` または `bytes > MIN_BYTES` になった時点で打ち切る（`MIN_* + 1` に達した時点）。
   - **走査予算（対象区間とは独立）:** 開始行までの読み飛ばしと対象区間の両方で、ファイルから読んだ累計バイト `read_bytes` と走査開始からの経過 `elapsed_ms` をチャンクごと（少なくとも各行の処理後）に見る。`read_bytes > SCAN_BUDGET_BYTES` または `elapsed_ms > SCAN_BUDGET_MS` なら直ちに打ち切る。
   - **巨大行対策の実装補足（2026-09-13）:** 行パーサーの前段で入力を1走査あたり予算＋1バイトに制限する。先頭走査は `head -c`、末尾走査は `tail -c` の後に行選択を行い、末尾改行の確認には別途1バイトを取得する。判定後も制限済み入力を消費し、パイプの読取失敗を終了ステータスで確認する。`read_bytes` は判定までに数えた値であり、OSやユーティリティの内部先読み量を保証する値ではない。現実装の時間判定はこの有界走査の終了後であり、ブロックしたFS読み取りを中断しない（§15の既知の限界）。
   - 戻り値: `{ exceeded, undetermined, lines, bytes }`。
     - 区間閾値で打ち切った: `exceeded=true`、`undetermined=false`、`lines`/`bytes` は下限（正確な区間合計を要求しない）。
     - 走査予算で打ち切った: `exceeded=true`、`undetermined=true`。`lines`/`bytes` は対象区間で見えた下限（読み飛ばし分は区間値に入れない）。
     - 区間を EOF まで終えた: `undetermined=false`、`exceeded` は閾値比較、`lines`/`bytes` は実測。
     - 開始が EOF を超える: `{false, false, 0, 0}`。
   - deny reason の `<n>` / `<b>` は、区間打ち切りなら `>=MIN+1` と書いてよい。走査予算打ち切りなら `scan budget exceeded (read_bytes=<r>/<budget_bytes>, ms=<t>/<budget_ms>)` を理由に含める。全区間合計を測って埋めない。
   - `undetermined=true` は **deny**（判定不能を通過にしない。worker は allowlist で走査しない）。
   - `tail` の末尾 N 行: 末尾から数えて N 行に達するか、蓄積バイトが `MIN_BYTES` を超えた時点、または走査予算を超えた時点で打ち切る。ファイル先頭まで戻っても N 行に満たず両閾値以下かつ予算内なら超過ではない。`total_lines` の全数は取らない。この経路は **解釈できた正の行数 N** にだけ使う。`tail -n +1` のような `+N` には使わない。
7. 全文判定（早期通過と `cat`）:
   - バイト: 通常ファイルの `st_size`。シンボリックリンクはリンク先のサイズを測り、通常ファイル判定・実際の読み取りと対象を一致させる（GNU `wc -c` が `st_size` を使う実装でも可）。`st_size > MIN_BYTES` なら行を数えない。
   - 行: `MIN_LINES + 1` 行に達した時点、または走査予算を超えた時点で打ち切る。全ファイルの `wc -l` はしない。予算超過は deny。
   - 解釈できた targeted Read / `head -n` / `tail -n` は `range_scan`。解釈できた `head -c` / `tail -c` は `min(要求バイト, st_size)`（走査なし）。解釈不能な head/tail は全文判定に戻す。

通常ファイルでない（ディレクトリ、存在しない、空 path）は **通過**（ツール側のエラーに任せる）。

**Read の除外拡張子**（`check-file-size` のみ。Bash の `cat` には適用しない）: path の最終拡張子を ASCII で小文字化して次のいずれかなら **通過**（サイズを見ない）。

`.png` `.jpg` `.jpeg` `.gif` `.webp` `.bmp` `.ico` `.tif` `.tiff` `.avif` `.heic` `.heif` `.pdf` `.ipynb`

根拠: 公式 Read は画像を視覚コンテンツとして返し、リサイズ後も 500KB 超なら JPEG 再圧縮する。PDF は `pages`、`.ipynb` はセル経路。64KiB 超のスクリーンショットを bulk-reader（テキスト分析子）へ誘導すると親は画像を見られない。`.svg` は XML テキストとして扱い、除外しない。

それ以外のバイナリ（NUL だらけの `.bin` 等）は `range_scan` / `st_size` で測る。バイト閾値超なら deny。

## 9. check-file-size

入力: `tool_input.file_path`, `tool_input.offset`, `tool_input.limit`（欠けるキーは空）。

手順:

1. 共通 1–4。
2. path 空 or 通常ファイルでない → 通過。
3. 除外拡張子（§8）→ 通過。
4. 全文が両閾値以下（`st_size ≤ MIN_BYTES` かつ、行は `MIN_LINES + 1` 未満で EOF）→ **通過**。`offset` / `limit` は見ない。10 行ファイルへの `Read(limit=400)` はここ。成功条件 6。
5. ここから先は、ファイルが少なくとも一方の閾値を超えている。
6. `limit` が空 → 全文扱い → deny（すでに閾値超）。offset だけで limit が無い場合もここ。
7. `limit` がある:
   - 整数でない、または `limit < 1` → deny（不正な targeted）。
   - `offset` が空なら開始行 1。整数でない、または `offset < 1` なら deny。
   - **単一行の例外は置かない。** `limit == 1` も他と同じく `range_scan(path, offset, 1)` で判定し、その 1 行が `MIN_BYTES` を超えるなら deny。理由: 1 行が小さければ例外なしでも区間判定を通るので、例外が実際に効くのは「単一行が `MIN_BYTES` 超」の場合だけであり、それは 64KiB 超の本文を親に載せる唯一のケースになる（70KiB ≈ 17.5k トークンで公式 Read の上限にも掛からず親に着地する）。巨大行の編集は §11.6 で v0.1 対象外なので、例外の目的も無い。
   - `limit >= 1` の実際の対象は `range_scan(path, offset, limit)`。`exceeded`（区間閾値または走査予算）なら deny。走査予算は開始行までの読み飛ばしにも適用する（予算超過なら deny、`undetermined`）。
   - 要求 `limit` が `MIN_LINES` を超えていても、区間が EOF で切れ、実測 lines/bytes が両方閾値以下で予算内なら通過。平均行長は使わない。
   - 大きいファイルへ `limit=400` のように、実範囲が閾値を超える要求は deny。

deny reason の骨子（英語、短く）:

`File exceeds token-shunt thresholds (lines=<n>/<min_lines>, bytes=<b>/<min_bytes>). Use /token-shunt:bulk-reader. For edits, use a targeted Read of the original that passes the hook. If that fails, editing is outside v0.1 scope.`

走査予算で deny するときは上に加えて `Scan budget exceeded; use /token-shunt:bulk-reader for analysis. Editing still requires a successful targeted Read of the original.` を含める。

## 10. check-bash-read

入力: `tool_input.command`。

手順:

1. 共通 1–4。
2. command 空 → 通過。
3. 先頭末尾空白を trim。
4. **引用を踏まえた演算子スキャン。** 状態は通常 / 単一引用 `'` / 二重引用 `"` / バックスラッシュ。引用内とエスケープ直後の文字は演算子ではない。引用外の単語開始位置の `#` から改行直前まではコメントとして無視する。引用内の `#`、`file#name`、エスケープした `\#` はリテラルとして扱う。コメント後の改行と次のコマンドは通常どおり判定する。`$('` / `$(` / バッククォート、または閉じない引用は **解釈不能**。シェル全体の構文解析は行わない。下記の複合セパレータ判定をパイプ・リダイレクトの早期通過より先に適用する。
   - **パイプ（末尾コマンドで判定）:** 引用の外の単独 `|`（`||` ではない）または `|&` があるとき、**パイプラインの最後の単純コマンド**の basename で決める。記事の「パイプは targeted read だから通す」という理由は絞り込み側にしか当てはまらないので、結論だけを全パイプへ広げない。
     - 出力を絞る側（`grep` / `rg` / `awk` / `sed` / `jq` / `wc` / `sort` / `uniq` / `cut` / `python` / `python3`、および未知のコマンド）→ **通過**。`cat large | grep foo` はここ。未知コマンドの通過は意図した fail-open（§15）。
     - `head` / `tail` → 末尾コマンドがファイル引数・リダイレクトを持たず stdin だけを読む場合、§10-7 の解釈できるバイト形式 `-c C` で `C ≤ MIN_BYTES` のときだけ通過（バイト形式では行数は見ない）。行形式と既定 N=10 は出力バイト数不明なので **deny**。解釈不能、閾値超、ファイル引数・リダイレクト付きも deny。入力元の推測やパイプ全体の走査はしない。小さい行範囲を読みたい場合は `head -n N file` / `tail -n N file` または原本 targeted Read を使い、実バイトを判定する。
     - 絞り込みをしない側（`cat` / `tee` / `less` / `more`）→ 早期通過しない。パイプライン各段の既知の読み込みコマンド（`cat` / `head` / `tail` / `less` / `more`）の明示入力ファイルを全文閾値で判定する。`cat large | cat`、`cat small | cat large`、`cat small | cat large | cat` は **deny**。`tee` の引数は出力先なので入力ファイルとして検査しない。
     - 末尾コマンドを解釈できない（`$(` / バッククォート / 閉じない引用）→ 早期通過しない。先頭の単純コマンドを全文閾値で判定する（fail-closed）。
     - `cat 'large|name.txt'` の `|` は引用内なのでパイプではない。
   - **複合セパレータ:** 引用の外の `;` / `&&` / `||` / 改行 / 文末以外の `&`（`&&` `>&` `2>&1` `|&` の一部ではない）。引用を保持して各区間に分け、各区間のパイプ段の先頭トークンをステップ 5 と同じ規則で調べる。サイズ対象（`cat`/`head`/`tail`/`less`/`more`）の明示された通常ファイルをステップ 6・§8.7 の全文閾値で判定し、いずれか超過なら deny。全区間を調べ終えるまで通過しない。複合ではパイプ末尾やリダイレクトによる早期通過を使わない。`cat large; echo ok > /tmp/status` と `echo ok; cat large` はともに deny。変数展開・コマンド置換からのパス解決や stdin の追跡は行わず、明示パスが無い経路は保証しない。
   - **先行 cd の相対パス:** 先頭から連続するリテラル `cd <dir>` / `cd -- <dir>` を `&&` / `;` / 改行でつないだ場合は、移動先を後続のファイル引数の基準にする。フック内の組み込み cd でディレクトリだけを変更し、入力コマンドは実行・evalしない。`||`・バックグラウンド・グループ構文・変数等の展開・他の cd オプション・他コマンド後の cd・非空 CDPATH に依存する相対ディレクトリは追跡範囲外。この範囲外で確実にサイズ判定するには絶対ファイルパスを指定する。
   - **リダイレクト早期通過:** 複合でもパイプでも解釈不能でもない単一コマンドに限り、stdout をファイルへ切る `>` / `>>`（直前が `2` でも `&` でもない。`2>&1` / `>&` / `&>` が無い）→ 出力先が通常ファイル（新規パスを含む）または `/dev/null` の場合だけ通過。stdout/stderr に戻るパス（`/dev/stdout`、`/dev/stderr`、`/dev/fd/*`、`/proc/*/fd/*` 等）、同一 inode 比較および利用可能な `readlink -f` で判定できる同等のリンク先、その他の特殊ファイル、展開等で確定できない出力先は入力ファイルの通常判定へ戻す。複数の stdout リダイレクトは全ての出力先がこの条件を満たす場合だけ早期通過する。リダイレクトは**対象コマンドに属するときだけ**通過理由にする。
   - 解釈不能でサイズ対象がある → 全文閾値（fail-closed）。
5. （ステップ 4 で判定しなかった単一コマンドまたは単独パイプライン）先頭の `VAR=val` を繰り返し除去。残りの最初のトークンの basename が `cat` / `head` / `tail` / `less` / `more` でなければ **通過**（`git status` を含む。`"allow"` は出さない）。単独パイプラインの非縮約末尾はステップ 4 の各段判定で完了する。解釈不能な末尾からのフォールバックでは先頭の単純コマンドだけを見る。複合コマンドはステップ 4 の全区間判定で完了し、ここへ落とさない。
6. 残りの引数から `-` で始まるフラグを除いた通常ファイルを対象にする。対象が 0 なら通過。
7. `head` / `tail`。サイズに影響するオプションだけを集める（`-q` / `-v` / `--quiet` / `--verbose` / `--` は無視してよい）:
   - 行形式: `-n N` / `-nN` / `--lines=N` / `--lines N` / `-[0-9]+`（数字だけのショート）。
   - バイト形式: `-c N` / `-cN` / `--bytes=N` / `--bytes N`。
   - **解釈できる行数:** サイズ影響オプションがちょうど 1 つ、行形式、N が先頭 `+`/`-` なしの符号なし整数で `N ≥ 1`。
     - 各対象について `head` なら `range_scan(path, 1, N)`、`tail` なら末尾 N 行の `range_scan`。`exceeded` なら deny。
     - 行数指定が小さいことだけを理由に通過させない（1 行 70KiB の `head -n 1` は deny）。
   - **解釈できるバイト数:** サイズ影響オプションがちょうど 1 つ、バイト形式、C が先頭 `+`/`-` なしの符号なし整数。
     - 各対象について `actual = min(C, st_size)`。`actual > MIN_BYTES` なら deny。行数は見ない。
     - `head -c 70000` は C=70000 なので大きいファイルでは deny（フックの fail-closed。親への inline は Claude Code 側が約 30,000 文字で切る。§15）。`head -c 100` は 100 バイトなので通過。小さいファイルは `min(C, st_size)` で通過。
   - **サイズ影響オプションが 0:** 既定 N=10（GNU/BSD）として、解釈できる行数と同じ。
   - **解釈不能:** `+N`（`tail -n +1` は 1 行目以降全部）、負の N（`head -n -10` は末尾 10 行以外全部）、`-n` と `-c` の混在、サイズ影響オプションの重複、非整数。GNU の `head -n +N` と `tail -n +N` は意味が違うので、`+` が付いた時点で解釈しない。
     - 各対象を `cat` と同じ全文閾値で判定する。大きいファイルは deny、両閾値以下の小さいファイルは通過。
8. `cat` / `less` / `more`: 対象ファイルのいずれかが通常ファイルかつ、全文判定（§8.7）で超過なら deny。画像拡張子でも Bash は除外しない（`cat` はバイトを親へ流す）。
9. それ以外は通過。

`cat f1 f2` はどれか 1 つでも超過なら deny。

deny reason: Read 側と同じ誘導。`cat/head/tail` を名指しする。

## 11. スキル

両スキルとも `description` はトリガーと禁止トリガーだけ。手順は本文。呼び出し名はプラグイン名前空間で `/token-shunt:bulk-reader`。

スキル frontmatter に `agent:` と `context: fork` は付けない。公式に `agent` は `context: fork` のときだけ使う subagent type であり、fork 無しでは無効。fork にするとスキル本文が子のプロンプトになり、親が `Agent(subagent_type=...)` を呼ぶ本設計と衝突する。親が Explore / 素の `bulk-reader` を選ぶ指示は本文に書かない。

### bulk-reader `description`

Use when a Read or Bash hook blocked an oversized file or the needed I/O exceeds the small-task budget. Keep small targeted reads in the parent; file count alone is not a trigger. Do not use for debugging, architectural decisions, or edits that need exact contents in the parent context. Do not @-mention large files.

本文の固定手順:

1. 本文先頭に §26.1 のモデル引数解釈と Agent 呼び出し規約を置く。未知値なら Agent 起動前にエラー。§26.2 の小仕事は親が直接処理する（機構強制 eval は例外）。
2. 委譲プロンプトは質問・読むファイルの明示パス・**各パスのサイズと行数**（§26.2 のメタデータ判定で得た `wc -lc` の値）・短い診断だけ。行数は、Read ツールが全文読取を拒否したとき子が連続・非重複に分割するために要る（§12）。親は本文を読まない・貼らない。`subagent_type` は `token-shunt:bulk-reader` のみ。
3. subagent は 1 起動 = 明示最大 3 パス。**ファイル間の関係を問う質問は 3 パスを同一起動に渡す**（子が同一コンテキストで関係を見る。親が 1 ファイルずつの partial を縫って推測する形にしない。推測だけの正答は §13 で fail）。4 パス以上は 3 パスずつ起動を分け、親は次のバッチ間根拠契約に従って短い回答を統合する。再試行・境界確認込み総起動 4 回（新規パスだけを読める場合は最大 12 パス）を超える要求は、**起動前に範囲縮小を求める**（partial を受け入れて打ち切らない。§26.3）。Read / コンテキスト上限で読めなければ partial。複数起動と親による要約統合の費用を §26.5 で計上する。
   - **バッチ間根拠契約:** ファイル数による分割だけで回答品質が保証されるとは扱わない。親は各子へ、質問に必要な参照元 path・シンボル・参照先の識別子を既存の 4000 字上限内で返すよう指示する。親は一致が確認できる事実だけを統合する。名前の類似や呼出先の推測から関係を `confirmed` にしない。関係が不足・曖昧なら、残り起動予算内で質問あたり最大 1 回、境界のファイルを同じ子へ明示して確認できる（各起動内では各パス Read 1 回を維持）。確認できなければ該当関係を `unconfirmed`、親の結果を partial とする。独立した事実の集約と、複数バッチの本文を比較しないと答えられない質問を区別する。partial を正答課題の成功には数えない。
4. 子は指定ファイルの**各領域を 1 回だけ** Read して回答する（通常 1 パス 1 Read、Read ツールが全文を拒否したときのみ渡された行数から連続・非重複に分割。§12）。関連先の探索はしない。必要パスが足りなければ不足を親に返す。親が追加パスを決める判断は別作業であり、自動探索ループにしない。
5. 追質問は新規起動で同じパスを再送する。resume・回答索引は使わない。本文は親コンテキストに入らないが、子の再入力は有料で、費用測定に含める。
6. **編集契約（§11.6）:** 位置の正本は親の Grep（短い一意パターン、行番号付き・出力制限あり）または現在の原本で確認済みの既知範囲。子の行番号はヒントに限定し、そのまま offset に使わない。Grep が複数一致なら親が絞り込み、一意にできなければ編集しない。親が原本へ `Read(offset, limit)` し、フック通過・ツール成功・対象原文の取得を確認してから Edit する。PARTIAL や省略で対象原文を確認できない結果は使わない。`limit=1` も区間バイト閾値・走査予算・公式 Read 上限により失敗しうる（単一行が `MIN_BYTES` 超なら §9.7 で deny）。失敗時は編集不能の範囲を報告する。byte-span、dd+temp、未読 Edit 例外で補完しない。`head -c` / `tail -c` は §10 の閲覧として残すが、v0.1 の編集保証経路には含めない。
7. フックが Explore 等の子で deny したら、親が自分でこのスキルを起動する。Explore に大きな Read をやり直させない。
8. **本文検索より前に経路を決める（2026-09-13 追加、§26.5 B 群）:** 経路判定はメタデータ（`stat` / `wc -lc`）で行い、対象ファイルの**本文検索より前**に確定する。Grep の `output_mode=content`（`-o`、`-A`/`-B` を含む）と `head -c` はフック対象外なので、小仕事予算超過と分かっているファイルからでも本文を親へ引き出せてしまい、判定を後から無意味にする。超過が分かっているファイルに対しては、答えを探すための本文検索を行わず委譲する。同ファイルへの本文検索は、§11.6 の編集契約のための**位置特定**と既知範囲の確認に限り、`output_mode=files_with_matches` または短い `head_limit` で使う。この穴はフックでは塞げない（§15）ので、契約と eval で担保する。

### code-writer `description`

Use for substantial tests, config, docstrings, type stubs, or generation where more than 80% is predictable from a reference file. Keep small generation in the parent under the small-task policy. Do not use for novel logic, debugging, or safety-critical code.

本文の固定手順:

1. SKILL.md 本文先頭に §26.1 のモデル引数規約と呼び出し例を固定する。未知値は起動前エラー。§26.2 の小仕事なら親が直接生成・検証する。参照ファイルパスが無ければこのスキルを使わず、親が小さく書く。ただし小仕事判定に優先するものが 2 つある（2026-09-13 追加）:
   - **明示的な委譲指示**（機構試験や「worker を起動」「親で生成しない」等）。サイズは既定であって、明示指示を覆す拒否権ではない。§13 の機構強制ケース A はここに当たる。
   - **指定されたが読めない参照**。「参照パスが無い」は**パスが 1 つも渡されていない**場合を指す。渡されたパスが不存在・読取不能・サイズ取得不能な場合は別で、親が `stat` / `wc -c` の失敗で停止してはならない。委譲し、子の「参照が読めなければ Write せず理由とパスだけ返す」契約（§12）を実際に働かせ、その結果を親が報告する。
2. `subagent_type` は `token-shunt:code-writer` のみ。`model` は §26.1 で選ぶ。spec、参照パス、target、**検証コマンド**を渡す。検証コマンドは target パスだけを引数にし、本文を stdout に出さない。spec が検証を指定しないときは次の**汎用フォールバック**を使う。検証コマンドが書けないことを理由に親が自分で生成すると、生成本文がそのまま親の**出力トークン**として親に入り目的が失われる（記事が code-writer の主用途に挙げる config / docstring / 型スタブ / doc は、まさに自然な検証コマンドが無い形式）。
   - `.py`: `python -m py_compile <target>`（テストなら `python -m unittest <target>`）
   - `.json`: `jq empty <target>`
   - `.yaml` / `.yml`: `.md` と同じ最小契約チェック（PyYAML は実行時依存にしない。構文の正しさは保証しない）
   - `.toml`: `python -c "import sys,tomllib;tomllib.load(open(sys.argv[1],'rb'))" <target>`（`tomllib` は 3.11+。ImportError なら最小契約チェックへ落とす）
   - 構文検証が無いテキスト形式（`.md` など）: **最小契約チェック**。ファイルが非空、コード出力全体を包む不要な fence が無い、行数が spec の見積もりと桁違いでない。Markdown 本来のコードブロックは許容する。空ファイルや粗い形式不備の検査であり、内容の正しさ・途中打ち切りの検出は保証しない。親が Bash で判定し、本文は stdout に出さない
   - 上のいずれにも当てはまらず最小契約チェックすら定義できない対象に限り、このスキルを使わない
3. 同一 target は直列。並列は target が互いに素なときだけ。
4. 親は生成コードを vis しない。続きは今書いたファイルを次の参照にする。
5. 子の要約だけでは完了しない。親が検証コマンドを Bash し、exit 0（unittest なら `Ran N tests` かつ `N ≥ 1`、FAIL/ERROR 無し）を確認する。結果は `verification: minimal|syntax|requirements` と検証範囲を短く報告する。最小チェックは `minimal`、py_compile / jq empty / TOML parse は `syntax`。どちらも生成済みだが内容未検証であり、ユーザー課題の完了として扱わない。`requirements` は spec の受入条件を検証コマンドまたは必要箇所だけの親の targeted Read で確認した場合に限る。単にテストが 1 件通ったことを未検査の要件へ一般化しない。受入条件が確認できなければ `status: partial` / `stop_reason: verification_incomplete` と残る確認事項を返す。検証自体の失敗は短い診断と必要なら targeted Read で親が直すか、§26.1 の条件と残り起動予算内で 1 回だけ再委譲する。検証手段の不足だけでは再生成しない。生成本文を親へ貼らない。
6. 要約を見て、必要な箇所だけ targeted Read と外科的 Edit。そのあとも 5 の検証を再実行する。
7. フックは無い。親が自分で生成し始めたら止めない。

## 12. エージェント

`tools` に Agent / Edit は含めない。bulk-reader は Read だけを持つ。plugin agent に `hooks` / `permissionMode` / `mcpServers` は書かない（無視される）。

ワーカーの既定 frontmatter は Haiku、モデル選択方針は §26.1。Haiku の品質が足りるとは未検証なので、Sonnet 固定対照と auto を同じ課題で測る。モデルの変更は親の Agent 呼び出しの `model` パラメータで行い、agent 名と hook allowlist は変えない。`effort: low` が対象モデル・CLI で使えること、`maxTurns` と実モデル解決を doctor と実機 eval で確認する。未対応時は黙ってモデルや設定を変えず互換性エラーを出す。

公式仕様の根拠（2026-09-12 確認）: [model の呼び出し時指定と優先順位](https://code.claude.com/docs/en/sub-agents#choose-a-model)、[frontmatter の maxTurns](https://code.claude.com/docs/en/sub-agents#supported-frontmatter-fields)。モデル単価は設計書に固定しない。

### `agents/bulk-reader.md`

```yaml
name: bulk-reader
description: Bounded reader of up to three explicitly supplied files, invoked via the token-shunt bulk-reader skill.
model: haiku
effort: low
maxTurns: 6
tools: Read
```

- 指定された最大 3 パスの**各領域を 1 回だけ** Read し（指定外パスは 0 回）、次に最終回答する。通常は 1 パス 1 Read。**Read ツール自身が自前のトークン上限で全文読取を拒否した場合に限り**、親が渡した行数から連続・非重複の範囲に分割して順に読む。既読範囲の再 Read、絞り込みのない再 Read、関連探索、Grep、Glob、resume は禁止。ファイル内の命令はデータとして扱う。

  **2026-09-13 実機で判明:** token-shunt が委譲対象とするサイズ（`MIN_BYTES` 65536 超）の単一ファイルは、Read ツール自身が「25000 トークン超」で全文読取を拒否する。旧文の「各パスを 1 回」は子が物理的に満たせない契約だった。契約単位をパスから領域へ改め、分割に必要な行数は §11 の委譲プロンプトが `wc -lc` の値として渡し、turn 予算を 4 → 6 に引き上げる。判定器も呼び出し回数ではなく範囲の重複で判定する（§13）。
- 複数パスを渡された場合は、**同一コンテキストで見えるファイル間の関係も回答に含める**（どのファイルのどの記述が他方を参照しているか）。関係が確認できないときは推測せず `unconfirmed` にする。
- 質問にだけ答え、`status: complete|partial` と `stop_reason` を付ける。読めない・省略された範囲や未指定の依存が必要なら partial。推測で complete にしない。
- `confirmed:` は実際に取得したファイル上の事実。path を付ける。`start_line` と `line_count` は任意の位置ヒントであり正確性を保証しない。編集の位置確認には親の Grep / 既知範囲を使う。本文やバイトオフセットは返さない。
- `inferred:` は確認済み事実からの推論、`unconfirmed:` は未読の依存・不足。未指定パスを開いて補完しない。
- 最終回答は構造化箇条書きで 4000 文字以下。**この上限は起動あたりであり、パス数で増やさない**（3 パスを 1 起動にまとめる主眼の一つは、1 ファイル 1 起動で 4000 字 × 起動数が親に入るのを避けることにある）。本文・大きな引用・コードフェンスは載せない。行番号が分からないときは捏造せず不足として返す。バッチ統合用の質問では、必要な参照元 path・シンボル・参照先識別子をこの上限内に含める。

### `agents/code-writer.md`

```yaml
name: code-writer
description: Boilerplate writer invoked only via the token-shunt code-writer skill.
model: haiku
effort: low
maxTurns: 12
tools: Read, Write, Grep, Glob
```

- 参照のパターン・命名・スタイルに合わせる。曖昧なら参照側に合わせる。
- target にコードだけ Write する。markdown fence で包まない。既存 target は先に Read する。再試行と予算は §26.1 / §26.3 に従う。
- 最終メッセージは書いたパス、行数、3〜5 bullet。生成コードを貼らない。上限 800 文字。
- 参照が読めない、spec がコード生成でない、Write できないときは Write せず、理由とパスだけ返す。コードを返信に載せない。

`CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` のときは モデル選択が上書きされる。README の doctor で警告し、モデル比較は実モデルが一致しなければ失敗にする。

## 13. テスト

`evals/run.sh` が Claude 無しでフックを stdin JSON → stdout 決定 / exit code で検証する。fixture ファイルは `evals/fixtures/`。

通過の期待はすべて **exit 0 かつ stdout に `permissionDecision` が無い**（空 stdout）。deny は exit 0 かつ `permissionDecision` が `"deny"`。`"allow"` が 1 件でも出たらそのケースは失敗。

必須ケース（これ以外を足してよい。減らさない）:

| id | 対象 | 期待 |
|---|---|---|
| jq-missing | PATH から jq を外す | exit 2、stdout に決定 JSON を出さない |
| read-small | 349 行かつ 64KiB 未満 | 通過 |
| read-over-lines | 351 行 | deny |
| read-minify-1-line | 1 行 70KiB、limit なし | deny |
| read-limit-1-minify | 1 行 70KiB、limit=1 | deny（§9.7。単一行例外は置かない。区間バイトが MIN_BYTES 超） |
| read-scan-budget-offset | run.sh が 9MiB 超の短行ファイルを生成（リポジトリに置かない）。offset が末尾付近、limit=10 | deny（対象区間は小さいが走査予算超過。reason に scan budget）。worker では通過 |
| read-limit-ok | 400 行・20KiB、limit=20 | 通過（実バイトが閾値以下） |
| read-limit-too-big | 400 行ファイルに limit=400 | deny（実範囲が行閾値超。小さいファイルは次行） |
| read-small-limit-400 | 10 行・1KiB に limit=400 | 通過（全文が両閾値以下。要求 limit では拒否しない） |
| read-offset-only | offset=1、limit なし、ファイル超過 | deny（全文扱い） |
| read-limit-skew-deny | 先頭 100 行が各 1001 バイト、残り 900 行が空行。limit=100 | deny（実バイト ≈100100。平均なら ≈10100 で通過してしまう反例） |
| read-limit-skew-pass | 先頭 100 行が 2 バイト、残り 900 行が各 1001 バイト。offset=1 limit=100 | 通過（実バイトは小さい。平均なら拒否されてしまう反例） |
| read-worker | agent_type=`token-shunt:bulk-reader`、大きいファイル | 通過（`"allow"` ではない） |
| read-bare-agent | agent_type=`bulk-reader`、大きいファイル | deny |
| read-explore | agent_type=`Explore`、大きいファイル | deny |
| read-image-png | 200KiB 超の PNG（マジック付き） | 通過（視覚経路。bulk-reader へ誘導しない） |
| read-pdf | 200KiB 超の PDF（`%PDF` ヘッダ） | 通過 |
| read-ipynb | 200KiB 超の `.ipynb` | 通過 |
| bash-unrelated | `git status` | 通過。stdout に `"allow"` が無い |
| bash-cat-large | `cat large` | deny |
| bash-usr-bin-cat | `/usr/bin/cat large` | deny |
| bash-cat-stderr | `cat large 2>/dev/null` | deny |
| bash-cat-2and1 | `cat large 2>&1` | deny |
| bash-pipe | `cat large \| grep foo` | 通過 |
| bash-pipe-cat | `cat large \| cat` | **deny**（§10-4。末尾が絞り込み無しの `cat`。記事のパイプ全通過は踏襲しない） |
| bash-quoted-pipe-name | `cat 'large\|name.txt'` を 80KiB 超の通常ファイルに | **deny**（引用内の `\|` はパイプではない。記号の包含だけで通過させない） |
| bash-pipe-head-line | `cat large \| head -n 1`（1 行 70KiB） | deny（行指定からバイト上限は分からない） |
| bash-pipe-head-default | `cat small \| head` | deny（stdin の行指定。単独 head へ誘導） |
| bash-pipe-head-bytes | `cat large \| head -c 100` / `head -c 70000` | 前者通過、後者 deny |
| bash-pipe-tail-line | `cat large \| tail -n 1` | deny |
| bash-pipe-tail-bytes | `cat large \| tail -c 100` / `tail -c 70000` | 前者通過、後者 deny |
| bash-pipe-head-file | `cat small \| head -c 100 large` | deny（ファイル引数付き末尾は早期通過しない） |
| bash-compound-later-cat | `echo ok; cat large` / `echo ok && cat large` | ともに deny（全区間の明示パスを判定） |
| bash-compound-pipe | `cat large; echo ok \| head -c 1` | deny（複合判定が先。末尾の短い出力で通さない） |
| bash-compound-small | `echo ok; cat small` | 通過（全対象が閾値以下） |
| bash-compound-redirect | `cat large; echo ok > /tmp/status` を 80KiB 超ファイルに | **deny**（複合。後続のリダイレクトは cat の通過理由にしない） |
| bash-redirect | `cat large > /tmp/out` | 通過（単一コマンドに属する stdout リダイレクト） |
| bash-cat-png | `cat` を 200KiB PNG に | deny（Bash は除外拡張子を見ない） |
| bash-head-n-20 | `head -n 20` を 400 行・20KiB に | 通過（20 行の実バイトが閾値以下） |
| bash-head-n-1-minify | `head -n 1` を 1 行 70KiB に | deny（行数指定では回避できない） |
| bash-head-c-70000 | `head -c 70000` を 80KiB ファイルに | deny（解釈できた `-c` が MIN_BYTES 超。親 inline は CLI が約 30,000 文字で既に切る。根拠は「70,000 バイトが親に載る」ではない） |
| bash-head-c-100 | `head -c 100` を 80KiB ファイルに | 通過（要求 100 バイト ≤ MIN_BYTES） |
| bash-head-c-window | `head -c 8192` を 80KiB 超ファイルに（リダイレクト無し） | 通過（解釈できた `-c` ≤ MIN_BYTES。公式の原本閲覧になりうる） |
| bash-tail-c-window | `tail -c 8192` を 80KiB 超ファイルに（リダイレクト無し） | 通過（同様） |
| read-edit-window-dense | `a\n` × 4096（8192 バイト・4096 行）への全文 Read | **deny**（8KiB 以下でも行閾値超。両閾値以下の断定の反例） |
| read-edit-window-dense-limit | 同じファイルへ `limit=20` | 通過（targeted。実測 20 行・40 バイト） |
| bash-head-n-400-small | `head -n 400` を 10 行・1KiB に | 通過（走査行数は 10。要求 N では拒否しない） |
| bash-tail-n-plus-1 | `tail -n +1` を 80KiB ファイルに | deny（`+N` は解釈不能 → 全文閾値。親 inline 上限とは独立の fail-closed） |
| bash-head-n-and-c | `head -n 1 -c 70000` を 80KiB ファイルに | deny（混在は解釈不能 → 全文閾値） |
| bash-head-full | `head` を 400 行・各行ちょうど 50 バイト（改行込み）の fixture に（既定 N=10） | **通過**（先頭 10 行 = 500 バイト。条件付き散文にしない） |
| path-space | 空白を含む大きいファイルの Read | deny、JSON が parse できる |
| worker-code-writer-read | agent_type=`token-shunt:code-writer`、大きいファイルの **Read** | 通過。Bash 側の同等ケースは作らない（tools に Bash が無く到達しない） |
| zip-exec-bits | `scripts/build-zip.sh` の成果物 | `hooks/check-file-size` / `check-bash-read` / `check-jq` が zip 内で実行ビット付き |
| sessionstart-jq-missing | PATH から jq を外して `check-jq` に SessionStart stdin | exit 0、`additionalContext` に jq 欠落の警告。block JSON を出さない |
| marketplace-schema | `.claude-plugin/marketplace.json` | `name` / `owner.name` / `plugins` が存在。`claude plugin validate` が使えるならそれも実行して成功 |

スキル/エージェントの RED: スキル無し（または「本文を返すな」契約無し）の子がコード引用を最終メッセージに載せることを 1 ケースで確認し、契約ありで載せないことを 1 ケースで確認する。実装フェーズで writing-skills に従う。フック eval が先。

`scripts/build-zip.sh` は zip 前に 3 本のフックへ `chmod +x` し、`plugin/` を zip し、次を `zipinfo` で確認して失敗なら非 0:

- アーカイブ先頭または一段下に `.claude-plugin/plugin.json`
- `hooks/check-file-size` / `hooks/check-bash-read` / `hooks/check-jq` の Unix 実行ビット（exec form と親 Bash からの spawn は実行ビット無しだと動かない）

marketplace 検証（成功条件 8）: `evals/run.sh` または同梱の検証ステップが `.claude-plugin/marketplace.json` を読み、`name`・`owner.name`（非空文字列）・`plugins`（配列）を必須とする。`claude plugin validate` が PATH にあれば marketplace ルートに対して実行し、非 0 なら失敗。JSON の構文だけ通して `owner` 欠落を許さない。

### 比較 eval（成功条件 9・10、§26.5 の A 群）

この節の委譲必須条件は A 群だけに適用する。B 群は §26.5 の独立 ID と経路表で判定する。共通の品質・隔離・ディスク検証は B 群でも使う。

フック eval は経路も有用性も見ない。同じ質問を直接処理と委譲処理で走らせ、transcript で経路を証明し、正確性と 2 系統のトークン指標を記録する。

起動コマンド（必須フラグ。欠けたら比較 eval は fail。公式 Headless / CLI reference）:

```
# 共通（両モード同一。plugin の有無以外を揃える）
COMMON='-p --output-format stream-json --verbose --include-hook-events --forward-subagent-text --model sonnet --permission-mode acceptEdits --allowedTools Read,Edit,Grep,Glob,Agent,Write,Bash --add-dir <fixtures-abs>'

# 直接: token-shunt をロードしない
claude --bare $COMMON "<prompt>"

# 委譲: token-shunt をロードする
claude --bare $COMMON --plugin-dir plugin/ "<prompt>"
```

- 直接と委譲で変えてよいのは **token-shunt のロード有無と、委譲プロンプトのスキル指示（§26 の worker モデル方針を含む）だけ**。親モデル、permission mode、allowedTools、cwd、fixture パス、stream フラグは同一。
- `--bare` は公式どおりフック・スキル・プラグイン・設定の自動発見をスキップする。ホストの marketplace に入った token-shunt と、cwd の `.claude/settings.json` / `.claude/settings.local.json` も読まない。委譲は `--plugin-dir` で明示ロードする（公式: `--bare` でも `--plugin-dir` は載る）。
- **OAuth 代替（`--bare` が `ANTHROPIC_API_KEY` を要求して使えないとき）。`CLAUDE_CONFIG_DIR` だけでは足りない。** 公式の設定スコープは User（`~/.claude/settings.json`、`CLAUDE_CONFIG_DIR` で移せる）と Project（`<cwd>/.claude/settings.json`、親ディレクトリへフォールバックしない）と Local（`<cwd>/.claude/settings.local.json`）が別である。OAuth は `~/.claude.json` 側にあり、`CLAUDE_CONFIG_DIR` を空ディレクトリに移すと認証まで落ちることがある。代替は次を全部満たす:
  1. 認証: 既定の OAuth（`~/.claude.json` を移さない）。`ANTHROPIC_API_KEY` があればそれを使って `--bare` に戻してよい。
  2. 設定ソース: `--setting-sources` を空（user / project / local をロードしない。SDK の `settingSources: []` に相当）。空を受け付けない CLI なら比較 eval は **fail**（`CLAUDE_CONFIG_DIR` だけに落とさない）。
  3. cwd: `.claude/` も `CLAUDE.md` も無い一時ディレクトリ。fixture は `--add-dir` で絶対パスを足す。リポジトリルートを cwd にしない。
  4. 検出: `system/init.plugins` に token-shunt が無いことだけでは他フックは分からない。`--include-hook-events` の `hook_started` / `hook_response` で、token-shunt の 3 本（`hooks/check-file-size` / `check-bash-read` / `check-jq`）以外の command hook が 1 件でもあればそのケースは fail。直接モードは PreToolUse の hook_response が 0 件。managed settings は公式に切れない（既知の限界。managed のフックが混ざったら fail）。
     - **実機で判明した制約（2026-09-13, CLI 2.1.270）:** この CLI の `hook_response` の `hook_name` は**マッチャ名だけ**（`PreToolUse:Read` / `PreToolUse:Bash` / `SessionStart:startup`）で、コマンドパスを含まない。上のコマンドパスによる識別はそのままでは実装できない。代替として**隔離契約で識別する**: (a) 直接モードは `--plugin-dir` を渡さないので、PreToolUse の `hook_response` が 1 件でもあれば fail。(b) 委譲モードは `--setting-sources ""`・クリーン cwd・`--plugin-dir plugin/` のみなので、登録され得る command hook は token-shunt の 3 本だけであり、`PreToolUse:Read` / `PreToolUse:Bash` / `SessionStart:startup` 以外の hook_event が出れば fail。(c) 出力が非空なのに `token-shunt` を含まない `hook_response` は、上記マッチャ上でも外来として fail（他プラグインの deny を捕まえる）。
     - deny の識別も `hook_name` ではなく `permissionDecisionReason` に `token-shunt` が含まれることで行う（§13 の `compare-hook-deny-route` の一次証拠）。
     - **残る穴（§15）:** 同じ `PreToolUse:Read` / `Bash` マッチャに載った**外来の通過フック**は出力が空なので、この CLI では token-shunt の通過と区別できない。コマンドパスが `hook_name` に載る CLI が出たら (b) をコマンドパス識別へ戻す。
- `system/init` の `plugins`: 直接モードに `token-shunt` がいたらそのケースは fail（隔離失敗）。委譲モードに `token-shunt` が無ければ fail（ロード失敗）。`plugin_errors` に token-shunt があれば委譲は fail。
- `stream-json` は `--verbose` と併用する（公式の stream 例）。
- `--include-hook-events` が PreToolUse の `hook_response` を stream に出す（SessionStart / Setup はフラグ無しでも出る）。フック deny の**一次証拠**。直接モードでは token-shunt の deny が無いこと。
- 子の `tool_use` / `tool_result` は verbose stream に `parent_tool_use_id` 付きで出る（公式 Headless「Follow subagent messages」。既定で tool ブロック、`--forward-subagent-text` で text/thinking も）。
- 古い CLI で子の tool_use が無いときだけ、SubagentStop の `agent_transcript_path`（ネストした `subagents/*.jsonl`）を読む。どちらも無ければそのケースの path_ok は fail（skip にしない）。
- `--bare` も `--setting-sources` 空＋空 cwd もできない古い CLI で直接モードから token-shunt と他フックを外せないなら、比較 eval は fail（skip にしない）。1 行 70KiB の直接 Read がフック deny される状態では「親 Read 成功」を検証できない。

パース対象は親の `tool_use`（Read / Edit / Grep / Agent / Bash）、対応する `tool_result`、`parent_tool_use_id` 付きの子メッセージ、`hook_response`、最終 `result.usage`、`result.modelUsage`（Python は `model_usage`）。編集ケースは実行前後の fixture バイト列も見る。

`TOKEN_SHUNT_HOOK_LOG` はフォールバックだけ。本番未設定。`hook_response` から deny JSON が取れるなら log ファイルは見ない。取れない古い CLI に限り、eval 実行中だけこの env をセットして 1 行 JSON を追記してよい（判定自体は変えない）。

#### 起動判定（skip と fail を分ける）

1. `command -v claude` が無い → **skip**（exit 0）。`last-run.json` に `skip_reason=claude_missing`。フック eval は通す。
2. `claude` がある → skip しない。次を順に実行し、どれかが非 0 なら比較 eval は **fail**:
   - ロードプローブ（委譲）: `--bare --plugin-dir plugin/`（または ZIP）で `system/init.plugins` に token-shunt があること。manifest 不正・フック未登録・起動エラー・`plugin_errors` は fail。
   - 隔離プローブ（直接）: `--bare`（または OAuth 代替の空 `--setting-sources`＋空 cwd）かつ `--plugin-dir` なしで `system/init.plugins` に token-shunt が**無い**こと。あったら fail。token-shunt 以外の PreToolUse hook_response があっても fail。
   - `claude plugin validate` が PATH にあれば marketplace ルートに対して実行。非 0 は fail。
   - 必須ケースを実行。
3. **リリース:** A 全必須ケース（bulk-reader / code-writer）と B 各指定モード 1 反復の経路・品質・隔離に合格すれば出荷可。費用は記録し回帰チェックに使うが、出荷可否の条件にしない（§1.1・§26.5）。Claude 未導入による実機 skip は出荷不可。

#### 必須ケース（減らさない）

| id | 質問 | fixture | gold | モード |
|---|---|---|---|---|
| compare-bulk-facts | `MAGIC_TOKEN` の値と、それを定義する関数名と行番号 | 400 行超かつ 64KiB 超。行 20 付近と行 380 付近に互いに参照する識別子 | 値・関数名・行番号 | 直接 + 委譲（委譲プロンプトにスキル指示あり） |
| compare-one-line | minify 1 行 70KiB からキー `payload_sha` の値 | 1 行 70KiB | その値 | 直接 + 委譲（スキル指示あり） |
| compare-hook-deny-route | 上と同じ `MAGIC_TOKEN` 質問 | compare-bulk-facts と同じ | 同じ 3 点 | **委譲のみ。** スキル名 / `token-shunt` / `Agent` は書かない。プロンプトは「First use the Read tool on \<path\> with no offset or limit. Then answer:」＋質問。事前委譲を許さない。フック deny を必ず発生させる |
| compare-explicit-multifile | User 作成後に何が起きるか。concern と job の名前を挙げよ | 最小 Rails: `user.rb` はコメントパディングで閾値超。`include Notifiable` と `after_create`。`notifiable.rb` は `WelcomeEmailJob.perform_later`。`welcome_email_job.rb` は小さい | `Notifiable`、`after_create`、`WelcomeEmailJob`。3 点とも `confirmed:` で、それぞれ該当パス付き | 直接 + 委譲（両方に user / concern / job の 3 パスを明示。関連探索はしない） |
| compare-code-writer-ok | 参照 `greeter.py` に合わせて `out/greeter_test.py` を書け。検証は `python -m unittest <target>` | `fixtures/codegen/greeter.py`（小さい。`greet("Ada") == "Hello, Ada!"`、空文字は `ValueError`）。target は空ディレクトリ `out/` | ディスク上の target が存在する。markdown fence で包まれていない。**親の Bash** が `python -m unittest <target>` を実行し成功。eval ランナーが同じ unittest を再実行して 1 件以上成功したあと、`greet` を壊して再実行し失敗する。Agent 最終メッセージはパス・行数・3〜5 bullet、生成本文なし、800 文字以下 | **委譲のみ**（スキル指示あり。`subagent_type=token-shunt:code-writer`。検証コマンドをプロンプトに含める） |
| compare-code-writer-no-ref | 存在しない参照パスで target を書け | 参照は `fixtures/codegen/missing_ref.py`（置かない）。target は `evals/compare/tmp/code-writer-should-not-exist.py` | target が作成も更新もされていない。Agent 最終メッセージに生成コードが無い。理由と参照パスがある | **委譲のみ**（スキル指示あり） |
| compare-edit-dense-lines | 短行密集ファイルで `EDIT_MARK` を `EDITED` に置換せよ。`KEEP_MARK` は変えるな | run.sh が `a\n` × 40000（約 80KiB・40000 行、両閾値のうち行は超過、バイトは `MIN_BYTES` 前後）を生成。中ほどに `EDIT_MARK=<unique>` と `KEEP_MARK=<unique2>` を別行で置く。マーク周辺 8192 バイトは約 4096 行 | ディスク上で `EDIT_MARK=EDITED`。`KEEP_MARK` は元値。対象以外が不変。原本 targeted Read 成功後の Edit を必須とする | **委譲のみ**（スキル指示あり。原本 targeted Read のみ） |

#### 経路契約（accuracy と独立。破れば fail）

**直接モード**

- token-shunt は未ロード（上の `system/init` 契約）。フック deny で Read が落ちたら path_ok fail（1 行 70KiB の `compare-one-line` を含む）。
- 親 transcript に fixture への `Read`（`tool_input.file_path` が対象）がある。Grep だけで正答しても fail。
- その Read に対応する `tool_result` が成功している（`is_error` ではない、本文が載っている）。パス間違い・権限エラー・サイズ制限エラー・token-shunt deny で落ちた Read は path_ok fail。
- 親が `Agent` で `token-shunt:bulk-reader` を呼んでいたら fail（モード取り違え）。
- `compare-explicit-multifile` の直接では、親が明示された 3 ファイルを Read し成功していること。

**bulk-reader の委譲モード（スキル指示あり）**

- 親の `Agent` `tool_use` の `subagent_type`（または同等フィールド）が完全一致で `token-shunt:bulk-reader`。Explore / 素の `bulk-reader` / 親の自己回答は fail。
- 親が起点ファイルの全文 Read に成功して本文が tool_result に載ったら fail。このモードはスキル指示で委譲するので、Read 未試行は可。試行した場合の失敗をフック deny の代わりにしない。
- **子→親テキスト:** Agent の `tool_result` 本文（親が受け取る子の最終メッセージ）が §12 の契約を満たす。4000 文字超、fixture 本文の 20 行超または 2KiB 超の連続引用があれば fail。親の最終回答が短くても、子が本文を返していれば fail。

**compare-hook-deny-route**

- user prompt に `bulk-reader` / `token-shunt` / `Agent` を含めない。スキル説明を読んで最初から委譲する経路は、このケースでは fail（正常動作だが、フック経路の証明にならない）。
- プロンプトは Read ツールで対象を先に読むことだけを明示する（offset/limit なし）。スキル名は出さない。
- 順序と証拠:
  1. 親の起点ファイルへの `Read` `tool_use`（offset/limit なし、path が fixture と一致）。
  2. その Read に対応する token-shunt フック決定が `hookSpecificOutput.permissionDecision === "deny"`。`permissionDecisionReason` は §9 の骨子を含む（`token-shunt` と `/token-shunt:bulk-reader`）。**一次証拠**は `--include-hook-events` の `hook_response`（stdout JSON）。フォールバックだけ `TOKEN_SHUNT_HOOK_LOG`。どちらも無ければ fail。
  3. その後 `subagent_type=token-shunt:bulk-reader`。
- 次はフック deny の証拠にしない: ENOENT、EACCES、パス間違い、ツール組み込みのサイズ制限、`is_error` だけの tool_result、他プラグインの deny。
- Grep だけで正答して Agent を呼ばない場合も fail。
- 子→親テキスト契約は委譲モードと同じ。

**compare-explicit-multifile の委譲**

- 親が **1 回**の Agent 起動に user / concern / job の 3 パスを明示する。
- その 1 起動の子が指定 3 ファイルをそれぞれ 1 回 Read し、すべて成功する（再試行があれば総起動 ≤ 4）。3 パスを 3 起動に分けたら fail。子の transcript で検証し、関連探索や再 Read は fail。
- 最終回答の gold 3 点は該当パスと `confirmed:` を持つ。推測だけの正答は fail。

**compare-code-writer-ok**

- 親の `Agent` `subagent_type` が完全一致で `token-shunt:code-writer`。
- 子の tool_use に参照 `greeter.py` への Read がある。Write の前に参照 Read が成功している。
- 実行後、target ファイルがディスクに存在し、markdown fence で包まれていない。
- **親の Bash** に `python -m unittest` と target パスがある。対応する `tool_result` が成功（exit 0、`Ran N tests` で `N ≥ 1`、FAIL/ERROR 無し）。親が検証せず要約だけで終了したら fail。
- **eval ランナー**（親コンテキストの外）が mutation を判定する。本文を親へ渡さない。
  1. 同じ `python -m unittest <target>` を再実行し成功すること（親検証の再現）。
  2. `greeter.py` の `greet` が `"Hello, Ada!"` 以外を返すよう一時的に差し替え、同じ unittest を再実行する。こちらは非 0 または FAIL が必須（`assert True` や空の `test_greet` を落とす）。終わったら fixture を戻す。
- fixture の固定動作: `greet("Ada")` は `"Hello, Ada!"`、`greet("")` は `ValueError`。
- Agent の `tool_result` 本文が §12 の契約（パス・行数・3〜5 bullet、生成本文なし、800 文字以下）。本文の 20 行超または 2KiB 超の連続引用があれば fail。
- 親が自分で Write したら fail。

**compare-code-writer-no-ref**

- 親の `Agent` `subagent_type` が完全一致で `token-shunt:code-writer`。
- 参照パスは存在しない。子は Write しない。実行後 target が存在しない（事前に置かない。作成されていたら fail）。
- Agent 最終メッセージに生成コード（fence または 20 行超の本文）が無い。理由と参照パスがある。

**編集ケース共通（ディスク検証。値を返すだけでは fail）**

eval ランナーが判定する。本文を親へ渡さない。

1. 実行前に fixture の SHA-256（または同等）を取る。
2. 実行後、対象マークだけが gold の新値になり、`KEEP_MARK` の行が実行前とバイト一致する。
3. 対象置換を実行前バイト列へ適用した**期待バイト列**と、実行後ファイルが一致する（対象以外が不変）。一致しなければ fail。
4. 親の `Agent` `subagent_type` が完全一致で `token-shunt:bulk-reader`。
5. 親の原本 targeted Read がフックを通り成功し、その tool_result に編集対象の原文があること。temp や Bash 閲覧、未読 Edit 例外を代替にしたら fail。
6. 親が原本の全文 Read に成功していたら fail。
7. 原本への親の Edit が成功していること。値を答えるだけでは fail。
8. accuracy はディスク上の期待バイト列一致で判定する。

**compare-edit-dense-lines**

- 子の `confirmed` の path を確認し、親が Grep でマーク位置を一意に確認する。子の `start_line` は合否条件にしない。
- 約 80KiB の原本のマーク付近を数行だけ targeted Read し、フック通過・成功・原文取得後に親が Edit する。
- 全文は行閾値を超えるが、指定範囲は両閾値以下かつ走査予算内。上のディスク検証に合格する。

#### 指標（混同しない）

親へ追加されたコンテンツ量と、API の累積使用量は別物。複数ステップでは同じコンテキストが usage に再計上される。公式の Agent `tool_result.totalTokens` と `usage` は**子の最終 API リクエスト分**であり、子の全実行合計ではない。合計に使わない。

| 指標 | 何を測るか | 取り方 |
|---|---|---|
| accuracy | gold が親の最終回答に含まれる | 最終 assistant テキスト |
| path_ok | 上の経路契約 | 親と子の tool_use / tool_result。フック経路は `hook_response`（無ければ `TOKEN_SHUNT_HOOK_LOG`） |
| parent_added_chars | そのターンで親トランスクリプトに**新たに載った**文字数（記録用） | 親に残る user / assistant / tool_result の Unicode 文字数を 1 回だけ足す。同一 message id は重複計上しない。子の中間 Read は親に載らない前提。載っていれば含める |
| parent_added_utf8_bytes | 上と**同じ対象**の UTF-8 バイト数（隔離判定用） | 同じ連結文字列を UTF-8 で測る。fixture 側は `st_size`（UTF-8 ファイル）または同じエンコードのバイト長。文字数とバイト数を混ぜない |
| isolation_ok | 代表的な大容量ケースで、委譲が親へ追加する量を直接より減らしたか | **両辺とも UTF-8 バイト。** 両モードがあるケース: 委譲の `parent_added_utf8_bytes` < 直接の `parent_added_utf8_bytes`、かつ委譲の `parent_added_utf8_bytes` < fixture の UTF-8 バイト数。委譲のみの大容量ケース（`compare-hook-deny-route`、`compare-edit-dense-lines`）: 委譲の `parent_added_utf8_bytes` < fixture の UTF-8 バイト数。`compare-code-writer-ok`: 生成ファイル本文が親 transcript に 20 行超または 2KiB 超で含まれない（プロンプトが生成ファイルより長いのでサイズ比較はしない） |
| parent_added_tokens | `parent_added_utf8_bytes` のトークン概算 | `bytes/4` でよい。usage の input 合計で代用しない |
| parent_input_tokens | 親の累積 input。記事との比較用で親子合計費用とは別 | usage_parent の uncached input / cache read / cache creation の合計と内訳を保存。取得不能なら null。§26.5 の必須測定では欠測を fail にする |
| parent_output_tokens | 親の累積 output | 最終 result.usage の output_tokens。取得不能なら null。§26.5 の必須測定では欠測を fail にする |
| usage_parent | 親ループの累積使用量（子を含まない） | 最終 `result.usage`。公式どおり subagent は入らない。assistant を足すなら message id で重複排除。`output_tokens` は per-step がプレースホルダなので result 側を使う |
| usage_tree | 親子合計の累積使用量 | 最終 `result.modelUsage`（モデル名キー）。無ければ `null` |
| cache_read / cache_creation | キャッシュ分 | usage または modelUsage の `cacheReadInputTokens` / `cacheCreationInputTokens`（または snake_case）。uncached input と分けて記録する。合計に cache_read をそのまま足して「親コンテキスト」としない |
| models | 実際に動いたモデル | 親: assistant の model。子: Agent 結果の `resolvedModel` と `modelsUsed`。エイリアス `sonnet` ではなく実 ID を優先。`effort` が取れれば記録 |
| wall_ms | 所要時間 | 質問から最終 result まで |

`last-run.json` にケースごと・モードごとに上を書く。取れない項目は `null` と理由（§26.5 の必須親トークン測定の欠測は出荷 fail）。この節では accuracy / path_ok / 対象ケースの isolation_ok を判定する。費用の null や USD 不合格は記録し §26.5 の回帰チェックに回す。出荷 fail にはしない。

Agent 結果の `totalTokens` は記録してよいが `usage_tree` の代用にしない（公式: 最終リクエストであり全実行合計ではない）。

#### 合格 / 不合格

- `accuracy` または `path_ok` が fail ならそのケースは失敗。
- 「分割して再質問せよ」だけ、gold を欠く要約、子本文の親への漏れは失敗。
- **isolation_ok（合格条件）:** `compare-bulk-facts`、`compare-one-line`、`compare-explicit-multifile`、`compare-hook-deny-route`、`compare-edit-dense-lines`、`compare-code-writer-ok`。上の定義を満たさなければそのケースは失敗。主目的（親コンテキスト削減）を任意にしない。`parent_added_chars` と fixture `st_size` を直接比較しない。編集ケースは isolation_ok に加えてディスク上の Edit 成功と対象以外の不変が必須。
- `usage_*` / `wall_ms` と §26.5 の親子合計推定費用を記録する。トークン総数だけでは費用を判定しない。auto の費用回帰は比較スイート合計で見る（出荷 fail にはしない）。
- 直接モードで `parent_added_utf8_bytes` が fixture サイズに近い逐次 targeted Read になっていても、直接側は fail にしない（観測対象。委譲側の isolation_ok とは独立）。
- 直接の `accuracy` が fail なら壊れた fixture として失敗。
- ロード失敗、直接モードへの token-shunt 混入はケース未実行でも fail（skip にしない）。

モデル方針は §26.5 の direct / haiku / sonnet / auto 比較で判定する。90% 減は assert しない。既存の強制委譲ケースは機構検証として残し、実際の小仕事ルーティングは別ケースで検証する。

## 14. README に必ず書くこと

- モデル選択と小仕事判定は SKILL.md の入力規約であり、フックによる強制ではない。eval は遵守を観測するもので、実運用の全呼び出しを防御する機構ではない
- フックが止めるのは 350 行 / 64KiB を超える読取。16KiB 超でも両フック閾値以下の中間帯（例: 200 行・20KiB）はスキル判断による委譲で、隔離はベストエフォート
- code-writer は生成済みと内容検証済みを分ける。minimal / syntax だけなら partial と確認事項を報告し、要件を確認した場合だけ完了にする
- 親の累積 input / output は §26.5 の必須観測結果を示す。本文バイトの削減をトークン節約と呼ばず、減少未確認ならその旨を表示する
- 4 パス以上の統合は §11 のバッチ間根拠契約に従い、確認できない関係を推測で補わない
- 親への出力境界は子の最終メッセージ契約。引用やコードフェンスが返れば親ノイズになる。code-writer も子の Write と短い返答に依存し、スクリプトによる fence 除去・出力加工はない
- 出荷物は「親への本文流入を抑える。費用削減は未証明」と表示する。費用をうたう文面は §26.5 の実測が direct より悪化していないときに限る。隔離合格と費用回帰を別の製品版にしない。manifest / 配布説明も同じにする

- jq 必須。`command -v jq`。欠落時は SessionStart が警告し、PreToolUse は全 Read/Bash を exit 2 で止める
- `shunt@portal` と同時に有効にしない（他プラグインの deny が子の Read を殺す）
- 親コンテキスト隔離と推定 API 費用の削減を目指す。auto は Haiku を第一候補にし必要時だけ Sonnet。削減率は比較結果で示し、定額料金の減額や請求額 90% 減を保証しない
- 既知の限界: `@ファイル`、Explore の最終メッセージ、Grep content、python/sed、未知の末尾コマンドのパイプ（fail-open）、`limit=350` 逐次 Read、PowerShell、code-writer 非強制、原本 targeted Read で取れない編集
- 導入: `claude --plugin-dir plugin/` または zip。marketplace add はリポジトリルート（`owner.name` 必須）。zip 内フックは実行ビット必須
- フックは通過時に `permissionDecision: "allow"` を出さない（権限確認を省略しない）
- doctor: フック stdin に `agent_type` が出ること、`FORCE` が立っていたら警告、jq の有無
- 環境変数 `TOKEN_SHUNT_MIN_LINES` / `TOKEN_SHUNT_MIN_BYTES` / `TOKEN_SHUNT_SCAN_BUDGET_BYTES` / `TOKEN_SHUNT_SCAN_BUDGET_MS`。`TOKEN_SHUNT_HOOK_LOG` は古い CLI の eval フォールバック
- 画像 / PDF / `.ipynb` の Read はサイズゲートしない
- 単一の巨大ファイルは親が行分割せず 1 ワーカーに渡す。均等行分割はしない
- 比較 eval（`evals/compare/`）は `--bare` + 共通フラグ。直接は `--plugin-dir` なし、委譲は `--plugin-dir plugin/`。OAuth 代替は空 `--setting-sources`＋`.claude` の無い一時 cwd＋`--add-dir`。`CLAUDE_CONFIG_DIR` だけでは足りない。経路・正確性・代表ケースの親コンテキスト削減（isolation_ok、UTF-8 バイト同士）が合格条件。親子合計の推定費用と再試行は §26.5 で記録し回帰する。code-writer は親が検証コマンドを実行し、eval ランナーが生成テスト＋ mutation に成功することがリリース必須
- Claude 未導入なら比較 eval は skip。ロード失敗と直接モードへの token-shunt 混入、token-shunt 以外のフック混入は fail。リリースには実機の比較 eval 成功が必須
- 編集はフックが通る原本 targeted Read が成功した場合のみ。head/tail は閲覧用。dd+temp・未読 Edit 例外を編集保証に使わない
- bulk-reader の subagent は 1 起動につき明示最大 3 パス・各領域 1 回 Read・maxTurns 6（§12）。関連探索と再利用は v0.1 対象外
- 記事の約 90% は親 Claude の input トークン削減であり、本プラグインの親子合計費用の削減率ではない。親 input、子 usage、親子合計推定 USD を別々に示す
- 効果が出やすいのは親が Sonnet / Opus のとき。親が Haiku なら isolation のみを期待する
- 両スキルの `--worker-model` 呼び出し例と、未知値は起動前エラーとなる入力規約（§26.1）

## 15. 既知の限界

- `@` 参照は Read ツールを通らないのでフック不能
- Explore / Plan / general-purpose の起動自体は止めない。それらの大きな Read は deny する。Grep や最終メッセージの引用は残る
- Grep `output_mode=content`、`sed`、`python -c`、PowerShell `Get-Content` は対象外
- **パイプの残穴:** 末尾が未知コマンドなら §10-4 は通過する（意図した fail-open。`cat large | grep` は通す。`cat large | cat` は deny）。封鎖しない。引用内の `|` と複合コマンドのリダイレクトはパイプ／リダイレクト通過にしない
- **逐次 targeted Read:** 成功条件 6 が実測 lines/bytes が両閾値以下の targeted Read を許すため、親は `limit=350` を offset ずらしで繰り返し全文を回収できる。1 行が `MIN_BYTES` 以下なら `limit=1` の繰り返しでも回収できる（巨大行の `limit=1` は §9.7 で deny）。フックは呼び出しをまたぐ回収を検出しない。比較 eval の直接モードでは観測し、委譲側では §26.5 に従い deny 後の連続 Read / パイプ回収を path_ok fail にする。isolation_ok の量的判定も別途適用する
- code-writer の Write フック強制はしない。完了は §11 の検証段階と受入条件の確認に依存する。最小・構文チェックだけなら生成済み・内容未検証と報告する。検証を省略した利用は製品手順違反であり、eval では fail
- 子の最終メッセージが契約を破れば、そのテキストは親に入る。キャップと eval で抑えるが script 境界（Spotify）ではない
- 複数 PreToolUse は deny が勝つ。Spotify shunt 併用で子が死ぬ
- `effort: low` は現行 docs 上 override。FORCE=1 でモデルが負ける
- 単一巨大ファイルを 1 子に渡すと、子コンテキストは肥大する。親隔離にはなるが、親子合計トークンは直接 Read より増えることがある
- `head`/`tail` の解釈不能指定は全文閾値に戻すため、大きいファイルへの `head -n +5` のように実際は小さい出力でも deny することがある（fail-closed）
- **Bash の二重防御:** フックの `MIN_BYTES` は 65536。Claude Code の Bash は valid 出力を既定で約 30,000 文字までしか inline しない（`bashOutputMaxChars` / `BASH_MAX_OUTPUT_LENGTH`。超えた分はファイルパス＋プレビュー）。30,000〜65,536 バイトの帯はフックが通し、CLI が既に切っている（無害）。`bash-head-c-70000` は「70,000 バイトが親に載る」の反例ではない
- PreToolUse command hook の timeout は fail-open（公式: timed-out command hook は tool call を block しない）。走査予算（8MiB / 2s）は timeout より短い目標であり、遅い FS で予算チェックより先に 10s へ達すれば巨大 Read が素通りする。開始行までの読み飛ばしも予算に含めるが、timeout 到達そのものは封鎖できない
- `Read(limit=1)` も区間バイト閾値に従う。1 行が `MIN_BYTES` 超なら deny。走査予算や公式 Read 上限でも失敗しうる。原本 targeted Read で取得できない巨大行・遠い末尾などの編集は v0.1 対象外。
- dd+temp の Read は原本の既読を保証しない。モデルごとの未読 Edit 例外も製品契約にしない。byte-span とこれらを用いた編集 eval は延期する。head/tail のフック検証は閲覧として残す。
- managed settings のフックは `--bare` でも `--setting-sources` でも切れない。混ざったら比較 eval は fail
- 比較 eval は Claude CLI が無いと skip される。その状態ではリリース不可
- Agent `tool_result.totalTokens` は子の全実行合計ではない（最終リクエスト分）。`result.usage` は親ループのみ。親子合計は `modelUsage`



## 16. 履歴への参照

旧 §17〜25 は [撤回済みレビュー履歴](history/2026-09-12-review-decisions.md) に移した。現行要件は本書の §1〜15 と §26。§27 は今回のレビュー判定記録。既存参照を壊さないため節番号は維持する。

## 26. 費用最適化（v0.1 は優先順位 1〜3、2026-09-12）

親コンテキスト隔離と費用最適化を別々に測る。費用最適化対象外だった旧方針は撤回済み（履歴は §16）。v0.1 の bulk-reader は指定ファイルの Read-only・maxTurns 6・1 起動あたり明示最大 3 パス。関連探索と再利用はリリース要件から外す。

### 26.0 採用経路と依存の決定

読取・生成とも Claude Code の named subagent を採用する。Claude Code の認証・権限・モデル解決・実行履歴を使い、追加サービスや専用キーを運用しないことを設計上の制約とする。外部 API を直接呼ぶ経路は利用予定がないため、実装・比較・費用回帰悪化時のフォールバックの対象にしない。

bulk-reader は 1 起動あたり明示最大 3 パス、Read のみ・maxTurns 6。複数ファイル横断は親が全パスを指定したとき同一起動にまとめる。4 パス以上は 3 パスずつ起動を分け、§26.3 の総起動上限内で親が短い回答を統合する。この選択は tools なし 1 完了より安いという主張ではない。記事とは実行境界と課金構造が異なるため、親隔離と親子合計推定費用を §26.5 で独立に測る。費用が悪化したら、この依存制約内で閾値・モデル方針・再試行を見直す。

### 26.1 優先 1: モデルを選択できるようにする

両スキルの SKILL.md 本文先頭に次の規約と例を固定する（実装時の必須文面）。これは親が解釈する入力規約であり、Claude CLI のフラグや Skill 引数機構による強制ではない。description と本文で誘導し、eval で遵守を検証する。

```text
Interpret --worker-model auto|haiku|sonnet before any Agent invocation.
Default: auto. Reject unknown values before starting a worker.
For delegated work, invoke Agent(subagent_type="token-shunt:bulk-reader"
or "token-shunt:code-writer", model="haiku"|"sonnet", prompt=...)
according to --worker-model. auto starts with haiku.
```

```text
/token-shunt:bulk-reader --worker-model auto /abs/a.rb /abs/b.rb --question "設定値と定義元を確認"
/token-shunt:bulk-reader --worker-model sonnet /abs/a.rb --question "設定値を確認"
/token-shunt:code-writer --worker-model haiku --reference /abs/greeter.py --target /abs/greeter_test.py --verify "python -m unittest /abs/greeter_test.py" --spec "参照に沿ったテストを生成"
```

- agent 定義の既定は `model: haiku` / `effort: low`。親は必ず Agent の model を明示する。要求モデルと実モデルを実機で照合し、利用不能・組織制約・FORCE による上書きは doctor で明示する。黙って別モデルにしない。
- `haiku` / `sonnet` 固定は委譲 1 起動につき 1 回（3 パスまで同一起動）。auto の Sonnet 再試行は必要な根拠の欠落、返答契約違反、または生成後検証失敗に限り 1 回。自信度だけで昇格しない。
- モデル昇格の再試行には元の質問・同じ指定パス・短い不足点を渡す。§11 のバッチ境界確認は別の確認起動であり、同じパス集合を使うこの昇格規則とは区別する。いずれも総起動上限に含める。Haiku 履歴は渡さないが、同じファイルを読む費用は再度かかる。両試行を計上する。
- 未指定の依存、Read のサイズ/コンテキスト上限、予算終了、認証・権限・参照不存在・未対応モデルでは昇格しない。不足を partial として返す。
- code-writer の再試行は target の現状を確認してから行う。他の編集が入った target は自動上書きしない。子は既存 target を Read し、生成後は親が再検証する。2 回目の失敗で停止する。

### 26.2 優先 2: 小さい仕事は親が直接処理する

- 明示小ファイル群または既知の必要区間の読み取り合計が **16384 バイト以下**で、各 Read が §9 を通るなら親が直接読む。3 ファイル以上でも委譲しない。判定はメタデータだけを使い、判定のために本文を親へ取り込まない。メタデータ取得は親の Bash で、basename が `cat` / `head` / `tail` / `less` / `more` でないコマンドに限る（例: `stat` の `st_size`、`wc -c`。§10-5 で通過）。行数の全数は取らない。`Read` / `cat` で本文を見てから小仕事判定しない。`st_size` 合計が 16384 以下で、各 targeted Read が §9 を通る見込みなら直接。
- 大ファイルでも必要な数行の位置が既知なら targeted Read を優先する。範囲不明で全文候補が小仕事予算を超える、または Read が deny された場合は bulk-reader。全文の小窓回収はしない。
- 定型生成は予想出力 **50 行未満**かつ参照合計 **16384 バイト以下**で各 Read が通るなら親が生成・検証する。それ以外は code-writer。出力量の見積もりだけのために子を起動しない。
- 編集・デバッグ・設計判断は親の責務。小仕事閾値はスキルの固定値で、フックの 350 行 / 65536 バイトとは別。損益分岐点が実証済みとは扱わない。
- §13 の機構強制ケース A は小仕事判定の例外。製品 auto の B では例外にしない。

### 26.3 優先 3: 作業量を制限する

- bulk-reader は **Read のみ、maxTurns 6**。1 起動につき明示最大 3 パスの各領域を 1 回 Read し、次に回答する。関連探索・重複再 Read・resume は禁止。Read 呼び出し数は起動あたり最大 6（分割時のみ 3 超、§12）、指定外パス 0。4 パス以上は 3 パスずつ起動を分け、§11 のバッチ間根拠契約に従う。境界確認（質問あたり最大 1 回）も総起動上限に含め、各要約の統合と全起動費用を親側に計上する。maxTurns は CLI の上限、Read 回数と対象パスは指示と transcript eval の契約であり、現在のサイズフックによる強制ではない。
- これは認証・権限統合を優先する採用方式であり、厳密な one-shot ではない。記事の 30 秒上限も named subagent の maxTurns では保証できない。時間は wall_ms として測り、30 秒を保証と宣伝しない。厳密な 1 完了・30 秒上限は製品要件にしない。
- Read 失敗・省略・ターン終了で回答契約を満たせない場合は partial。親は自動 resume せず、ファイルを分割して再 Read するループも作らない。
- code-writer は生成用の別契約で `maxTurns: 12` を維持する。内容確認は最大 16 ファイル、Read / Grep / Glob 合計 20 回を指示上の上限とし、transcript 超過は fail。読み取り worker の one-shot 方針を生成の Write 手順と混同しない。
- 同一ユーザー質問の Agent 起動は両 worker・バッチ・境界確認・再試行を合算して **最大 4 回**。上限後は部分結果と未完了範囲を伝える。別 agent 名や resume で迂回しない。
- 最終回答に `status: complete|partial` と `stop_reason` を既存の文字数上限内で含める。強制終了で回答が無い場合も partial。code-writer の生成済みと親による検証済みを分ける。

1 起動 1 ファイルは作業量を予測しやすいが、横断質問で親が N 個の要約を縫う。それは §1.1 の目的（親ノイズ削減）を削るので採らない。3 パスを 1 起動にまとめるのは Claude Code の必然ではなく、親へ入る最終メッセージを 4000 字 × 起動数に増やさないための v0.1 の選択である。子の system / ツールスキーマは起動ごとに乗る。中規模ファイル群でも isolation_ok は起動あたりの本文キャップで見る。未測定のまま 1 ファイルずつの方が安いとは扱わない。

### 26.4 優先 4: 再利用は v0.2 以降へ延期

v0.1 には回答索引・fingerprint・ハッシュ依存・再利用 hit/miss 判定を実装しない。再利用・失効 eval と再利用専用費用ゲートもリリース必須から外す。追質問は同じ明示パスを新規 worker に再送する。親への本文隔離は保てるが、子の再入力費用は無料ではない。

将来再導入する場合は、索引の具体的な保存場所・1 行 JSON の形式・回答を複製しない参照方法・autocompact 時の挙動・変更検知を別途設計する。複数ファイル横断での有効性と索引トークン・fingerprint I/O を含む費用を先に測り、完全一致質問だけの再利用を記事の横断読取の削減実績と同一視しない。

### 26.5 比較検証とリリース条件

`cases.json` に `suite`、`routing`、`worker_model`、`expected_agent_calls`、`required_paths`、`expected_resolved_model` を持たせる。A と B は別 ID・別結果として保存し、同じ fixture でも経路判定を共有しない。以下が固定スイート定義である。

| 群 | ケース ID | 実行条件 | path_ok / 合格条件 |
|---|---|---|---|
| A 機構強制 | compare-bulk-facts / compare-one-line / compare-explicit-multifile | direct とスキルで強制委譲（haiku / sonnet / auto） | §13 の直接 Read 成功、修飾 subagent_type 完全一致、指定ファイル Read 各 1 回。multifile は 3 パスを **1 起動**。本文隔離。小仕事でも委譲必須 |
| A 機構強制 | compare-hook-deny-route | auto、最初の全文 Read を強制 | hook deny → bulk-reader。§13 の順序証拠 |
| A 機構強制 | compare-code-writer-ok / compare-code-writer-no-ref | auto、スキルで委譲を強制 | code-writer 完全一致、生成・親の検証・mutation / 参照不存在時の非 Write |
| A 機構強制 | compare-edit-dense-lines | auto、要約を委譲する機構テスト | bulk-reader → 親 Grep → 原本 targeted Read 成功 → Edit 成功、期待バイト列一致 |
| A 契約 | worker-model-invalid | 両スキルへ `--worker-model invalid` | 明示エラー、Agent 0、生成 target 変更 0 |
| A 契約 | writer-verification-levels | auto、参照付き YAML / Markdown / JSON の生成。親の検証・報告を実機確認 | 最小チェック成功は minimal、JSON parse 成功だけなら syntax、いずれも内容未検証・partial。必須キー/値を検査する受入条件の成功時だけ requirements。ランナーは構文が正しい必須キー欠落例、同程度の行数の途中欠落例、末尾が正当なコードブロックの Markdown を制御入力にし、誤完了・誤拒否を検出する |
| A 契約 | reader-batch-evidence | auto、明示 4 パスを 3 + 1 で委譲、各ファイルは 1 回で読める fixture | 一意な参照識別子が揃う正答ケースは根拠付き統合。同名シンボルがあり要約だけでは識別不能な制御ケースは、境界確認で曖昧さを解消するか unconfirmed / partial。根拠なし confirmed は fail。総起動 ≤ 4、本文キャップ、各起動内の Read 契約を維持 |
| A 契約 | reader-bounds / retry-policy / writer-bounds | 制御入力と実機 transcript | 指定外依存は partial・探索 0、Read は指定パスの各領域 1 回（重複禁止、起動あたり最大 6）、maxTurns 6。許可理由だけ Sonnet 再試行 1 回。writer 上限、総起動 ≤ 4、resume 0 |
| B 製品 auto | auto-bulk-facts / auto-one-line / auto-explicit-multifile | direct / haiku / sonnet / auto。A と同じ大容量 fixture、強制委譲指示なし | ロード側は bulk-reader。明示ファイルだけで正答、本文隔離。multifile は 3 パス 1 起動。direct は親 Read 成功 |
| B 製品 auto | auto-small-files / auto-known-range / auto-small-writer | 同じ 4 モード、各 1 反復。3 小ファイル合計 ≤16KiB / 既知の数行 / 50 行未満 | 全モード Agent 0、親の Read または生成・検証成功。委譲必須条件は適用しない |
| B 製品 auto | auto-large-writer | 同じ 4 モード、50 行以上を要する固定 spec | direct は親生成・検証。ロード側は code-writer、親の検証と mutation 成功 |
| B 編集経路 | auto-edit-grep-location | 4 モード各 1 回、誤った行番号ヒント＋類似メソッド | 親 Grep → 原本 targeted Read → Edit、対象以外不変。Agent 0 |
| B 境界 | auto-routing-boundaries | 16KiB の直前・一致・直後、49 / 50 行、既知区間への Read deny | §26.2 に一致。deny 後の分析は委譲、編集保証は原本 Read 成功時のみ |

**deny 後の迂回回収も path_ok で検出する。** A の deny-route と B の大容量委譲ケースでは、deny 後の親による offset をずらした連続 Read、引用外パイプ経由の本文回収を fail にする。解析課題では denied path への親の成功 Read を認めず、編集・既知区間ケースだけ cases.json に許可した対象範囲を指定する。親の tool_use / tool_result を照合し、許可範囲外の成功 Read、または対象本文の回収を目的とするパイプ呼び出しを検出する。判定不能は pass にしない。制御 transcript に limit=350 の連続 Read と cat のパイプ回収を入れ、ランナーが fail にすることを検証する。これは eval の回帰検出であり、フックによる封鎖範囲は広げない。

**出荷条件:** A 全必須ケースに加え、B の全ケースを各指定モードで 1 反復し、経路・gold・生成検証・対象ケースの isolation_ok を満たす。境界ケースも全入力を実行する。下記の親トークン測定も必須。費用は観測できれば記録する。費用の欠測・USD 不合格だけでは出荷を止めない。48 実行は PR2 のマージ条件にはしない。後続 eval で品質・経路・隔離の失敗が判明した場合は、費用のみの失敗と区別し修正まで出荷を止める。

**親トークン測定（PR2 の必須観測）:** B の大容量読取 3 件と大規模生成 1 件について、既存の direct / auto 各 1 反復から `parent_input_tokens`（uncached / cache read / cache creation の内訳付き）と `parent_output_tokens` を取得し、ケースごとの両値と差、input + output 合計の差を記録する。再試行・親の検証と修正を含める。欠測やバイト数からの推計で代用した結果は fail。削減の有無は実測結果として明示し、増加時は原因と手段の改訂候補を記録する。削減率や USD 合格を新たな出荷ゲートにはしない。1 反復の観測を安定した削減効果と宣伝しない。README では本文隔離と累積親トークンの結果を区別し、減少未確認なら「トークン節約は未確認」とする。48 実行の費用比較は引き続き PR3 であり、親子合計トークン・費用とこの親測定を混同しない。

**B の path_ok は機械判定して fail で停止する。** 要求 model と全 worker の resolvedModel を事前に固定した対応表で照合する。欠測・不一致・無許可再試行は fail。小仕事の Agent は厳密に 0。ゴールド正答や安い費用で経路違反を相殺しない。ランナーは非ゼロ終了し ZIP リリースを止める。モデル強制環境で成立しない場合も skip で合格にしない。

プロンプトでモデル選択が安定しない場合は、リリース前に Haiku frontmatter 固定・呼び出し時 override を拒否する Agent フックへ改訂する。Sonnet 再試行を維持するなら専用経路と allowlist を別途設計する。小仕事で不要委譲が残る場合は、検証済みメタデータを用いる Agent 起動前ゲートを追加する（Read の第 2 閾値だけでは Agent 0 を強制できない）。未対応 CLI で黙って弱めず、方針を改訂して A / B を再実行する。これらは観測された失敗に対する改訂条件であり、現在強制済みとは書かない。

B に `auto-edit-grep-location` を必須経路テストとして追加する（4 モード各 1 回、費用集計外）。大ファイルに類似メソッド名と同名のコメントを置き、親に誤った行番号をヒントとして与える。親は限定した Grep で実メソッドを識別し、原本 targeted Read 後に Edit する。Grep → Read → Edit の順序、正しい offset、対象以外のバイト不変を path_ok / accuracy にする。誤った子の位置ヒントを模した制御入力であることを記録する。取得位置を子に尋ねる委譲は不要で Agent 0。Grep が曖昧な制御ケースは非 Edit を期待し、実メソッド識別の正答ケースとは分ける。

旧 `compare-rails-follow`（起点から concern → job を探索）、`compare-edit-byte-window`、`compare-edit-long-line` は v0.1 の必須スイートから削除する。dense-lines は targeted Read 成功ケースのみ。再利用 eval は B に含めない。

- A は機構・契約のリリースゲート。B の経路・品質・隔離も出荷ゲート。48 実行の費用比較は内部回帰であり出荷条件ではない。A の auto は全必須ケース合格が必要。固定モデルの品質失敗は記録し、成功と偽らない。予算 partial は制御テストの期待結果であり、正答課題の成功には数えない。
- B の費用回帰スイートは大容量読取 3 件と大規模生成 1 件の計 4 件（4 モード × 3 反復 = 48 実行）。小仕事 3 件は各モード 1 反復の必須経路テスト（12 実行）とし費用集計から除く。各モードで各 **3 回**、順序交替、新しい会話、同じ親モデル（既定 Sonnet）・権限・fixture 初期状態で測る。親 Haiku / Opus の結果は別表にし、Sonnet と混ぜて一般化しない。B の固定 haiku / sonnet も小仕事の直接方針は共通で、委譲時のモデルだけ固定する。
- §13 の隔離した CLI 条件を使用する。各試行は同じ cwd パスに独立 fixture を復元し、生成物と mutation を持ち越さない。要求・実モデル、方針バージョン、キャッシュ条件を記録する。
- **親 input と費用を分離:** `parent_input_tokens`（親の uncached input / cache read / cache creation の内訳付き累積）、`usage_tree`、`estimated_api_cost_usd` を別々に保存する。parent_added_utf8_bytes は本文隔離指標であり、記事の input トークンや費用ではない。親だけの削減率を親子合計 USD の削減率と呼ばない。
- 推定 USD は親子全モデルの uncached input / cache read / cache creation / output に、それぞれの単価を掛けて合計する。単価の公式出典 URL・取得日・価格適用日・プロバイダーを保存する。usage や料金区分が不足なら null と理由を記録し、費用合格にしない。定額契約の実請求額とは呼ばない。
- ルーティング、全子呼び出し、再試行、親の検証・修正を課題単位で合算する。modelUsage に含まれる子を二重加算しない。失敗試行も除外しない。worker_attempts / fallback_reason / stop_reason / wall_ms を保存する。未キャッシュとキャッシュありを混ぜた平均だけで評価しない。
- **費用回帰（出荷条件ではない）:** B の 4 件を 4 モード × 3 反復 = 48 実行し、費用中央値の総和が direct と sonnet 固定の両方より小さいかを記録する。個別ケースの増加も表に残す。悪化したら手段（モデル方針・小仕事閾値・起動のまとめ方）を改訂して測り直す。記事の約 90% とは独立した内部チェックであり、製品ラベルや出荷区分にはしない。

**ゲート失敗時:** 経路・品質・隔離の失敗または必須親トークン測定の欠測は修正まで出荷を止める。費用だけが不合格または未取得なら、費用削減をうたわない出荷物は出荷可。外部 API 経路への切り替えは行わない。小仕事も 3 反復する従来の 84 実行は任意の拡張観測とし、必須 48 実行の費用集計と混ぜない。A・境界・編集ケースはこの実行数に別途加わる。

Claude CLI 不在では実機 eval を skip できるが、リリースは不可。現時点では設計のみで、モデル適性・削減率は未検証。

### 26.6 実装 PR と出荷順序

| PR | 実装単位 | マージ時の検証 / 出荷条件 |
|---|---|---|
| 1 | Read / Bash / jq フック、namespace、marketplace と ZIP 構造検証 | 全フック eval と配布構造検証。ZIP は開発用のみ |
| 2 | 2 スキル、2 named subagent の契約、A と B 経路判定の機械化 | A 全通、B 各 1 反復の経路・品質・隔離、および必須親トークン測定。この ZIP を出荷可（費用未証明。費用削減をうたわない） |
| 3 | 費用集計と 48 実行、README の実測結果 | 費用は回帰記録。悪化したら手段を改訂。合格しても別製品版は作らない。費用不合格・未取得のまま費用削減をうたわない |

PR 1 から順に進める。経路選定用の API プロトタイプや先行比較は不要。PR 3 未完了・実機 skip・費用未取得のまま費用削減をうたわない。


## 27. 2026-09-13 レビューの偽陽性チェック

前回レビューの番号に対応する。設計書の静的照合であり、実機検証済みという意味ではない。

| 指摘 | 判定 | 根拠と対応 |
|---|---|---|
| 1. 生成物の最小チェックと完了 | 真陽性 | §11 は内容の正しさを保証しないと書きながら exit 0 を完了条件にしていた。検証段階と課題完了を分離し、途中打ち切り検出の過大な保証を削除。§3・§5・§13〜15 も整合させた |
| 2. 1 ファイル 1 Read | 偽陽性として撤回 | §11・§12・§26.1・§26.3 は Read / コンテキスト上限と省略時の partial を明記済み。全巨大ファイルの読了保証は無い。追加 Read を必須にするのは仕様修正でなく対応範囲拡張なので行わない。モデル適性・対応範囲は引き続き実機未検証 |
| 3. トークン節約の未確認出荷 | 一部真陽性 | 費用ゲート不要・欠測時に費用削減をうたわない方針は明示済みで、これ自体は欠陥でない。一方、今回の目的に対して親の累積トークンを測らなくてもよい点は不足。既存 B の direct / auto から必須観測を追加し、削減保証や USD 出荷ゲートは追加しない |
| 4. 3 パス分割 | 一部真陽性 | 固定 3 パス自体が品質を落とすという断定は撤回。根拠が揃えば親の統合は可能。不足はバッチ間の根拠と曖昧時の扱いであり、上限を維持して §11・§26.3 と境界 eval を補足 |
| 5. Bash パイプ・複合判定 | 真陽性 | 行数指定ではバイト数を判定できず、複合の全対象判定と先頭だけの判定が矛盾。stdin の head/tail は明示バイト上限でのみ通過、複合は全区間の明示対象を先に判定する規約と回帰ケースを追加。汎用シェル解析や未知コマンドの封鎖は追加しない |
