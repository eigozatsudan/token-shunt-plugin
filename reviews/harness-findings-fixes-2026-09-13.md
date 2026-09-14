# 別ハーネス指摘の修正（2026-09-13）

対象は HEAD b66c13f と、それ以降の単一行契約・model hook の未コミット変更。フック、評価器、ハーネスを3サブエージェントへ分担し、親で契約・文書・統合検証を担当した。実機API評価とコミットは実施していない。

## 対応

| 指摘 | 対応 |
|---|---|
| F1 | 引用外プロセス置換を拒否。通常ファイルへの出力隔離として扱わない。 |
| F2 | tail の旧式 +N を解釈不能なサイズ指定として全文閾値で判定。 |
| F4 | Read/Bash フックは Bash 4 未満で早期 exit 2。SessionStart は警告、doctor は失敗。 |
| F5 | 仕様外のグループ化・制御構文・wrapper を README に具体例付きで明記。シェル全体の解析へ拡張しない。 |
| F6 | 対象 reader の未引用 glob/tilde/brace 展開を拒否。既存の安全なバイト上限・通常ファイルへの出力隔離は維持。 |
| F7 | 先頭 cd の移動先を解決できなくなった後の対象 reader を拒否。古い cwd の不存在を通過根拠にしない。 |
| F8 | doctor の「HOOK_LOG で captured stdin を確認」の誤手順を訂正。 |
| F10 | fixture の引用文脈を保つ置換、空白・改行を保持する env 引数化。 |
| F11 | reader の maxTurns=7、Read 予算=6。終了報告用ターンを確保。 |
| F12 | reader の status/stop_reason を末尾検査。箇条書きのラベルも許容し、欠落・重複・空理由は拒否。 |
| F13 | 非パイプの本文回収を検出。grep の filename/count/quiet 出力、echo の単なる文字列を本文回収と混同しない。 |
| F14 | stat と独立に実バイト・末尾改行を数える。head/tail の byte 指定にも限定実測を適用。 |
| F16 | 4大容量ケース・4モードの今回のUSD合計、差分、欠測、実行失敗を記録。 |
| F19 | worker 試行、要求model、観測した status/stop/fallback/retry reason を保存。不明は null。 |
| F20 | 全Bashなどが依存不足で止まることと、外部ターミナルからの復旧・無効化を明記。 |

P3 の具体的な問題も対応した。任意 hook log に帰属フィールドを追加し、compare 起動時に旧 summary を無効化、完成した JSON を公開する。中断用 trap と timeout の kill-after を追加。不正 JSONL は黙殺せず失敗にする。ZIP の検証対象へ新しい Agent hook を加えた。

model hook の起動前拒否は、対応する error 結果・専用理由文・子活動なしが揃う場合だけ実起動から除外する。拒否された試行は metrics に残す。一般の Agent エラーを除外する変更ではない。

## 検証と限界

最終統合検証で compare 193 tests、evals/run.sh 113 pass / 0 fail、judge selftest 16件が成功。フック単体59 tests、空白入りrepoでのcatalog、引用符・ドル・backtickを含むパス、空白・改行env、stat過少の再現を検証した。cap / child_no_body 未指定でも reader の終了契約を検査する回帰も含む。

Bash 3 実機はないため、旧版の値を注入したコピーで早期拒否を検証した。maxTurns の実機終了挙動も未検証であり、強制停止時に回答がないものを成功にはしない。

F3 の過去の費用増加は結果として残す。今回の USD は CLI が報告する単回費用の集計で、48実行・3反復中央値の費用実験や料金表からの独立再計算ではない。費用削減は実証しておらず、費用だけで出荷合否は変えない。

F9/F15 は現行ですでに修正済み、F17/F18 は前回分類のとおり変更対象としない。一般的な TOCTOU の解消や、追跡済み生成物の削除は今回の修正には含めない。

## 追加指摘 F21–F25 の修正

別の3サブエージェントで判定器・環境/gold・ZIPを分担し、親で境界条件と文書を確認した。

- F21: require_parent_tokens の bool / mode配列を単体判定と集計で共通解釈。不正な型・未知モードは spec fail。
- F22: Transcript の入口でツール入力の object、既知文字列フィールド、Read の正整数を検証する。不正値を空値に補正せず、イベント位置・tool ID・フィールド付きの transcript fail を返す。Edit/検証コマンドの下位処理にも型ガードを追加。
- F23: 両ランナーは起動時に CDPATH を解除。run_hook / run_claude は ambient TOKEN_SHUNT_* と CDPATH を除去し、明示catalog設定またはrunner生成fixtureのみ再設定する。認証・PATH・モデルoverride診断は保持する。
- F24: 各modeでfixture再生成後に gold_file の型・存在・単一JSON・非空文字列配列を検査。不正ならcase CLIを起動せず、specとgold_input失敗理由を保存する。judge / aggregate も解決済みgoldの欠落を拒否する。
- F25: Python / zipinfo の両経路でmanifestと同じルートの4フックを検証。ルート/一段下配置を扱い、欠落・非実行権限・重複・別ディレクトリによる偽装・複数manifestを拒否する。

最終検証: compare 201 tests OK、evals/run.sh 114 pass / 0 fail、judge selftest 16件成功、git diff --check成功。ZIP検証は両backend・両配置を含む28サブケース、不正goldは7種類を検証した。CLIはテストダブルであり、実機API再評価やコミットは行っていない。
