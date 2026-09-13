# 運用レビュー

## 範囲と方法

運用目線で、現行作業ツリー（HEAD `cb1ab7c94952df128aa9d171217177390b4a151e`）をそのまま読んだ。対象は marketplace / plugin マニフェスト、`hooks.json` と 3 本のフック、`scripts/build-zip.sh`、`scripts/doctor.sh`、`docs/distribution/README.md`、`evals/run.sh`、`evals/compare/run.sh`、ルート README の導入・デスクトップ・doctor・環境変数、および設計仕様 §1–15・§26。`reviews/` と `docs/history/` は読んでいない。git log / blame / コミット文は根拠に使っていない。設計書 §27 は所見リストとして使っていない。

検証は読み取りと、作業ツリーを汚さない実験に限った。`claude plugin validate .` と `claude plugin validate ./plugin` は実行した（どちらも警告付き成功）。既存 `token-shunt.zip` は `zipinfo` と内容ハッシュの比較のみ。`scripts/build-zip.sh` は `/tmp` コピー上でのみ実行し、元の ZIP は未変更（SHA-256 一致を確認）。jq 欠落・不正 JSON・空白を含むプラグインパスからの exec 起動は `/tmp` 展開コピーで再現した。ライブの `claude -p` は実行していない。

## 確認した不具合

### P2: doctor の agent_type 確認手順は stdin を保存しない

- 場所
  - `scripts/doctor.sh:235-243`（案内コマンド）
  - `plugin/hooks/check-file-size:42-45` および `plugin/hooks/check-bash-read:41-44`（`TOKEN_SHUNT_HOOK_LOG` の実体）
  - `README.md:210`（HOOK_LOG は判定ログのみ、と正しく注記）
- 再現
  1. `scripts/doctor.sh` を実行する。末尾の hook stdin 節が次を例示する。
     `TOKEN_SHUNT_HOOK_LOG=/tmp/ts-hooks.jsonl claude --plugin-dir plugin/ -p "use /token-shunt:bulk-reader on a large file"`
  2. 案内どおりログを開く。各行は `{hook, decision, reason}` だけである。
  3. トップレベル `agent_type` は無い。stdin JSON も無い。
  4. 括弧書きの `cat > /tmp/hook-stdin.json` は例示コマンドに含まれておらず、hooks.json を一時改変しないと取れない。
- 影響
  本プラグインの worker 免除はハーネスが PreToolUse stdin のトップレベルに `agent_type` を載せることに依存する（`check-file-size:131-134`、`check-bash-read:145`）。無い環境では `token-shunt:bulk-reader` / `code-writer` もサイズゲートされ、大きな Read がすべて deny になる。doctor は設計 §7・README がこの確認の場だと書いておきながら、案内どおりでは確認できない。HOOK_LOG に `agent_type` が無いことを「未対応 CLI」と誤読するか、確認したつもりで出荷する。
- 修正方向
  例示を stdin ダンプに変える。デバッグ用の一時フック、または `jq -r '.agent_type // empty'` で入力 JSON を保存する手順を出し、`TOKEN_SHUNT_HOOK_LOG` を agent_type 確認に使わない。README の「HOOK_LOG は判定ログだけ」と矛盾しない文言にする。
- 確信度
  高。コード上 HOOK_LOG に stdin が乗らないことは実装から確認できる。ライブセッションは未実行。

### P2: ユーザースコープ導入後、doctor はキャッシュ上の実体を見ない

- 場所
  - `scripts/doctor.sh:46-48` および `99-100`（`--plugin-dir "$ROOT/plugin"`）
  - `scripts/doctor.sh:237`（手動確認も `--plugin-dir plugin/`）
  - `plugin/.claude-plugin/plugin.json:4`（`"version": "0.1.0"`）
  - `README.md:25-32` および `docs/distribution/README.md:55-64`（marketplace add + install、キャッシュコピー）
- 再現
  1. README どおりリポジトリルートで `claude plugin marketplace add .` と `claude plugin install token-shunt@token-shunt --scope user` を行う。Claude Code は `plugin/` を `~/.claude/plugins/cache` へコピーする（公式 marketplace 仕様。相対パス source は copy であり link ではない）。
  2. `scripts/doctor.sh` を同じリポジトリで実行する。プラグインロードもモデルプローブも `--plugin-dir "$ROOT/plugin"` 固定である。公式どおり `--plugin-dir` はインストール済みプラグインより優先する。
  3. ソースの `plugin/` を直したあと、version を変えずに `claude` を通常起動する。公式の version 管理では `plugin.json` の version がピンになり、同じ `0.1.0` のままではキャッシュは更新対象にならない。
  4. doctor はソース側のエージェント登録を「confirmed」と記録しうる（`doctor.sh:209-228`）。通常起動は古いキャッシュを使う。
- 影響
  継続利用の正規経路（ユーザースコープ）で動くのはキャッシュであり、ソースツリーではない。doctor は「インストール・モデル解決の診断」と案内されているのに、導入済みコピーの欠落・古いフック・実行ビット落ちを検出しない。README は「登録元は更新用に残す」と書くが、`claude plugin marketplace update` / `claude plugin update token-shunt@token-shunt` も version バンプも書いていない。明日出荷して運用者がソースを直しても、現場の `claude` には届かない。
- 修正方向
  doctor に「`--plugin-dir` なし（導入済みキャッシュ）」と「`--plugin-dir plugin/`（ソース）」を分けて出す。導入済みを確認できないときは unconfirmed と明示する。README の導入節に、キャッシュが正本であること、更新は version バンプ + marketplace/plugin update（または再インストール）、`--plugin-dir` はセッション中そのディレクトリを消さないこと、を手順として書く。
- 確信度
  高。`--plugin-dir` 固定と version ピンはリポジトリ上の事実。キャッシュコピーと version ピンの更新条件は現行 Claude Code 公式ドキュメント（plugin-marketplaces / plugins-reference）に一致する。ライブの install/update は未実行。

### P3: 比較 eval の一部プロンプトがソースツリーの判定スクリプトをモデルに渡す

- 場所
  - `evals/compare/cases.json:302`（`python3 {JUDGE_DIR}/flow_checks.py` を親 Bash 検証として複数回指示）
  - `evals/compare/run.sh:227-229`（`--allowedTools` に `Write` を含む）
  - `evals/compare/run.sh:499-503`（`{JUDGE_DIR}` をソースの `evals/compare` に置換）
- 再現
  1. `writer-verification-levels` を含む比較 eval を実行する。
  2. 親プロンプトに作業コピーではなく `evals/compare/flow_checks.py` の絶対パスが埋め込まれる。
  3. 同じ CLI 呼び出しは `Write` を許可している。
- 影響
  fixture 本体は `RUN_ROOT/work` に隔離されている（`run.sh:31-68`、`test_runner.py:32-50`）。一方、判定器そのものはソースツリー上のパスとしてモデルに見える。誤った Write / 上書きで `flow_checks.py` を壊すと、以降の判定と作業ツリーが汚染される。出荷成果物（ZIP）は直接壊れないが、リリース判定ランナーとしては隔離契約の穴である。
- 修正方向
  `flow_checks.py` を `TMP` へコピーし、プロンプトと `disk_check` の両方をそのコピーだけに向ける。ソースの `evals/compare` を `--add-dir` しない。
- 確信度
  中。パス置換と Write 許可はコード上確認できる。モデルが実際に上書きした実例は、本レビューではライブ実行していない。

## 不具合としない観察

- `plugin/hooks/hooks.json` は `"args": []` 付きの exec form である。現行 Hooks リファレンスでは `args` があるときシェルを通さず、`${CLAUDE_PLUGIN_ROOT}` は command / args に文字列として置換される。公式例も `"command": "${CLAUDE_PLUGIN_ROOT}/scripts/format.sh", "args": []` である。空白を含むプラグインパスでスクリプトを argv0 として直接 spawn できることを `/tmp` で確認した。`bash -c "$command"` 前提の「空白でフックが起動しない」は、現行コードと公式仕様には当たらない。
- 3 本のフックは `#!/usr/bin/env bash` とソース上の実行ビットを持つ。既存 ZIP はアーカイブ直下に `.claude-plugin/plugin.json` があり、3 フックは `mode=0o755`。`unzip` 後も実行ビットが残る。ZIP 内容は `plugin/` とバイト一致。`claude plugin validate` は marketplace / plugin とも author 警告のみで成功する。marketplace.json は `name` / `owner.name` / `plugins[].source`（`./plugin`）を満たす。
- jq 欠落時、Read/Bash フックは stdout に決定 JSON を出さず stderr に `token-shunt: jq is required`、exit 2。現行仕様では PreToolUse の exit 2 はツール呼び出しを block する。SessionStart の `check-jq` は jq を呼ばず、欠落時は `additionalContext` を exit 0 で出す。設計どおり fail-closed / SessionStart 非 block。
- 比較 eval は `--bare` ではなく `--setting-sources ""` + 空 cwd + `--add-dir` である。run.sh 先頭コメントと README が CLI 2.1.x の理由を書いており、設計 §13 の OAuth 代替そのもの。直接モードは `--plugin-dir` なし、委譲は `plugin/`。作業コピーは `evals/compare/tmp/runs/run.*`（`.gitignore` 済み）。`last-run.json` も ignore され、`selected_run_valid` と `release_eligible` は集計で分離されている。`claude` 欠落は skip（exit 0、`skip_reason`）。ロード失敗・直接モードへの混入は probe で fail。ソース fixture はコピー元であり、モード間リセットは work 側 `gen_fixtures` が担う。
- `evals/run.sh` の zip-exec-bits が `scripts/build-zip.sh` を呼び、追跡中の `token-shunt.zip` を作り直すのは設計 §13 の検証ステップである。本レビューでは元ツリーでは実行していない。
- doctor の hard fail が jq 欠落だけなのはスクリプト先頭と README の明示仕様である。プラグイン未確認・モデル不一致は unconfirmed / 出力上の `MODEL MISMATCH` であり、exit 0 を全項目確認と読まない注記がある。設計 §12 の FORCE 警告も実装されている。
- デスクトップ未検証、Chat/Cowork 非対象、費用削減未証明は README / 設計の既知の限界であり、運用欠陥に数えない。
- `agent_type` を `tool_input` から読まないこと、通過時に `permissionDecision: "allow"` を出さないことは実装と eval の spoof ケースで担保されている。環境変数 4 種の不正値はフック側で既定に戻す。

## 検証

- `claude plugin validate .` および `./plugin`: 成功（author 警告のみ）。
- `zipinfo` / Python: ZIP 内 3 フックが Unix 実行ビット付き。`plugin/` と内容ハッシュ一致。
- `/tmp` へ unzip: 実行ビット保持。不正 JSON は exit 2。PATH から jq を外すと Read/Bash が exit 2、`check-jq` は警告 JSON を exit 0 で返す。
- 空白を含むディレクトリへ plugin をコピーし、exec form 相当（絶対パスを argv0）で `check-file-size` を起動: worker allowlist 入力で exit 0。
- `/tmp` コピーで `scripts/build-zip.sh`: 検証成功。元の `token-shunt.zip` の SHA-256 は不変。
- ライブ `claude -p`、marketplace install、キャッシュ実体の中身比較は未実行。
