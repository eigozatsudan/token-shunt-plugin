# 別ハーネス指摘の独立検証

対象は現行ワーキングツリー（未コミット変更を含む、HEAD `b66c13f`）。実装・既存テスト・配布ZIPは変更せず、人工入力によるPoCとZIP再ビルドは一時コピーで実施した。全スイートや実機モデル呼び出しは今回再実行していない。提示された226テストのベースラインは現行との差があり、このレビューの正当性の根拠には使わない。

検証資料: `/tmp/codex-security-scans/token-shunt/b66c13f_20260914T014516Z_external-review`。`rubric.md`、実行可能な `validate.py` / `minor_checks.py`、候補別の検証票・JSONログを保存した。

## 結論

先頭cdの追跡喪失は未修正のP1として成立する。設計書の古い全文定義と配布ZIPのキャッシュ混入も事実。一方、括弧付きコマンドの保証範囲、skip_reason、テストカバレッジ、denyとReadの結合が不可能という説明には訂正が必要。

## P1: 先頭cdの追跡喪失

根本制御: `plugin/hooks/check-bash-read:698`、`:738`、`:741`。`TRACK_CD=0` のとき、`CD_UNCERTAIN` を立てる処理より先にreturnする。後続readerの相対パスを元cwdで調べ、存在しなければ対象ファイル集合が空となって通過する。

人工的な `sub/f`（82,000 bytes）、元cwdに `f` がない状態で実フックのstdinにBashコマンドを与え、同じcwdの実Bashと比較した。

| コマンド | フック | 実Bashのstdout bytes | 評価 |
|---|---:|---:|---|
| `cd sub && cat f || true` | pass | 82,000 | 保証するcd追跡喪失後の拒否に反する |
| `cd sub || exit; cat f` | pass | 82,000 | 同上 |
| `cd sub && cat f & echo hi` | pass | 82,003 | 同上 |
| `(cd sub && cat f)` | pass | 82,000 | 再現するが、§14のグループ化対象外という留保あり |
| `< /dev/null cd sub; cat f` | deny | 82,000 | 元報告の却下判断は正しい |
| `cd sub && cat f` | deny | 82,000 | 通常の追跡は機能する |
| `cat sub/f` | deny | 82,000 | 通常のサイズ判定は機能する |

ここで示した影響は、Bashを使える親に大容量本文が返る隔離契約違反。人工本文を用いたフック単体CLI＋Bashの比較であり、第三者への送信やClaude Code全体での実行を実測したものではない。ファイルは実行ユーザーが読めること、親が当該Bash構文を選ぶことが前提。P1という製品上の修正優先度は妥当だが、外部攻撃者による認証突破・機密流出まで拡張してはいけない。

修正案の検証として、一時コピーで `CD_UNCERTAIN` 判定を早期returnより前へ移すだけの変更を試した。先頭3形はdenyになったが、括弧付き形はpassのまま。グループ化を保証に含めるなら追加対処が要る。ただし設計書 `:716` はグループ化を明示的に対象外とするため、この4形を同一の保証違反として一括計上すべきではない。

カバレッジの説明も補正が必要。`test_cd_hooks.py` には `cd ... | cat; cat same.txt` があり、パイプによる `TRACK_CD=0` は通る。「TRACK_CD=0経路を全く試していない」は不正確。欠落しているのは、元cwdでは対象がなく、移動先にだけ大容量ファイルがある上記構文との組合せ。

## P2: 設計書の不整合

`docs/2026-09-12-token-shunt-design.md` の指摘は成立する。

- `:169` 以降のhooks.json全文は3登録、実ファイルは7登録。実際には5スクリプト・PreToolUse 4登録。
- `:162` のplugin descriptionはjqだけを要求するが、実manifestはjqとPython 3を要求する。
- `:214` の「3本ともbashシェバン」、`:253` の「PreToolUseの2本」、`:522` のビルド前「3本」も古い。reader契約フックはPython。
- §6の構成一覧は現行フック・doctor・比較評価器・テスト群を網羅していない。構成図の省略自体より、「全文」とされた必須登録が欠ける点が実害につながる。
- §13の `--bare` を使うコマンド例とAPIキーがあれば戻してよいという説明は、現runnerの `NOT --bare` 方針と矛盾する。今回CLI仕様を外部資料で再調査したのではなく、同じリポジトリ内の方針不一致を確認した。

後段の新しい追記だけでは前段を写経する読者を保護できない。必須マニフェスト例を実ファイルと一致させることが優先。

## P2相当の配布品質問題: ZIPのpyc混入

現行 `token-shunt.zip` に `hooks/__pycache__/check-reader-contractcpython-314.pyc` がある。一時コピーの `scripts/build-zip.sh:15` のzip経路と `:22` 以降のPython fallbackの両方が同じpycを含めて正常終了した。`:39` 以降のverifierはこの余剰ファイルを拒否しない。

ルート `.gitignore` は存在しない。`evals/test_reader_contract.py:13` のSourceFileLoaderと、`evals/run.sh:206` 以降の `-B` なし起動はキャッシュ生成経路になる。ZIP内pycのヘッダーは現在のreaderソースのmtime・サイズと一致しなかった。

ただし、現登録は拡張子なしPythonスクリプトを直接起動する。混入pycの自動実行や任意コード実行は確認していない。不要・古いビルド生成物が配布される問題として扱う。ビルド両経路での除外と、その除外を検証するテストを優先し、gitignoreやテストの `-B` だけを対策にしない。

## 軽微な指摘の判定

| 指摘 | 判定・補足 |
|---|---|
| reader必須フィールド未文書化 | 真。設計書に `agent_id` はない。実フックでsession_id / agent_id / tool_use_id / hook_event_nameを個別に欠くとexit 2を確認。ただしagent_type自体がないとexit 0で対象外になる。現在のCLIが必須フィールドを欠くとは今回示していない。PostToolUseの位置メタデータが欠ける場合は、安全な継続を許さずstoppedになる処理。doctorもagent_typeの手動確認案内が中心。 |
| catalogのdenyがbulk-reader理由を要求 | 真。実際のCD_UNCERTAIN denyを `check_expect deny` に渡すとfail。非ルーティングdenyを同じexpectへ追加すると偽失敗になる潜在的なハーネス欠陥。 |
| check-agent-modelのjqエラー時pass | 真。`{"tool_input":123}` でexit 0・stdout空。ただしstderrにjqエラーが出るので完全なsilentではない。CLIが通常供給するtool_inputはobjectであり、不正形状を外部攻撃者が到達させる経路は未確認。P3の入力検証一貫性の問題。 |
| last-run.json.exampleのスキーマずれ | 一部真。claude_code_versionは現runner/集計に出力経路なし、通常集計のsuite_cost_usdはexampleにない。ただしskip_reasonは `run.sh:28` が実際に出力する。またsuite_cost_usdはスキップ・起動失敗には常時出ない。通常集計とスキップの別例にするのが正確。 |
| 拒否Readが3パス枠を消費 | 再現。絶対パスを3つ、offset=2で拒否させると4つ目はパス上限で拒否される。拒否試行も予算を消費する保守的挙動であり、本文漏洩の欠陥ではない。すべての拒否が枠を使うわけではなく、非絶対パス等はsetdefault前に拒否される。 |
| deny_routeがReadとdenyを結合しない | 真。対象ReadのFile not found結果と、別件のdenyイベント、後続Agentを並べた最小トランスクリプトでも現judgeは全体passになった。ただし最小specでの反例であり、全実ケースの合格を示したものではない。理由にpathがないだけで改善が構造的に不可能とは言えない。Read IDに対応する失敗tool_resultや既存hookログのtool_use_idを証拠に使う余地がある。 |
| worker-model-invalidが事前拒否とhook拒否を区別しない | 真だが既存の意図的な評価。実行されなかった起動をagent_zeroから除外する専用テスト3件も合格。モデル自身の遵守と、フックが防いだ結果は別の測定として扱うべき。 |
| reader状態破損で同一session/agentが停止 | 再現。壊れたJSONを残すと同一IDへの2回の呼出しが連続exit 2。自動復旧はないが、同一状態ファイルが残る間の停止であり全セッションの恒久故障ではない。予算を黙ってリセットしないfail-closedの選択。 |
| big-scan.txtのnot committedコメント | 真。`evals/fixtures/big-scan.txt` はgit管理対象、`evals/run.sh:40` のコメントは不一致。 |
| readerの8MiB上限とSCAN_BUDGET_BYTESが非連動 | 真。`:59` は定数で、環境変数を読まない。ただし別フックの上限との非連動だけでは安全境界を破る証拠にならない。設定の適用範囲の文書化課題。 |
| SEPS内のpipe分岐がdead code | 真。scannerは `|` / `|&` をPIPESへ入れるため、`:741` のSEPSループ内の該当枝は到達しない。今回のP1原因を直す代わりにはならない。 |

## 検証と次の作業

関連する既存テスト29件（cd・Bash既知指摘・reader契約・ZIP）と、拒否済みモデル起動テスト3件が全て合格。それとは別に新しいPoCで上記欠陥を確認した。テスト合格はP1への反証にならない。

優先順位は、先頭3形のcd追跡喪失を直すこと、ZIP両ビルド経路からキャッシュを除外すること、必須マニフェストとランナー手順の文書を揃えること。その後にcatalogのdeny種別、形状不正時のモデルフック、reader互換性確認と例示スキーマを整える。今回の依頼は精査なので、修正・実機再測定・ZIP更新は行っていない。
