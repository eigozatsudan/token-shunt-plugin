# クリーンコンテキスト・俯瞰レビュー

対象: /home/dev/projects/skills/token-shunt の現作業ツリー（未コミット修正を含む）。README、現行設計の機能・評価・出荷条件、plugin 全体、配布スクリプト、比較評価の集計・契約を確認。reviews/、docs/history/、過去実行ログは読んでいない。適用される AGENTS.md はリポジトリ内と祖先ディレクトリに見つからなかった。外部API・認証済みモデル・実機CLIの呼び出しなし。既存ファイルは変更していない。

## 確認した不具合

### P2: 空白を含む配置先では登録済みフックが起動できない

- 根拠: plugin/hooks/hooks.json:8,21,32 の command が `${CLAUDE_PLUGIN_ROOT}/hooks/...` で、実行パスを引用していない。
- 発生条件: ソースまたはZIPを空白のあるパス（例 `/tmp/token shunt overview X/plugin`）に置き、`--plugin-dir` で読み込む。docs/distribution/README.md:35 は任意の空ディレクトリへの展開を案内しており、配置先の制限はない。
- オフライン再現: plugin/ を tempfile の空白入りパスへコピーし、hooks.json に登録された command を `CLAUDE_PLUGIN_ROOT` を指定した `bash -c` で実行、入力は `{}`。SessionStart・Read・Bash の3件とも exit 127、`bash: line 1: /tmp/token: No such file or directory`。同一配置で command を `"${CLAUDE_PLUGIN_ROOT}/hooks/check-file-size"` にした対照は exit 0、stdout/stderr 空。これはシェル起動層の問題で、スクリプト内のファイル名処理に到達しない。
- 影響: jqの起動時案内も2つのサイズ判定も動かない。Claudeがフックの一般エラーをどう提示・扱うかは実機未確認なので、必ずReadが通過する/必ずブロックされるとは断定しない。どちらの場合も配布されたプラグインの主機能を利用できない。
- 修正方向: 3つの command の実行パス全体を JSON 内で二重引用する（例 `"command": "\"${CLAUDE_PLUGIN_ROOT}/hooks/check-file-size\""`）。現在のテストはフックスクリプトを直接起動するため、空白を含む展開先で hooks.json 経由の起動を検証する回帰を追加し、ZIPを再生成する。
- 確信度: 高（シェルによる実行失敗と引用後の成功を対照再現）。Claude内部の実行方式をライブ検証したものではない。

## 俯瞰評価

目的→手段→評価の整合は概ね取れている。親コンテキストへの本文持ち込み削減を主目的とし、hook は deny とスキル案内だけ、実際の委譲と返答上限はモデル指示であることを README が区別している。metadata による16KiB経路決定、Read/Bash の350行・64KiB機械的ゲート、named worker の免除、最大4起動、親による生成物検証と partial の扱いは、役割の異なる制約として説明されている。未証明の費用削減を製品効果として主張していない。

リポジトリルートの marketplace と ZIP 中の plugin root の違いを配布READMEが説明しており、ZIPと現在のplugin/全ファイルのバイト比較は一致した。ZIPが古いという仮説は反証された。

比較評価は selected_run_valid と release_eligible を区別し、必要ケース集合との一致と親トークンの必須内訳を確認している。費用欠測/費用悪化を出荷不合格にしないのは現行設計 §26.5/§26.6 で明示した方針であり、集計のバグとは数えていない。48実行の費用回帰測定は後段の計画として区別すべきで、現状に費用改善の実証はない。

## 不具合とは確定しなかった観察

- code-writer/SKILL.md:73 は「親は生成コードを決して見ない」と書く一方、85-98 は受入確認・修正の targeted Read を明示的に許す。局所例外から意図は理解できるため、実害を再現していない文章上の曖昧さとして扱う。「本文全体を親へ戻さず、必要範囲の targeted Read のみ許す」への整理は有益。
- skill の本文返却上限が機械強制ではない、Grep/sed/python 等が hook 対象外、複数呼び出しの合算予算なし、巨大単一行で Read 上限に達すると partial、agent_type の実機入力依存、doctor がライブ未確認を hard failure にしない点は、README/設計で意図的制限または未確認と説明済み。欠陥数に加えていない。
- code-writer の構文確認だけで complete になる仮説は、SKILL が syntax/minimal を partial と明示するため反証された。
- 1ケースだけ合格して release_eligible になる仮説は、judge.py:1496-1502,1605 の mandatory set 照合で反証された。

## 検証

- `/tmp/token-shunt-review-tests-u66qerjc` に plugin/evals/scripts/marketplace をコピーして比較評価のオフライン unittest を実行: 89 tests、9.345秒、OK。元ツリーのテスト生成物を変更せず、PYTHONDONTWRITEBYTECODE=1。
- ZIP内容比較: plugin/ の全ファイルと一致。
- 上記フック配置パス対照テスト: 3件失敗、引用した対照1件成功。
- evals/run.sh は fixture/ZIPを書き換え、存在するCLIを呼ぶ分岐もあるため、そのまま実行していない。実機のモデル経路/費用/agent_type を今回新たに証明したとは主張しない。

## 統合後の偽陽性確認・訂正（最終判定）

**上記P2候補を撤回する。確認済み不具合は0件。** 初回の再現は `args: []` を無視して `bash -c` で実行したため、現行設定の起動方式を取り違えていた。

公式 Hooks reference の Exec form and shell form（https://code.claude.com/docs/en/hooks#exec-form-and-shell-form）は args 指定ありを shell を使わない exec form と定義する。現行 hooks.json の3件すべてに `args: []` が存在する。公式仕様に沿って CLAUDE_PLUGIN_ROOT を展開し、`subprocess.run([executable, *args], shell=False)` で再検証した。

配置先 `/tmp/token shunt exec control y_pt8ia7/plugin`、入力 `{}` で check-jq/check-file-size/check-bash-read の全3件が exit 0、stdout/stderr 空。したがって空白パスの起動失敗は再現しない。初回に提案した command へのシェル引用符追加も採用しない。exec form では引用符を文字として実行パスへ含めるおそれがある。

旧CLIで args が無視されるとの主張には、対象バージョンの対応範囲および実装仕様の根拠が必要である。今回はその証拠を得ていないため、互換性問題へ付け替えて報告することもしない。
