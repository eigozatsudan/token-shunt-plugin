# 通常レビュー

## 範囲と方法

現行ワーキングツリー（HEAD `cb1ab7c94952df128aa9d171217177390b4a151e`）を、設計正本 `docs/2026-09-12-token-shunt-design.md` の §1–15 と §26 に対して静的に突き合わせた。§27 は所見リストとして使っていない。`reviews/`・`docs/history/`・git log / blame / コミット文は読んでいない。

対象は指示どおり、Read/Bash/jq フック、`hooks.json`、両スキル、両 named agent、比較判定器（`judge.py` / `flow_checks.py` / `routing_checks.py`）、`cases.json`、`evals/run.sh`、README、および上記設計節である。

アルゴリズムとして追ったのは次である。

- PreToolUse の通過（空 stdout・`permissionDecision` なし）と deny JSON、jq 欠落時の fail-closed、worker allowlist の完全一致
- Read: 全文両閾値以下の早期通過、`limit` 欠落は全文、`limit=1` を含む区間バイト判定、走査予算、除外拡張子
- Bash: 引用付き演算子スキャン、パイプ末尾コマンド、複合セパレータ先行、リダイレクト早期通過、先行 `cd`、`head`/`tail` の行/バイト解釈
- bulk-reader の 3 パス 1 起動、領域 1 回、トークン上限拒否後の連続非重複継続、maxTurns 6
- auto の Haiku 初回と許可理由だけの Sonnet 1 回、総起動 4
- deny 後の委譲、親による連続 Read / パイプ回収の path_ok 検出
- code-writer の参照必須・非 Write、親検証、minimal / syntax / requirements の区別

検証はオフラインのみ。`python3 -B -m unittest discover -s evals/compare -p 'test_*.py'`（152 件）と `evals/run.sh`（フック必須ケース + 回帰、pass 110 / fail 0）を実行した。比較 eval の live Claude API（`evals/compare/run.sh`）は走らせていない。フックは既存の stdin JSON ケースで間接的に行使した。実装・テスト・git 状態は変更していない。

## 確認した不具合

本レンズでは、現行仕様の意図アルゴリズムに対する実装欠陥を確認しなかった。P1 / P2 / P3 ともに 0 件である。

スキル本文は指示であり機械強制ではない、Grep / sed / python / `@file` は封鎖しない、呼び出し横断の蓄積は検出しない、費用削減は未証明、という文書化済み限界は、実装が契約と矛盾していない限り不具合に数えていない。

## 不具合としない観察

Read フックは §9 の手順どおりである。allowlist はトップレベル `agent_type` の完全一致のみ（`plugin/hooks/check-file-size` 128–134 行）。素の `bulk-reader` と Explore はサイズゲート対象のまま。全文が両閾値以下なら `offset`/`limit` を見ずに通過し、ファイル超過後の `limit=1` は `range_scan` に落とす。`limit=1` 例外は置いていない。走査は `head -c` で予算+1 バイトに閉じ、判定不能は deny する。通過時に `permissionDecision: "allow"` は出さない。

Bash フックは §10 の判定順を守る。複合セパレータをパイプ／リダイレクト早期通過より先に処理し、パイプは末尾 basename で決める。末尾が `grep` 等なら通過、`cat`/`tee`/`less`/`more` なら各段の明示入力を全文閾値で見る、`head`/`tail` は解釈できる `-c C`（`C ≤ MIN_BYTES`、stdin のみ）だけ通過する。`tee` の引数は入力として検査しない。`args: []` は exec form であり、インストールパス空白による spawn 失敗は `bash -c "$command"` を仮定せず、本レビューでは不具合にしていない。

`plugin/hooks/check-bash-read` 394–477 行付近は、パイプ途中段が stderr 等へ漏れる場合に追加の全文判定を行う。仕様 §10-4 は「入力元の推測やパイプ全体の走査はしない」と書いており、これは仕様文面より広い fail-closed である。必須通過ケース（`cat large | head -c 100` 等）は維持される。目的（親への本文流入防止）には沿うため、アルゴリズム破壊とは見ない。

bulk-reader の契約単位はパスではなく領域である。スキルと agent は、トークン上限拒否に加え、成功結果が渡された EOF より前で止まった場合も最終返却行の次から連続継続する。仕様 §12 の「拒否した場合に限り」より実務寄りだが、README と判定器（`routing_checks.py` の返却行ラベル）が揃っており、重複再 Read と飛び読みは fail にする。これは 2026-09-13 の領域契約の実装であり、1 パス 1 Read の旧文への回帰ではない。

判定器はファイルが存在するとき、要求範囲を完遂した targeted Read のあとに残りの行へ進む連続分割も許可しうる（`incomplete = returned[-1] < total_lines`）。「まず全文 Read して拒否されてから分割」はスキル指示であり、判定は重複とカーソル連続を見ている。仕様 §26.5 の「各領域 1 回・起動あたり最大 6」と矛盾しない。

再試行判定は auto のみ Sonnet 1 回、許可理由の短文、同一パス集合、先行 worker 結果の後、resolved model 照合、resume 禁止、総起動 ≤ 4 を機械検査する。固定 haiku/sonnet の再試行は落とす。writer 検証は親 Bash の実行証拠と、artifact 単位の `verification:` / `status:` を分け、構文成功だけの complete を拒否する。`python3` と `unittest discover` は仕様例の `python -m unittest <target>` と文言は違うが、本文を stdout に出さず親が検証する意図は同じである。

スキル非遵守は文書どおり機構欠陥ではない。判定器は領域契約違反（重複・飛び）を path_ok fail にするので、遵守の観測手段はある。

## 検証

- `python3 -B -m unittest discover -s evals/compare -p 'test_*.py'`: 152 tests, OK
- `evals/run.sh`: pass 110, fail 0（必須フックケース、jq 欠落、symlink/cd/走査予算/Bash 操作回帰、marketplace、zip 実行ビット）
- フック 3 本は Unix 実行ビット付き。`hooks.json` は仕様の exec form（`args: []`）
- live Claude API は未実行。経路の実機合格は本レビューの証拠に含めていない
