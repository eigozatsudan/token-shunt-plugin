# F1〜F8 修正・検証記録（2026-09-14）

結果: **fixed**（検証で確定した範囲）。既存の未コミット変更を保持して修正した。
実機全スイートの新規測定やリリース判定を行ったという意味ではない。

## 修正内容

| 指摘 | 修正 | 主なファイル |
|---|---|---|
| F1 | 先頭リダイレクト・代入を共通のコマンド識別で扱い、fd転送順序を保持。単独・複合・パイプの明示入力を検査。先頭リダイレクト付きcdの未解決状態と名前付きfdも対処 | plugin/hooks/check-bash-read |
| F2 | リダイレクトごとの全前置・後置再字句化を廃止し、字句化結果を1回走査 | plugin/hooks/check-bash-read |
| F3 | reader契約、新Bash回帰、doctor回帰を標準ランナーの合否集計へ追加 | evals/run.sh |
| F4 | 共通deny処理でtoken-shuntの帰属を保証 | plugin/hooks/check-bash-read |
| F5 | 記録済みcwdに基づくパス同一性。絶対パス・相対名・リンクを正規化し、cwd不明の相対Readは証拠不足として禁止チェックを不合格 | evals/compare/judge.py |
| F6 | Python不足時は既存サイズフックがbulk-readerをexit 2で遮断。契約フックの非object JSON・不正な入れ子を診断付きexit 2にする | plugin/hooks/check-file-size, check-reader-contract, check-jq |
| F7 | 5フックの構成・一覧に更新 | docs/distribution/README.md |
| F8 | 同ディレクトリの一時ファイルへ一度に書き、置換成功後だけrecorded。準備・書込み・置換失敗は非0、既存記録を保持 | scripts/doctor.sh |

READMEと設計正本も保証範囲・依存条件・検証手順に合わせて更新した。
配布ZIPを既存ビルドスクリプトで再生成。生成済みbytecodeを除いた一時ステージから
ビルドし、ZIPの全11ファイルが現在のpluginソースとバイト一致することを確認した。

## 元の問題と正常系の確認

- 前置stderrリダイレクト、fd複製、heredoc、パイプ・複合の元のF1トリガーは拒否。
  制御用bashで80,000バイトの出力を確認したうえで、同じ入力のフック拒否を検証した。
- 通常ファイルへのstdout隔離、小さなRead、headのバイト境界、fd転送順序、
  引用されたfd風のファイル名、heredocのリテラル本文、算術シフトを正常系として確認。
- F2は100/200/300リダイレクトで0.486/0.965/1.518秒、最終出力がstderrへ戻る全例を拒否。
  /dev/nullへ閉じた正常系は通過。時間はこの環境の実測で、一般的な実行時間保証ではない。
- F4の実フックdenyをjudgeへ渡し、両方でforeign_hooksが空、ts_deny_payloadが取得できる。
- F5の/./、//、sub/../、相対名・リンクの同一ファイルは拒否。別の同名ファイルや
  symlink/..の異なる到達先を誤認しない。cwd不明を「別ファイル」と断定しない。
- F6はhooks.jsonの実際のReadフック組合せをPythonなしPATHで実行し、bulk-readerを遮断。
  親とcode-writerにはbulk-reader専用の依存条件を課さない。[]/nullはexit 2。
- F8はCLIスタブと無改変のdoctorコピーを使い、準備・実書込み・置換失敗、
  ディレクトリとディレクトリへのリンクを検証。成功時だけ記録が更新される。

## 検証ゲート

1. 構文・差分: `bash -n`（変更Shell群）と `git diff --check` は合格。
2. 直接回帰: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest evals.test_bash_finding_fixes evals.test_bash_operational_hooks evals.test_cd_hooks evals.test_review_hooks evals.test_scan_budget_hooks evals.test_symlink_hooks` は70 tests OK。
   reader契約11件、doctor記録5件、パス同一性7件も合格。
3. 標準検証: `PYTHONDONTWRITEBYTECODE=1 bash evals/run.sh` は **pass 119 / fail 0**。
4. 比較評価: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s evals/compare -p 'test_*.py'` は **226 tests OK**。
   `judge.py --selftest` も全項目合格。
5. 保存済み75実行のjudge再判定は前回修正後と同じ **pass 48 / fail 27**。新たな退行なし。
   disk・費用・live aggregateを再測定したものではない。
6. ZIPビルド・内容一致・構成・実行権限の検証は合格。

## 独立レビューと残る限界

サブエージェントによる事前調査、3分担の実装、別のread-onlyレビューを実施した。
レビューで残っていた前置リダイレクト付きcdと名前付きfdの経路は、親でも再現を確認し、
修正・回帰テストに含めた。heredocの末尾改行によるstdout隔離の誤拒否と、算術の<<を
本文として誤認する問題も確認して修正した。

名前付きfd、ANSI-C/ロケール引用のheredoc区切り、非引用heredoc本文のバックスラッシュ改行は
保守的に拒否する。リダイレクト・代入付きcdの後のreaderも未解決として拒否する。
入力リダイレクトだけによる本文回収、既知の非対応wrapper等は保証範囲を拡張していない。
過去に変更・削除されたシンボリックリンクの履歴は保存transcriptだけでは復元できない。
ライブモデル呼出・キャッシュ更新・プラグイン公開・コミットは行っていない。

証跡ディレクトリ:
`/tmp/codex-security-scans/token-shunt/b66c13f_20260913T231529Z/artifacts/`
（fix-final.diff、fix-files.json、fix-package.json、fix-redirect-timing.json、fix-deny-attribution.json）。
