# token-shunt 運用観点の独立レビュー

実施日: 2026-09-13。現行の README、docs/distribution、plugin、scripts、evals を対象にした。既存 reviews/、docs/history/、git 履歴、他者の /tmp レビューは参照していない。リポジトリ実装は編集せず、一時コピーで検証した。Claude の課金を伴う実機呼び出しは実施していない。

候補は以下の2件。重要度はいずれも P2（条件付きで評価結果を誤認させる運用不具合）。

## 1. 本文ありのケース実行で非0終了が失われ、selected_run_valid が true になる

- 重要度: **P2**。確度: 高。
- 箇所: `evals/compare/run.sh:524–536`。特に525行の `if (( rc != 0 )) && [[ ! -s $transcript ]]; then`。
- 問題: ケースのCLI終了コードを判定するのはトランスクリプトが空の場合のみ。出力が存在すると、プロセス終了コードは判定器に渡されず、内容側の判定のみで pass にできる。実行終了時エラーや、最終結果を出した後のハングがタイムアウトで打ち切られた場合でも、実行自体の失敗を結果に残せない。
- 再現手順:
  1. `evals/compare/test_runner.py` の既存 `RunnerIsolationTests` を一時ディレクトリで初期化する。
  2. 同テストにある `run_with_cli_double()` のローカル代替CLIだけを変更し、事前プローブは従来通り exit 0、実ケースは成功時と同じトランスクリプトを出したあと exit 17 とする。runner/judge/cases は現行コードのコピーのまま。
  3. `auto-small-files` を実行し、シェル終了コードと `last-run.json` を確認する。
- 観測結果: direct/haiku/sonnet/auto の全4ケースが exit 17 なのにランナーは **exit 0**、`done: pass=7 fail=0 runs=4`、集計は `fail_runs=0`、`selected_run_valid:true`。限定実行のため `release_eligible:false` であり、リリース全体の誤合格までは主張しない。
- 意図された制限との差: 533行のコメントは、非0終了でもAPIエラー等を含むストリームを判定して理由を得る意図を示す。ストリームを解析しつつ実行失敗を保持することは可能であり、非0終了の痕跡そのものを捨てて正常実行として集計する必要はない。同ファイルの事前プローブでは非0終了を環境失敗として扱う。
- 修正方向: 本文を判定する処理は維持した上で、ケースの非0終了を `checks.run=false` 等に統合し verdict を失敗に固定する。終了コードを保存する。
- 再現コード: `/tmp/token-shunt-operations-probes.py` の `nonzero_case_run` と `run_with_cli_double` 部分。
- 保存証跡: `/tmp/token-shunt-operations-797zoru4/nonzero-case-evidence/last-run.json` と、その下の `tmp/runs/run.*/`。

## 2. フック評価のケースJSONが不正でも、そのスイートを省略して成功終了する

- 重要度: **P2**。確度: 高。
- 箇所: `evals/run.sh:69–77` および `evals/run.sh:81–92`。特に77行と92行の `done < <(jq ...)`。
- 問題: ケース列挙の `jq` がプロセス置換内で実行され、その終了コードが確認されない。不正JSON、欠落ファイルなどで列挙に失敗するとループが0件のまま終わり、残りの特殊チェックだけを数えて成功する。評価ケースの編集ミスをCIの終了コードで検出できない。
- 再現手順:
  1. plugin/、scripts/、.claude-plugin/、evals/ を一時ディレクトリにコピーする。
  2. `PATH=/usr/bin:/bin bash <copy>/evals/run.sh` を実行する。この環境ではclaudeがPATH上になく、課金を伴うCLI呼び出しはない。
  3. コピーの `evals/hook-evals.json` と `evals/bash-hook-evals.json` を双方とも `{ definitely invalid JSON` に置き換え、同じコマンドを実行する。
- 観測結果: 正常時は **exit 0 / pass: 110 fail: 0**。不正化後はstderrに2件の `jq: parse error: Invalid numeric literal at line 1, column 13` が出る一方、**exit 0 / pass: 14 fail: 0**。96ケースが脱落しても失敗数に反映されない。
- 意図された制限との差: README が許容しているのはCLIがない場合の plugin validate の省略であり、フックケースJSONを読めない場合の省略ではない。今回の特殊チェックや回帰チェックは継続するが、列挙失敗をテスト成功として扱う理由にはならない。
- 修正方向: 両JSONをループ開始前に構文・配列構造検証し、列挙失敗を親シェルへ伝播する。必要なら期待するケース数・0件禁止も検証する。
- 再現コード: `/tmp/token-shunt-operations-probes.py` の offline-suite 部分。
- 保存証跡: `/tmp/token-shunt-operations-797zoru4/baseline.stdout`、`baseline.stderr`、`malformed.stdout`、`malformed.stderr`。

## 確認済みで候補から除外した点

- 空白入りプラグイン配置パス: hooks.json は3つとも `args: []` を持つ。最新版公式仕様ではこれはシェルを介さない exec form で、`${CLAUDE_PLUGIN_ROOT}` は1つの実行ファイルパスに置換される。シェル文字列として評価する再現は実際の設定を再現していないため棄却した。空白入りパスで同じexec形式をオフライン実行し、SessionStart exit 0、Read/Bash の両方が exit 0 と deny JSON を返すことを確認した。[Claude Code公式 Hooks reference / Exec form and shell form](https://code.claude.com/docs/en/hooks#exec-form-and-shell-form)（2026-09-13確認）。
- doctor のライブ確認失敗で exit 0 となる点: READMEとスクリプトは、jq不足のみハード失敗で、ライブ確認できない項目をunconfirmedとすることを明記している。意図された制限として不具合扱いしない。
- ZIPビルドとオフライン基本検証: 一時コピーで `evals/run.sh` が正常時 pass 110 / fail 0 を確認。ビルド・実行権限検証もこの実行に含む。

全再現は `python3 /tmp/token-shunt-operations-probes.py` で再実行できる。リポジトリは読み取りのみで、一時コピーと代替CLIを使用する。
