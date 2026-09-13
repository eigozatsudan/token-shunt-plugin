# 再レビュー: 5観点・統合・偽陽性チェック

対象: HEAD `338e981`、現行プラグイン・評価コード・運用スクリプト。
前回レビュー後にソース修正はない。今回もレビューのみでコード修正・コミットは行っていない。

## コンテキストと手順

新規エージェント `r8_overview` を fork_turns=none で起動し、過去レビュー・git履歴を渡さず調査。
追加起動はスレッド上限で拒否されたため、この1名が5観点を順にレビューした。
5つの独立コンテキストではない。親は過去の会話を保持する統合・検証担当であり、
親自体をクリーンコンテキストとは扱わない。

独立発見段階は本文量指標の欠落1件、棄却候補2件。
その段階を区切ってから、親が現行コードで再現した5候補を提示し、統合後の偽陽性チェックを実施。
独立に発見した結果と、提示された候補の検証を混同しない。

## 統合した真陽性

| ID | 優先度 | 問題 | 場所 | 発見経路 |
|---|---|---|---|---|
| F1 | P2 | unconfirmedだけの回答をconfirmedとして受理 | evals/compare/judge.py:424 | 親の再現→統合検証 |
| F2 | P2 | 表があると後続の明示的な矛盾する検証報告を破棄 | evals/compare/flow_checks.py:106 | 親の再現→統合検証 |
| F3 | P2 | 全文拒否後、返却終端不明でも要求終端から次のReadを許可 | evals/compare/routing_checks.py:155 | 親の再現→統合検証 |
| F4 | P2 | 非同期の親向け回答を本文量指標に加算しない | evals/compare/judge.py:253 | クリーンな独立発見→親の再現 |
| F5 | P2 | READMEの明示検証コマンドがcwd外の正常testで失敗 | README.md:80 | 親の再現→統合検証 |
| F6 | P2 | コメントに対象名があれば無関係なunittestを親検証と認定 | evals/compare/judge.py:84 | 親の再現→統合検証 |

### 再現と正常対照

- **F1**: `gold_confirmed_ok('- unconfirmed: /a.py — TOKEN\nstatus: partial', ['TOKEN'], {'gold_paths': {'TOKEN': ['/a.py']}})` が不足なし。
  fallback正規表現がunconfirmedの途中に一致。真confirmedなら正当な成功、goldなしなら失敗。
  真confirmedの別項目がある場合はfallbackに入らず未確認goldを拒否する。
- **F2**: control_trunc.jsonの表にsyntax/failed、後続散文に同artifactの
  `verification: requirements status: complete` を明示しても禁止control検査を通る。
  矛盾なしの表は正当な成功。単なる補足文を許容する意図と、明示的な再宣言の無視は別問題。
- **F3**: 全文token-cap拒否→offset1/limit3の成功結果が行番号なしのsource→offset4/limit7成功がエラーなし。
  中央結果に正しい1–3行ラベルがあれば正当。拒否なしでは終端不明継続が拒否される。
  現行agentの「終端不明ならpartial停止」に対する判定漏れで、実際の終端を証明できない。
- **F4**: 独立レビューはsummaryを16バイトから漢3,900文字（11,700バイト、4,000文字以内）へ増やしても
  parent_added_utf8_bytesが5,477固定と確認。同期返答では58→11,742に増加。
  親の別対照でも短いlaunch ackで20/3,000文字のsummaryが両方76バイトとなった。
  child_return_ofが正式な親向け返答として解決する通知なので、中間イベントを除外しただけではない。
  影響は本文隔離指標とbytes/4推計。実usageや実請求額そのものの誤計上とは主張しない。
- **F5**: 現環境にpython aliasなし。python3へ直してもrepo cwdから/tmpの正常な1テストの絶対パスを
  `-m unittest`へ渡すとexit1。`discover -s <dir> -p greeter_test.py`なら同じtestがexit0。
  明示--verifyなのでfallback修正では救済されない。cwdによって旧式も通るため常時失敗ではない。
- **F6**: `python3 -m unittest discover -s /tmp/tests -p unrelated.py # greeter_test`
  がunittest起動とgreeter_test対象の両contains条件に成功する。
  コメントを消すと対象名検査は失敗。disk_checkは別途対象を検証するので、
  リリース全体で失敗testを見逃すとの主張ではなく、親の対象検証証拠の誤認。

## 棄却した候補

1. **空白を含むプラグイン導入先でフック起動が必ず失敗する**: 偽陽性。
   シェル再現は失敗しても、現行hooks.jsonの3フックはいずれもargs:[]を持つ。
   公式仕様ではargs指定時はシェルを介さず直接起動し、パスは分割されない。
   現行exec形式への反例になっていない。
   根拠: [Claude Code Hooks reference — Exec form and shell form](https://code.claude.com/docs/en/hooks#exec-form-and-shell-form)。
   古いCLIの挙動を未検証のまま現行不具合へ一般化しない。
2. **費用データがnullでも出荷可能**: 仕様通りであり不具合から除外。
   現行設計§13/§26.5/§26.6は費用欠測を出荷failにせず、48実行費用比較を後続工程に置く。
   READMEも削減未確認を明示。親本文量、累積親usage、親子費用は別指標として扱う。

## カバレッジと検証

- 俯瞰: README、設計の受入条件・制約・出荷段階、両スキル/両エージェント。
- 通常: Read/Bashフックの走査・閾値・範囲・解析、Read継続・retry契約。
- 敵対的品質: 引用・リダイレクト・パイプ、委譲証跡、通知順序と判定境界。
- 運用: manifest/hooks設定、doctor、ZIP生成、比較ランナーの初期化と隔離。
- トークンコスト: 親本文指標、親usage、集計ゲート、費用欠測と出荷契約。

今回のフックテスト: 52件成功（14.292秒）。ZIPの9ファイルはpluginと一致し、フック実行ビットも正常。
比較用144テストは同コミットの直前検証で成功済みであり、今回は上記の対象再現を実行。
実機API・実費計測はなし。既存pyc4件は変更状態を保持。
全コード分岐やホスト内部の網羅保証はない。6件は未修正であり、レビュー結果は未コミット。
