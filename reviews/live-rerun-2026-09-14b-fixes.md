# 2026-09-14b レビュー対応

対象: `reviews/live-rerun-2026-09-14b.md`。3サブエージェントでルーティング、応答契約、評価要求を分担し、親で統合・計数修正・実機確認を実施。

## 原因の訂正と修正

- `verification_execution` 13件は未実行ではなかった。6件のwriter境界実行は `wc && py_compile && echo` 等、残り7ファイルは継続行・相対パス・終了状態ラベルを含む検証バッチで実行済み。判定器で限定的な構文を認識し、成功したAND連鎖または各コマンドに対応する順序付きJSON結果を要求する。失敗を隠す `; echo` / `|| true`、引用された `&&` による偽証跡は拒否する。
- `gold_confirmed` の期待パスは basename が fixture root 直下に解決されていた。`rails/app/...` の実際のfixture相対パスに訂正。再判定で7件中2件が解消。残り5件は実際の契約違反で、2件は `.../app/...` へのパス省略、3件は `confirmed:` と絶対パスの証拠項目自体を省略していた。別実行の絶対パス・basenameだけの引用・unconfirmed は引き続き不合格。
- Bashの `deny_bypass` 2件は、行数・バイト数だけを返すメタデータ計測だった。限定的な `for` ループと `sed | wc` を識別し、本文出力・tee・コマンド追加・置換・リダイレクトは例外にしない。
- 16,385バイトでReadフックが通ること自体は仕様どおり。委譲基準16,384バイトとフック拒否閾値65,536バイトを混同しない指示を、スキルの説明と本文に追加。50行writerもWrite前に委譲判断することを説明に明記。フックの閾値は変更していない。
- 子の応答には末尾の独立した `status:` / `stop_reason:` 行を要求。writerの呼び出し文に800字以内・参照Read後のWrite・必須状態行を明記。委譲後の分析を親のtargeted Readで回収しない指示も追加。
- 編集位置の一意なGrep、原本targeted Read、編集前の値を含む最終回答など、既存の判定要求をケース文面に明示。

## 単一行の比較基準

旧directはReadを試みており、CLIが34,953トークンとして標準25,000上限で拒否していた。その後Grepで値だけを取得したため比較基準が縮小した。単なる未読指示違反ではない。

約70KBのfixtureを維持し、`compare-one-line` / `auto-one-line` の全モードをネイティブRead上限40,000で統一した。他ケースは25,000に固定。カタログと解決済みspecに記録し、ambient設定の影響を除いた。これはRead可能な隔離比較であり、標準CLI上限での可読性試験ではない。

## 計数

`done:` とFAIL一覧は最終aggregateから出力する。プローブは `probes:` に別掲し、disk/isolationによる後付け失敗も反映する。aggregate全体のエラーは実行数に混ぜずERROR表示する。

## 検証

- 比較評価のPython回帰265件、フック等のPython回帰100件が成功。
- `evals/run.sh`: pass 121 / fail 0（カタログと関連回帰を含む）。`git diff --check` も成功。
- `scripts/build-zip.sh` で配布ZIPを再生成し、構成・実行権限の検証に成功。
- 実機対象: `compare-one-line,auto-routing-boundary-16k-plus,auto-routing-boundary-50-lines-writer`。
- 証跡: `evals/compare/tmp/runs/run.PKrzzQTf`。プローブ3件成功、最終集計 **pass 2 / fail 6 / runs 8**。`done:` と一致。
- `compare-one-line/direct` と `haiku` が成功。親追加量はdirect 70,128バイト、haiku 16,093バイト。directのReadが成立し、当該2実行の比較を確認できた。
- その後の6実行はClaudeセッション上限（18:10 JSTリセット）で結果エラー。境界ルーティング・残りモード・全75実行の成否は未確認。複数周回とコスト中央値の評価は未実施。
- `selected_run_valid` / `release_eligible` はfalse。今回の修正だけでモデルの指示遵守や費用改善を保証するものではない。

## 旧証跡の再判定

`live-rerun-2026-09-14b-rejudge.json` に75実行分の単体判定を保存。旧specはgold_pathsだけ訂正し、新しいプロンプト・Read上限は遡及適用していない。単体判定はpass 42 / fail 33からpass 49 / fail 26、理由件数はverification_execution 13→0、gold_confirmed 7→5、deny_bypass 3→1。aggregateの隔離判定・リリース判定は再計算していないため、元レビューのaggregate pass39/fail36とは直接比較しない。
