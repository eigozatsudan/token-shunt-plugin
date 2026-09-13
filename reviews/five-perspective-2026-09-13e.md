# 5観点レビュー・統合・偽陽性確認

対象コミット: `338e981`（直前までの修正をコミット済み）。対象はプラグイン全体と運用・評価コード。
今回のレビューでは製品コードを変更していない。既存の変更済み pyc 4件は保持。

## 実施方法と制約

`fork_turns=none` の新規エージェント2名で開始し、過去 reviews を読まず独立調査した。
3名目以降は `agent thread limit reached` で拒否され、子からの新規起動も同じ結果だった。
したがって俯瞰・運用・トークンコストは1名、通常・敵対的はもう1名が別パスで担当。
5観点すべてを確認したが、5つの完全に独立したクリーンコンテキストではない。
親は候補を統合し、合成トランスクリプトと正常対照を再実行して検証した。
実機API実行・価格照会・新規の費用計測は行っていない。

## 統合結果: 真陽性6件

### F1 [P2] unconfirmedをconfirmedとして正答扱い

場所: `evals/compare/judge.py:424`（confirmed_items のfallback正規表現）。

先頭形式の confirmed 項目がないとき、fallback の `confirmed:` は
`unconfirmed:` の途中にも一致する。
`- unconfirmed: /a.py — TOKEN` と `status: partial` だけでも、
gold_paths が TOKEN→/a.py の gold_confirmed_ok は不足なしを返す。
担当者は compare-explicit-multifile の正常な Agent/Read 証拠を保持し、最終回答だけ
unconfirmed/partial に替えた場合も全 judge が成功することを確認した。
未確認回答を正答にしてしまうため、単なる表示形式の差ではない。

正常対照: confirmed のみなら成功、goldを消せば失敗。
別の真 confirmed 項目と unconfirmed gold を混在させると失敗するため、
fallback限定の見逃しであることも確認。

### F2 [P2] 表があると後続の矛盾する検証報告を捨てる

場所: `evals/compare/flow_checks.py:106–107`。

artifact_sections は表の行を見つけると、その成果物の他のセクションを一律上書きする。
`| control_trunc.json | syntax | failed |` の後に
`control_trunc.json verification: requirements status: complete` と追記しても、
requirements/complete禁止の control 判定を通る。
担当者の fence.md 対照でも同様。親コミットでは失敗し対象コミットでは成功する回帰。

正常対照: 追記なしは成功。単なる補足文を許容する意図は妥当だが、
明示的な verification/status 再宣言まで捨てるのは誤合格につながる。

### F3 [P2] 拒否後は返却終端不明でも次のReadを許す

場所: `evals/compare/routing_checks.py:155–159`。

全文token-cap拒否後にpartition状態を維持し、返却ラベルが読めない成功結果を
要求spanで代用する。その結果、実際の最終行が不明なのに要求終端から継続できる。
合成例: 全文拒否→offset1/limit3の成功結果が単にsource→offset4/limit7成功。
child_reads_once のエラーは空。
`plugin/agents/bulk-reader.md:28` の終端不明ならpartial停止という現行契約に反する。

正常対照: 中央結果に1–3の正しい行ラベルを付ければ正当な継続。
先行拒否なしなら同じ終端不明継続は拒否される。
既存挙動だが、今回の対象は全体レビューなので除外しない。

### F4 [P2] 非同期回答が親の本文量指標に加算されない

場所: `evals/compare/judge.py:253–273`。

parent_added_text はassistant/userだけを収集し、親へ届く
system/task_notification.summaryを含めない。
child_return_ofは同通知を正式な子の返答として扱っている。
短いlaunch ackを使う対照では、summaryが20文字でも3000文字でも
parent_added_utf8_bytesは76のまま。同期返答なら返答量に応じて増加する。

正常対照: 両方の非同期summaryをchild_return_ofは正しく解決し、4000文字制限内。
従って子の返答上限検査では防げない。本文隔離のdelegate/direct比較を過小評価し得る。
実usage由来のparent_input_tokensや実API請求額の誤計上とは主張しない。

### F5 [P2] READMEの明示verify例が正常なテストでも失敗

場所: `README.md:80`。

例が `python -m unittest /abs/greeter_test.py` のまま。
現環境はpython aliasがなく、python3へ置換しても、cwdからimportできない
絶対パスの正常な1テストに対してModuleNotFoundErrorで失敗する。
明示--verifyなので、更新済みSKILLのfallbackは使われない。

正常対照: 同じファイルを `python3 -m unittest discover -s <dir> -p greeter_test.py`
で実行すると1テスト成功。旧式でもcwdが対象の祖先なら成功する。
常に失敗するとの断定ではなく、文書が提示する任意の絶対パス利用に欠陥がある。

### F6 [P2] コメントの対象名で無関係なunittestを検証済みとする

場所: `evals/compare/judge.py:84–85`。

parent_bash_containsはunittest起動部分を構文解析する一方、greeter_testなど対象名は
生commandへの部分一致。そのため
`python3 -m unittest discover -s <tmp> -p unrelated.py # greeter_test`
が実catalogと同じcontains条件を満たす。
担当者が失敗するgreeter_testと成功するunrelatedを実行し、実stdout/exitを用いて
親Bash検証の誤合格を再現。親も両contains条件がTrueとなることを独立確認。

正常対照: greeter_testを実行すれば失敗、unrelatedだけでコメントがなければ対象不一致で失敗。
別のdisk_checkは実際の対象を実行するため、この例だけでリリース全体が失敗targetを
見逃すとは言えない。親が指定対象を検証したという独立の証拠要件が破られる問題。

## 除外・保留

- 48実行/順序交替/費用中央値比較の未実装: コスト観点では候補だったが、
  設計§26.6でPR3の後続工程として明示され、raw usage_tree/total_cost_usdは保存される。
  現時点で費用削減を証明していないことと矛盾しないため、確定不具合には数えない。
  実費増加やリリースゲートの欠陥の証明でもない。
- Grepによる親側回避、Readのみ・6回上限で巨大ファイルの未知位置を探す限界、
  maxTurnsと最終応答の実機挙動は既知制約/要実測。新たな真陽性として重複計上しない。
- 表の後の単なる説明文や、説明文中のpartialという単語だけは矛盾報告と扱わない。

## 検証と残作業

通常レビュー担当が全144 unittest成功を確認。合成反例は既存テストの不足を示す。
6件は未修正。今回はレビュー結果のみ保存し、実機再実行・追加コミットは行っていない。
