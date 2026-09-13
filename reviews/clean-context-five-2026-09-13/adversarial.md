# token-shunt 敵対的品質レビュー

対象は現行 README.md、plugin/hooks、plugin/skills、plugin/agents、evals の一次資料。既存 reviews/、docs/history/、git履歴は参照せず、実装は編集していない。これはセキュリティ監査ではなく、境界条件と契約の品質レビューである。

## 結論

この観点で確定した実装バグは **0件**。Bashの未対応構文による通過を実再現したが、親レビュー担当が確認した現行設計§10-5/6の限定パーサ仕様と整合するため、確定バグには数えない。READMEの説明から対応範囲を理解する際の注意点として以下を残す。

## 観測1：前置リダイレクトと接着した入力リダイレクトは検査されない

- 分類・重要度：**情報／対応範囲の文書明確化候補**。実装バグと断定しない。
- 箇所：`plugin/hooks/check-bash-read:304-308`（先頭の変数代入だけを剥離）、`:320-327`（引数そのものに対する通常ファイル判定）、`:656-663`（先頭トークンをコマンド名とし、未知名は通過）。
- 再現スクリプト：`/tmp/token-shunt-adversarial-repro.py`。作業ディレクトリ：`/tmp/shunt-adversarial-qgu17h4c`。本文は820バイト×100行、合計82,000バイトの `large.txt`。フックと `bash --noprofile --norc -c` を独立に実行し、本文は表示せず出力バイト数だけ計測した。

| コマンド | フック | Bash終了値 | 実際のstdout |
|---|---|---:|---:|
| `cat large.txt 2>errors.txt` | deny | 0 | 82,000 bytes |
| `2>errors.txt cat large.txt` | pass（空出力、終了0） | 0 | 82,000 bytes |
| `2>/dev/null head -c 82000 large.txt` | pass | 0 | 82,000 bytes |
| `2>/dev/null cat large.txt \| cat` | pass | 0 | 82,000 bytes |
| `cat <large.txt` | pass | 0 | 82,000 bytes |
| `cat < large.txt` | deny | 0 | 82,000 bytes |

- 影響：同じ内容を出すシェルコマンドでも、リダイレクトの位置や空白によりフックが発火しない。利用者がREADMEの「単独のcat」「明示的な入力ファイル」を広く解釈すると、検査されると期待する可能性がある。
- 対象外との照合：READMEはシェル全体を解釈しないと明記している。さらに親レビュー担当から共有された現行設計§10-5は `VAR=val` のみを除いた先頭トークンが対象名でない場合のpassを、§10-6は引数として存在する通常ファイルの検査を規定する。上の挙動はこの限定仕様に従うため、未対応構文として分類する。実装の拡張を必須修正とは扱わない。READMEの非対象例に前置リダイレクトや接着した入力リダイレクトを添えると、保証範囲はより明確になる。

## 除外した候補：空白を含むCLAUDE_PLUGIN_ROOT

`hooks.json` のコマンド文字列を `bash -c` に渡し、`CLAUDE_PLUGIN_ROOT` を `/tmp/.../plugin space` にすると終了127を再現した。しかし **この再現モデルは現行hooks.jsonに当てはまらない**。

親レビュー担当が確認した公式資料「Exec form and shell form」（https://code.claude.com/docs/en/hooks#exec-form-and-shell-form）では、`args` が存在するとexec formになり、shellによるトークン分割を行わない。現行 `plugin/hooks/hooks.json` は全フックに `args: []` を指定する。このため、単純にコマンド文字列が未引用であることを根拠とした不具合候補は除外した。旧CLIでの非互換についても実機のバージョン根拠がないため指摘しない。

## 検証上の限界

Claude実機でのワーカー応答やCLI互換性は検証していない。スキルとエージェントの指示は一次資料として確認したが、モデルによる契約違反を推測だけで不具合とはしていない。既存評価の全件実行も行っていない。
