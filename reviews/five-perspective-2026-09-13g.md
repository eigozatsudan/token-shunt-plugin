# 5観点レビュー・Codex合算・再検証

対象: HEAD `cb1ab7c94952df128aa9d171217177390b4a151e` の現行作業ツリー。
実施日: 2026-09-13。レビュー開始時は実装を変更していない。確定した真陽性の修正は同日の後続作業。

後続の精査で見つかったG1・G2・G4の修正不足も反映した。最終的な変更と検証結果は [修正完了記録](five-perspective-2026-09-13g-fixes.md) を参照。この文書の初回原票は当時の観測として保持する。

## 手順

1. 会話を継承しない5サブエージェントで、カレントの自作プラグインを俯瞰・通常・敵対的・運用・トークンコストでレビューした。`reviews/`・`docs/history/`・git履歴は初回根拠に使わない。
2. 親が候補を合算し、Codex側のクリーンコンテキスト5観点（`reviews/clean-context-five-2026-09-13/` の P2×5）と結合した。
3. 合算リストを、再び会話を継承しない3サブエージェントで再検証した（評価器 / フック / 運用）。仕様は設計 §§1–15・§26 と README。
4. 親が再検証報告と現行コードを照合し、コード修正とドキュメント追記を分けた。

独立発見と、提示候補の再検証は混同しない。採否の正本はこのファイル。

## 再検証後の真陽性（修正対象）

| ID | 優先度 | 問題 | 場所 | 発見 |
|---|---|---|---|---|
| G1 | P2 | 同一 `message.id` の後続 `tool_use.input` を parent_added / leakcheck から落とす | `evals/compare/judge.py` `parent_added_text` | セッション（コスト）＝ Codex F2 |
| G2 | P2 | 複数親 `result.usage` が区間値なのに最後だけを累積トークンにする | `evals/compare/judge.py` Transcript / `metrics` | Codex F5 |
| G3 | P2 | フック評価カタログ JSON が壊れても `evals/run.sh` が成功終了する | `evals/run.sh` process substitution | Codex F4 |
| G4 | P2 | fixture 本文が読めないと `child_no_body` が 2KiB 引用を pass にする | `evals/compare/judge.py` `quote_leak` | セッション（敵対的） |
| G5 | P2 | 委譲 EOF 行数が `wc -l`（改行数）で、未終端最終行を落とす | `plugin/skills/bulk-reader/SKILL.md` | Codex F1 |

優先度は条件・影響範囲に基づきP2とする。ホスト権限の破壊はP1の必要条件ではない。G1は実CLIログでisolation合否が反転しうるため、評価結果の信頼性に関わる修正として扱う。

## 再検証でコードバグから外したもの

| 候補 | 判定 | 理由 |
|---|---|---|
| CLI 終了コード 17 でも本文があれば比較評価成功（Codex F3） | 当初は偽陽性分類。精査後に仕様を明文化 | 元の設計にはCLI終了コードとケース評価終了コードの区別が曖昧な箇所があった。後続修正ではケース本体を本文・ディスク検証で判定する既存動作を明記し、CLI終了コードは `cli_exit_code` として保存する。プローブ非0、親result欠落・エラー結果はfail。 |
| `cat <large.txt` / `head -c 70000 <large.txt` の通過（セッション敵対的） | コードは偽陽性。docs は既知穴 | 現象は再現。§10-6 の「対象 0 なら通過」と一致。パイプ末尾の `-c` 判定とは別規則。README 表は広く読めるので §15 / 制限事項へ追記。 |
| ANSI-C `$''`（セッション敵対的） | 仕様の隙間。docs は既知穴 | 状態機械は `'"` `\` のみ。`$('` は解釈不能、`$'` は未列挙。フック変更は仕様変更。 |
| Bash がコマンド末尾 LF を落とす（セッション敵対的） | 偽陽性 | 非クォート改行は bash でも単語区切り。フックと実 bash が開くファイルは一致。Read の sentinel 契約とは別。 |
| deny 後の Grep content（セッション敵対的） | 仕様の隙間 | §26.5 の deny_bypass は連続 Read とパイプ。§11.8 の「eval で担保」と列挙が食い違う。編集 Grep（§11.6）と衝突するコード追加はしない。 |
| doctor がキャッシュを見ない（セッション運用） | docs-only P3 | `--plugin-dir` + `--setting-sources ""` は設計 §13 の隔離プローブ。別のキャッシュ診断は現行の必須範囲ではない。READMEが「インストール診断」と読める点を直す。 |
| 空白パスのフック起動失敗 | 偽陽性（両レビュー一致） | `hooks.json` は `args: []` の exec form。 |
| 費用削減未証明 | 仕様どおり | §1.1 / §26.5。出荷ゲートではない。 |

## 独立5観点の要約（初回）

| 視点 | 初回 | 再検証後に残るコード欠陥 |
|---|---|---|
| 俯瞰 | P3 文書2件（配布READMEの費用比較、設計の python unittest 例） | コード欠陥なし。設計の検証例は今回の必須修正に含めない |
| 通常 | 0件 | 0件 |
| 敵対的 | stdin `<`、`$''`、末尾 LF、Grep、欠落 fixture | G4 のみコード。他は docs / 偽陽性 |
| 運用 | doctor stdin、doctor キャッシュ、判定スクリプトを Write 許可 | キャッシュは docs。stdin 例は README が HOOK_LOG 非保存を既に書くため必須修正にしない。Write 許可はヘルパー意図 |
| トークンコスト | 同一 id 分割 | G1 |

Codex 側の独立報告は [clean-context-five-2026-09-13](clean-context-five-2026-09-13/README.md)。初回5原票は `five-perspective-2026-09-13g-{overview,normal,adversarial,ops,cost}.md`。再検証原票は `five-perspective-2026-09-13g-reverify-{eval,hooks,ops}.md`。

## 修正方針（確定後）

1. `parent_added_text`: tool-use ID、イベントUUIDとブロック位置で再送を除外する。同じ引数の別ツール呼出も計上し、本文一致だけで重複扱いしない。
2. `metrics`: 一意の親resultの区間usageを合算し、欠測区分を0へ補完しない。子resultは除外し、`modelUsage` は最後の親resultのまま。
3. `evals/run.sh`: カタログが非空配列でなければ非 0。
4. `child_no_body`: 指定fixtureを相対・絶対パスの一意な対応で解決し、一部でも読めなければfail。別ファイルの本文で代用しない。
5. スキル / 設計: 委譲後の行数は論理行（未終端最終行を含む）。`wc -c` はサイズ用。
6. README / §15: `<` と `$''` を既知穴に。doctor はソースの `--plugin-dir` プローブでありキャッシュ正本ではない。

## 検証限界

実機 API・新規の費用計測はしていない。保存済み比較ログは判定器の再計算に使った。修正後にPythonテスト173件とフック110件が成功した。最終状態は[修正記録](five-perspective-2026-09-13g-fixes.md)を参照。
