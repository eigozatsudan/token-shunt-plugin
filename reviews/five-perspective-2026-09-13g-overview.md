# 俯瞰レビュー

## 範囲と方法

現行ワーキングツリーを、目的・制約・手段・ドキュメント・フック・スキル・エージェント・評価・配布が一つの製品として閉じているか、という俯瞰だけで見た。パーサ微細バグは対象外。費用削減の未証明はリリースゲートではない（設計 §1.1・§26.5、README 先頭）。

読んだもの: `README.md`、設計書 `docs/2026-09-12-token-shunt-design.md` の §1〜15 と §26、`docs/distribution/README.md`、`plugin/**`、`evals/**`（オフライン判定器と `cases.json`）、`scripts/**`、`.claude-plugin/marketplace.json`、`plugin/.claude-plugin/plugin.json`。`reviews/` と `docs/history/` と git 履歴は読んでいない。§27 は根拠に使っていない。

フック起動形は `plugin/hooks/hooks.json` の `command` + `args` と、現行 Claude Code Hooks リファレンス（https://code.claude.com/docs/en/hooks の Exec form / shell form、公式プラグイン例、PreToolUse タイムアウト）を突き合わせた。`bash -c "$command"` 前提は置いていない。ZIP はアーカイブ内容と `plugin/` のバイト一致、フック 3 本の Unix 実行ビットを確認した。`evals/compare/run.sh`（実機 Claude API）と実モデル呼び出しは実行していない。

## 確認した不具合

### P3: 配布READMEが費用比較をリリース確認項目に並べ、出荷ゲート階層と食い違う

- 場所
  - `docs/distribution/README.md:77`
  - 対比: 設計 §1.1（費用は内部回帰、出荷区分にしない）、§26.5（費用の欠測・USD 不合格だけでは出荷を止めない）、§26.6 PR2（費用未証明のまま出荷可）
  - 実装側の出荷判定: `evals/compare/judge.py:1835-1836`（`release_eligible` は失敗ゼロかつ必須ケース全実行。費用合格は条件に入らない）
  - ルート README は区別している: `README.md:5-6`（料金削減は未確認）、`README.md:204`（本文バイトと親トークン内訳・推定費用を分ける）
- 再現
  - 配布 README の「配布前の確認」は、ZIP/診断成功だけではリリース不可としたうえで、「スイートA・B、本文の分離、必須の親トークン計測**と費用比較**を確認します」と列挙する。
  - 設計の出荷条件は経路・gold・隔離・必須親トークン計測であり、費用比較は記録対象の内部回帰である。
  - 判定器も費用不合格を `release_eligible` に入れない。
- 影響
  - 配布担当が「費用比較が終わるまで ZIP を出さない」と読むと、§26.6 の PR2 出荷区分（費用未証明・費用をうたわない）と衝突する。ルート README と配布 README でゲートの読みが割れる。
- 修正方向
  - 配布 README を §26.5 に合わせ、「費用比較は記録し手段改訂に使う。欠測や USD 不合格だけでは出荷を止めない。費用削減をうたう文面は実測後に限る」と書く。A/B・隔離・必須親トークンは現状どおり必須のまま残す。
- 確信度
  - 高（文面と §26.5 / `release_eligible` の条件が直接食い違う。ランタイム欠陥ではない）

### P3: 設計正本の Python 検証コマンドが、出荷スキル・README・比較evalと不一致

- 場所
  - 設計 §11（`docs/2026-09-12-token-shunt-design.md:395-396`）: `.py` は `python -m py_compile <target>`、テストは `python -m unittest <target>`
  - 設計 §13 `compare-code-writer-ok`（同ファイル `:587`、`:630-632`）と §26.1 呼び出し例（`:779`）: `python -m unittest /abs/greeter_test.py`
  - 出荷スキル `plugin/skills/code-writer/SKILL.md:17` と `:49-51`: `python3 -m py_compile`、テストは `python3 -m unittest discover -s <dir> -p <filename>`。絶対パスをモジュール名にしない、と本文で理由を書いている
  - `README.md:79` と同じ discover 例
  - `evals/compare/cases.json:187,193` と `evals/compare/run.sh:229` 以降の writer 検証も `python3` + `discover`
- 再現
  - 設計例どおり `python -m unittest /abs/greeter_test.py` を親 Bash に書くと、多くの環境で `python` が無い、または絶対パスが unittest のモジュール名として解決できない。
  - 出荷スキル・README・比較ケースは `python3 -m unittest discover -s … -p greeter_test.py` で揃っている。
- 影響
  - 出荷物どうし（スキル / README / eval）は一貫している。正本だけが古い契約を残す。設計に合わせて実装した第三者や、設計例をそのまま親検証に使うと、生成は成功しても検証段階が落ち、`verification_incomplete` / 再委譲に入りうる。
  - これは「実装が仕様の検証手段を満たせない」ではなく、「正本のコマンド例が出荷契約に追従していない」。
- 修正方向
  - 設計 §11・§13・§26.1 の例を、出荷スキルの `python3` + `discover`（および py_compile / tomllib も `python3`）に合わせる。逆方向（スキルを `python -m unittest <target>` に戻す）は、スキル本文が既に否定している失敗モードを再導入するので採らない。
- 確信度
  - 高（三箇所のコマンド文字列が一致しない。フックやエージェントの実行時バグではない）

## 不具合としない観察

- 目的と手段の階層は製品として閉じている。フックはサイズゲート（通過時は `permissionDecision` なし、deny 時だけ JSON）、スキルが委譲・小仕事・モデル選択、named subagent が bounded I/O、親が編集と検証、eval が経路・隔離・必須親トークンを機械判定する。allowlist は `token-shunt:bulk-reader`（Read+Bash）と `token-shunt:code-writer`（Read のみ）で、エージェント frontmatter の tools と一致する。フックが Agent を自動起動しないことは README が明示し、設計 §5 の「deny → 親がスキルを開く」と一致する。
- `plugin/hooks/hooks.json` は `command` に `${CLAUDE_PLUGIN_ROOT}/hooks/…`、`args: []`、`timeout` 秒。現行公式は `args` があるとき exec form（シェル無しで `command` を直接 spawn）とし、プラグイン公式例も同じ形（`command: "${CLAUDE_PLUGIN_ROOT}/scripts/format.sh", args: []`）である。3 本とも `#!/usr/bin/env bash` と実行ビットがある。ZIP 内も `plugin/` とバイト一致し、フック 3 本は `mode=0o755`。起動失敗は再現していない。PreToolUse の command hook タイムアウトは公式どおり fail-open で、設計 §7・§15 と README の既知限界に書いてある。
- `claude --plugin-dir ./token-shunt.zip` は公式プラグイン文書がサポートし、ZIP 配置（アーカイブ直下の `.claude-plugin/plugin.json`）も満たす。配布 README は展開後ディレクトリだけを書いており案内は狭いが、展開パスも公式に正しく、成功条件 8 の実装欠落ではない。
- bulk-reader の「全文拒否に加え、成功 Read が EOF 前で黙って止まる場合の連続・非重複継続」は README・スキル・エージェント・`evals/compare/routing_checks.py` が揃っている。設計 §12 本文はトークン上限拒否時の分割に寄っている。出荷契約の内部分裂ではなく、正本の追従遅れ。
- `retry-policy` と `writer-bounds` は `cases.json` に `child_no_body` / `child_msg_max` が無く、判定器はフラグがあるときだけ子→親本文契約を見る。他の bulk-reader / code-writer 必須ケースはキャップを付けている。スキル・エージェント側の 4000/800 字契約自体は欠けていない。
- doctor の `agent_type` 確認は stdin dump ではなく手順案内（`scripts/doctor.sh:233-247`）。README も別途実入力確認と書いてあり、設計 §7 の「1 回 dump」より弱いが、未確認を成功と偽ってはいない。
- マニフェスト（`plugin.json` / marketplace）は 90% も費用削減もうたわない。費用未証明の断りは README 側。marketplace の “route to subagents” は設計 §7 の文面そのもので、自動 spawn 主張としては README が打ち消している。
- 比較 eval が `--bare` ではなく `--setting-sources ""` + 空 cwd なのは、設計 §13 の OAuth 代替そのもの。`run.sh:3-5` が 2.1.x で `--bare` を使わない理由を書いている。
- トークン・料金削減が未確認であることは欠陥ではない。`release_eligible` が費用合格を要求しないのは §26.5 どおり。

## 検証

- フック 3 本を `plugin/` と `token-shunt.zip` で照合。ZIP 15 エントリ、内容差ゼロ、`check-file-size` / `check-bash-read` / `check-jq` は実行ビット付き。
- `hooks.json` の exec form（`args: []`）を公式 Hooks リファレンスの「args があれば exec form」「プラグインは `${CLAUDE_PLUGIN_ROOT}/…` + `args: []`」例と照合。shell form（`args` 省略 → `sh -c`）ではない。
- 公式: PreToolUse の command/http/mcp_tool が timeout すると tool call は block しない。設計 §7・§15 の既知限界と一致。
- 公式: サブエージェント内 PreToolUse のトップレベルに `agent_type` が載る。フックは `.agent_type` のみを見、`tool_input.agent_type` は使わない。
- `cases.json` の A/B ID は §13 必須ケースと §26.5 表（`auto-routing-boundaries` の入力分割を含む）をカバーする。`judge.py` の `mandatory` は catalog の全 `(id, mode)`。
- オフラインの `evals/run.sh` と実機 `evals/compare/run.sh` は本レビューでは回していない（後者は禁止、前者は `build-zip.sh` がツリーの ZIP を置き換えるため）。
