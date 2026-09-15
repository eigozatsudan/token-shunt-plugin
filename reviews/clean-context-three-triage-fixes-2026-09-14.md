# 2026-09-14 レビューの再判定と修正

元資料: `clean-context-three-2026-09-14.md`。フックが pass することと、実際のツールが本文を返すことを区別する。以下の「未確認」は不具合の確定を意味しない。独立調査・実装修正・別エージェントの差分レビューを行い、親が実 Bash とフックで再検証した。

| ID | 再判定 | 根拠・対応 |
|---|---|---|
| A1 | 確認・修正 | 変数・特殊パラメータ・ANSI引用の command/operand 展開を追跡し拒否。単一引用・エスケープのリテラルは通過。既存の隔離・バイト上限の例外は維持。ANSI引用の operand は旧READMEにも制限として記載済みで「README未記載」は一部訂正。 |
| A2 | 仕様上の穴・強化 | 解釈不能末尾でも全段の既知readerを検査。echo ok | cat big.txt $(true) を旧pass→deny。 |
| A3 | 仕様上の穴・強化 | 未知末尾も全段を検査する仕様へ変更。grep・wc末尾とstderr側道の提示例をdeny。未知コマンド単独の読み取りは引き続き対象外。旧仕様とコードの矛盾という主張は撤回。 |
| A4 | 既知の範囲制限 | denylist対象外コマンドの存在を確認。汎用シェルsandboxへの設計変更は行わず、READMEで信頼境界を明確化。 |
| A5 | 遅延を再現・修正 | 旧フックはecho+100,000文字で25秒以内に終了せず。8192B固定上限を解析前に追加し、密な入力には3秒の協調的な時間確認も追加。O(n²)という厳密な計算量は未証明。CLIのtimeout時fail-openは今回実機確認していない。 |
| A6 | 確認・修正 | 非引用heredoc本文の実行される$()/バッククォートを拒否。引用済み本文とエスケープ済み置換はリテラルとして通過。 |
| A7 | **一部偽陽性・別形は確認して修正** | 提示された<<$Dは偽陽性。Bashは区切りを変数展開せずcat big.txtは本文になる。追加実測では<<$(true)の後続cat bigが旧フックをpassし、実Bashは802B出力。複雑な非引用区切りはマスク前に拒否し、区切り全体を引用した形は維持。 |
| A8 | 仕様上の除外・実際の本文取得は未確認 | check-file-size の拡張子免除と hooks.json の Read matcher を確認。同内容の .ipynb はフック pass。ただし rename 後の内容を実 Read が notebook として受理するか、NotebookRead が現 CLI に存在するかは未検証。「確認済み回避」は過大。 |
| A9 | 仕様上の制約・再現 | `head -c 65536 f1 f2` は pass。各70,000Bのファイルを使用。判定はファイル単位で合計上限ではなく、ヘッダ分もある。 |
| B1 | 状態喪失を確認・停止動作を改善 | 旧動作も6回予算で終端するため「永久デッドロック」は過大。300秒後は結果欠落としてinvocation全体をpartial停止。継続位置を推測せず新しいReadを許可しない。遅延Postでも再開しない。自動復旧とは扱わない。 |
| B2 | ロック待ちを修正・同一UID制約 | flock待ちを250msに制限しexit 2で拒否。実プロセスによる保持テストで確認。同一UIDの状態削除は防げず、メタデータの存続条件をdocstring/READMEに修正。 |
| B3 | 一部再現・信頼境界の説明不足 | 巨大しきい値による pass と HOOK_LOG=/dev/stdout の2 JSONを確認。ログ先は通常ファイルだけに限定しstdout/stderr別名・FIFO・symlinkは無視する修正を実装。環境変更権限が前提。PATH/BASH_ENV を制御できる利用者はフック実行環境も制御する。設定からの到達やタイムアウト時の CLI 動作は未検証で「高・全て確認済み」は支持しない。 |
| B4 | **互換性確認不足、障害未確認** | doctor-last-probe.txt は CLI 2.1.270、登録確認済み、agent_type は手動確認待ち。scripts/doctor.sh に ID と応答スキーマの確認手順がある。フィールドが実際に欠落した証拠はなく、委譲不能を確定できない。 |
| C1 | 確認・修正 | head/tail -n0の既知ファイル読み取りを通過し、実Bashの出力0Bを確認。 |
| C2 | 確認・修正 | パイプの各head/tailでも自身の出力量を検査。head/tail -n5 big.txt | catの出力10Bとpassを確認。 |
| C3 | **確認・修正済み** | jq のない PATH で check-agent-model は exit 2。check-jq の案内を Read/Bash/Agent/Task に修正。 |
| C4 | UX改善候補 | deny は bulk-reader 案内のみ。ただし既存コード編集の targeted Read 契約も案内しており、code-writer 自動推奨が常に正しいとは限らない。動作不良ではない。 |
| C5 | 保守性指摘 | 計測・設定・ログ関数の重複は存在。重複だけでは実害の証明にならない。 |
| C6 | 将来互換性の仮説 | check-agent-model は subagent_type のみ、judge は type も受理。実 CLI フィールド変更の証拠なし。 |
| C7 | 入力検証を統一 | 2サイズフックも単一JSON objectだけを受理。複数文書・配列・nullはexit 2。実ハーネスからの複数文書送信は未確認。 |
| C8 | 確認・修正 | cd追跡の括弧を字句種別で判定し、引用されたf(1).txtを誤ってグループ構文扱いしない。 |
| C9 | 条件付き誤判定を修正 | 指定された絶対パスcwdで両フックを検査。同名の小/大ファイルを別ディレクトリに置き、event cwd優先を実行確認。未指定時は起動cwd。実CLIの永続cdとの乖離は未確認。 |
| C10 | 起動失敗はコード上明白、CLI影響未確認 | Read Post/Failure の全件に Python shebang スクリプトが登録される。Python 不在時は非 worker でも起動不能。これが既に成功した Read を阻止するか等はハーネス依存。 |
| C11 | 同一 UID のローカル妨害 | tempfile.gettempdir 配下の root を mode/UID/symlink 検査する。先取りによる拒否はあり得るが、同一 UID が実行環境を変更できる前提で独立した権限境界破りではない。 |
| C12 | 構造的な競合窓 | サイズ計測と実 Read は別 open。同期を強制できないため内容変更の競合は残る。具体的な競合 PoC は未実施。 |
| C13 | **未再現・条件付き仮説** | 当環境の awk は a + NUL + b の length を3と数える。問題の処理系が特定されておらず「確認済み」は撤回。 |
| C14 | オプトインログの性質 | check-bash-read:45 の hook_log は command 全文を指定先へ追記する。外部への自動送信ではなく、利用者指定ログの権限・共有範囲に依存する。 |
| C15 | ビルド入力の信頼前提 | zip -r は通常 symlink を辿り、Python 分岐もファイルを open する。一方 Python os.walk はディレクトリ symlink を既定では辿らないため一律の説明は不正確。悪意ある plugin 入力を受け入れる前提なしでは独立した脆弱性としない。 |

## 担当分の再現方法

一時ディレクトリに big.txt = `x\n` ×400（800B）、同内容 big.ipynb、f1/f2 = 各70,000B、sub/f(1).txt = `ok\n` を作成。フック stdin は `{"tool_input":{"command":"..."},"cwd":"一時ディレクトリ"}` または tool_input.file_path を設定し、subprocess の cwd も同ディレクトリで実行した。deny は exit 0 + permissionDecision=deny の場合もあるため終了コードのみでは評価していない。

A7 は `D=EOF bash` に次のスクリプトを渡した。フックは pass、実 Bash の出力は EOF と cat big.txt の2行のみであり big.txt の内容は出ない。

```bash
cat <<$D
EOF
cat big.txt
$D
```

B3 は `TOKEN_SHUNT_MIN_LINES=999999999999999 TOKEN_SHUNT_MIN_BYTES=999999999999999` で Read pass。`TOKEN_SHUNT_HOOK_LOG=/dev/stdout` では同じ Read のログ JSON と deny JSON が計2行になった。C3 は空 PATH を設定して `/bin/bash plugin/hooks/check-jq` と check-agent-model を直接実行。C13 は Python subprocess から `awk '{print length($0)}'` に bytes `b'a\0b\n'` を渡して出力 `3` を確認した。

## 変更と検証

変更対象は `plugin/hooks/check-bash-read`、`check-file-size`、`check-reader-contract`、`check-jq`、追加した `write-hook-log`。READMEの動作説明を追従し、既存のagents/skills/compare関係の作業中変更を保持した。汎用シェル解釈器やハーネスの権限境界は導入していない。

- 構文: `bash -n plugin/hooks/check-bash-read plugin/hooks/check-file-size plugin/hooks/check-jq evals/run.sh`。
- 再現と正常系: `python3 -B evals/test_clean_context_fixes.py`（8テスト）、`python3 -B evals/test_hook_logging.py`（5テスト）、`python3 -B evals/test_reader_contract.py`（17テスト）。新規テストもevals/run.shに登録。
- 既存回帰: `python3 -B evals/test_bash_finding_fixes.py`（14テスト）を確認。未知パイプ末尾の仕様変更に対応するカタログ期待値2件をpassからdenyへ更新。
- 配布チェック: `bash evals/run.sh` は **pass: 123 / fail: 0**。ネストした回帰スイート・marketplace検証・ZIP構成/実行権限検証を含む。`token-shunt.zip`を再生成した。

差分レビューで区切り終端の誤拒否が挙がり、終端照合を本文実行検査より前へ移した。その後、非引用の複雑な区切りは元の字句解析では終端自体が一致しないことを実行確認したため、マスク前の明示拒否にした。単一引用の複雑な区切りは本文と後続コマンドを正しく分離するテストを追加した。

残る限界: 実CLIのstdinスキーマ・実Readのnotebook decoding・CLI timeoutの挙動は本検証では未実行。環境や同一UIDの状態/実行ファイル変更、未対応コマンド、呼び出し合計、TOCTOU、停止した通常ファイルシステム呼び出しは防止保証の対象外。B1は安全に停止させる改善であり、失われた結果の復元ではない。

最終計測: `echo ` + 100,000文字（100,005B）は0.034秒でdeny。密な通常出力隔離（600個のリダイレクト、7,214B）は1.443秒でpass。時間予算は協調的検査であり、O(n)化や任意の低速FSでの絶対締切を意味しない。最終実行ログ: `/tmp/token-shunt-clean-context-evals-final.log`。`git diff --check`も成功。
