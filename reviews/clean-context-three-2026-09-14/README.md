# クリーンコンテキスト・3観点レビューと偽陽性チェック

対象: 現行作業ツリー（HEAD `b66c13f4` + 未コミット変更）。実施日: 2026-09-14。

俯瞰・通常・敵対的の各担当を、会話を継承しない独立コンテキスト（読み取り専用サブエージェント）で起動した。既存の `reviews/`、`docs/history/`、git 履歴は根拠にせず、現行ソース・仕様・テストを確認させた。統合担当（本会話）が候補を合算・重複排除し、各候補を現行ソースへの照合・フックスクリプトへの合成入力・実 bash との対照で再確認した。

実装ソースは変更していない。Claude の課金を伴う実機呼び出しは行っていない。検証は `/tmp/tsv` の合成 fixture に対するフック直接実行と、判定器関数のオフライン呼び出しで行った。

## 統合結果

独立レビューの報告対象候補は延べ18件（俯瞰9・通常1・敵対8）。偽陽性チェックで、敵対的候補の部分例1件を除去し、1件を設計内として除外、1件の細部記述を訂正した。最終的に **P1 が5件、P2 が11件** の計16件を残した。P0 の指摘はない。

| 観点 | 独立候補 | 統合先 | 個別報告 |
|---|---:|---|---|
| 俯瞰・設計整合性 | 9 | F5, F9-F16 | [overview.md](overview.md) |
| 通常・正確性 | 1 | F4 | [normal.md](normal.md) |
| 敵対的 | 8 | F1-F3, F6-F8, 除外2 | [adversarial.md](adversarial.md) |

### F1 — P1: 同一コマンド行内のステージングで `-f`/サイズ検査を素通りできる

位置: `plugin/hooks/check-bash-read:457`・`464-469`・`746-758`。

`cp large.txt s.txt; cat s.txt` — 判定時点で `s.txt` は不存在または小さいため `cat` のオペランド検査を通るが、実 bash は `cp` 実行後に本文を出力する。統合側で実機再現: フックは pass（空出力・exit 0）、実 bash は400行を出力した。`mv`/`ln`/`tee`/`install`/`python3 -c shutil.copy` 等、reader でない書き込み側なら同型。パイプ版 `cp large s | cat s` も同じ機構で通る。

`cat large > s; cat s` は seg1 の `cat large` が deny されるため不可（実機確認済み）。文書化済みの制限（未対応 reader・コマンド置換・`<` 入力）とは別系統で、**列挙済み reader・リテラルパスの検査対象が判定時刻と実行時刻で変わる**点が未文書化。

### F2 — P1: `+=` 代入プレフィックスが `strip_vars` を抜ける

位置: `plugin/hooks/check-bash-read:422`（`^[A-Za-z_][A-Za-z0-9_]*=` のみスキップ）。

`x+=v cat large.txt`、`PATH+=:/tmp cat large.txt` は代入語と認識されずコマンドワード `x+=v` → `*)` で pass。実 bash では有効な代入プレフィックスとして `cat` が実行される（統合側で実機再現: フック pass、bash が本文400行を出力）。`V=1 cat` 形は既に対応・テスト済みの機能の欠けた形。評価側 `judge.py:830` の `bash_recovers_body` も同じ正規表現を使うため、deny 後の同形迂回は判定でも検出されない。

**偽陽性訂正**: 敵対的報告の副例 `a[0]=v cat f` は実 bash が `not a valid identifier` で拒否するため成立しない。`+=` 形のみを確定とする。

### F3 — P1: コマンドワードの brace 展開

位置: `plugin/hooks/check-bash-read:328`・`664-670`・`818-819`（展開の deny が reader アーム内に限定）。

`{c,}at large.txt` → フックは base を `{c,}at` と見て `*)` で pass、実 bash の brace 展開で `cat at large.txt` が走り本文が出る（実機再現済み。`{cat,} large.txt` も同様）。README:183 の展開 deny は「対象 reader のオペランド」に限定、README:184 の前置形リストにも該当せず未文書化。`[c]at` は cwd に `cat` が存在する条件付きの類例。

### F4 — P1: `auto-routing-boundary-50-lines` の fixture/gold 不整合で `release_eligible` が恒常不可

位置: `evals/compare/run.sh:151`・`161-163`、`evals/compare/cases.json:1151-1164`。

生成式は各関数を `def`+`return`+空行の3行で並べるため、`def task_fifty` は148行目・全体149行・**50行目は `    return 17`**（統合側で生成式を実行して確認）。ケースは「50行目に定義される関数名」を問い gold に `def task_fifty` を要求するため、正答では永遠に accuracy fail、誤答 `task_fifty` なら通る逆転した検査になっている。

`mandatory` は全カタログ（`judge.py:1983`）、`release_eligible = fails==0 and planned==mandatory`（:2128）なので、このケースが残る限り完全実行のリリース適格は成立しない。`agent_zero` 期待は149行<350行・約1.7KB<64KiBで偶然成立するのみ。

### F5 — P1: 文書化されたオフライン回帰コマンドがクリーンなチェックアウトで失敗する

位置: `evals/compare/test_runner.py:97-98`、`evals/compare/.gitignore:2`、`README.md:204`。

`committed_gold` が `fixtures/gen/gold-edit-hint.json` を無条件に `read_text()` するが、`fixtures/gen/` は gitignore 対象で `run.sh` は `RUN_ROOT` 側にしか生成しない。`git ls-files` で追跡 0 件を確認。クリーン checkout で README:204 の `python3 -m unittest discover -s evals/compare -p 'test_*.py'` を実行すると `FileNotFoundError`。`evals/run.sh:209` の部分 discover（`test_unreadable_and_model.py` のみ）は検出しない。

**偽陽性訂正**: 報告の「現ツリーでも該当ファイル不在」は誤り。生成済みの未追跡ファイルは現ツリーに存在する。クリーン checkout での失敗という本体の指摘は成立。

### F6 — P2: `check-reader-contract` がパス同一性をリテラル文字列で管理

位置: `plugin/hooks/check-reader-contract:31-36`。

`stopped` になった `/a/f` を `/a/./f` で再 Read できる（統合側で実機再現: 同一パスは deny、エイリアスは pass）。全体の `calls>=6`・3パス上限は残るため影響は per-path の stopped/retry/カーソル回避に限定。評価側は `norm_path` で正規化するため eval では検出されるが、ランタイム契約は抜ける。

### F7 — P2: judge `bash_recovers_body` が綴りとコマンド網羅で回避可能

位置: `evals/compare/judge.py:803-876`。

`sort ./big.txt`、`cat dir//big.txt`、`sed -n p x/../big.txt` は引数正規表現が `/`・`.` 前置を許さず非検出（統合側で関数を直接呼んで確認）。`tac`/`base64`/`bash -c`/`source`/`zcat`/`jq` 等の未列挙エミッタも同様。hook を通る未対応コマンド（例: `sort ./big`）との組合せで、deny 後回収がクリーン判定になり得る評価の偽陰性。

### F8 — P2: 本文検出の fixture 限定と thinking 除外

位置: `evals/compare/judge.py:281-282`・`891-951`・`1409-1420`・`1918-1938`。

分割・変形による検出回避の閾値部分（>2KiB 連続/21 連続行）は README:231 で文書化済み → 設計内。残る実装の穴: (a) `child_no_body` は `spec.fixtures` 宣言済み本文のみ照合し、fixture 外ファイルの本文は対象外、(b) `thinking` ブロックは `parent_added_text`/`leakcheck` の対象外で、本文が thinking 経由なら計測・引用検査を両方通過（usage には計上）。

### F9 — P2: `gold_confirmed` が basename のみの `confirmed:` 引用を受理

位置: `evals/compare/judge.py:649,655,664-679` vs `plugin/skills/bulk-reader/SKILL.md:78-86`（絶対パス必須・basename 引用は契約不適合と明記）。

basename が needle に含まれるため、basename だけの引用が判定を通る。契約違反の成功を許容する検証不足（静的確認済み、実機 transcript での発現は未検証）。

### F10 — P2: 子返答検査ブロックの宣言依存カバレッジ

位置: `evals/compare/judge.py:1374-1423`。

ブロックは `child_msg_max` or `child_no_body` or bulk-reader 存在時のみ起動。`writer-bounds`・`writer-verification-levels`（code-writer のみ、cap/no_body 未宣言）は `child_result_evidence` すら未検証。6委譲ケース（retry-policy・writer-bounds・writer-verification-levels・auto-large-writer・境界16k-plus・50-lines-writer）に `child_no_body` なし。`child_status` は bulk-reader 限定のため writer 返答契約（800字・status/stop_reason・形式）は全ケースで機械未検証。cases.json の delegate 宣言を統合側で走査し確認済み。

### F11 — P2: A 群 delegate モードで要求/解決モデルが未検証

位置: `evals/compare/routing_checks.py:256-258`・`279-284`、`evals/compare/cases.json`（A群は `expected_resolved_model`/`retry_policy`/`batch_invocation` いずれも未宣言、統合側で全件走査して確認）。

`sonnet` モードで haiku が起動しても A群では検出されない（`worker_attempts[].requested_model` への記録のみ）。`check-agent-model` フックが model∈{haiku,sonnet} は強制するため、残る隙間はモード別の要求/解決一致と auto の初回 haiku 順序。B群は宣言済みで fail-closed。`expected_resolved_model` の宣言値は有効化以外では参照されず、期待値は mode から導出される。

### F12 — P2: `BUILTIN_HOOKS` が同名の外来 `SessionStart:startup` フックを不可視化

位置: `evals/compare/judge.py:26`・`991-992`（payload 検査前に skip）。

README:192 が文書化する残穴は PreToolUse 通過フックのみで、SessionStart の名前衝突は未記載の追加盲点。managed/policy settings のフックが `--setting-sources ""` でも残るかは CLI 仕様依存（要確認）。

### F13 — P2: 設計 §26.5 の cases.json フィールド名が実装とドリフト

位置: `docs/2026-09-12-token-shunt-design.md:893`（`routing`/`worker_model`/`expected_agent_calls`/`required_paths` 等を規定）vs 実装語彙（`expect.<mode>`、`agent_calls_min/max`、`child_reads_once`、`expected_resolved_model`、`require_parent_tokens`）。

意味的カバレッジはあるが名称が陳腐化。`required_paths` は `routing_checks.py:117` に実装済みだが全ケース未使用（`deny_route.allow_range`、`expect.plugin` 既定も未使用の防御的語彙）。

### F14 — P2: 費用集計と 48 実行反復が設計記述とドリフト

- 設計 §26.5 は単価×usage の合計と単価出典の保存を規定 → 実装は CLI 報告 `total_cost_usd` のみ（`judge.py:479`・`2096-2124`）。README:229 は実装どおり正直に記述。
- 設計は 4件×4モード×3反復・順序交替・新しい会話を規定 → `repeat.sh` は run.sh をそのまま N 回（既定2）実行のみ。
- 設計自身が非出荷条件と明記しているため軽微だが、規定手法と実装の差分として記録。

### F15 — P2（軽微）: marketplace 説明文の誇張

`.claude-plugin/marketplace.json:13` の「Hooks block oversized Read/Bash and route to ... subagents」— 実際のフックは deny + 理由文中の案内のみで起動しない。README:5 は「自動で起動しない」と明記しており marketplace 文言のみが誇張。

### F16 — P2: `check-reader-contract` の例外捕捉が4型に限定され想定外例外は fail-open

位置: `plugin/hooks/check-reader-contract:116-117`（`OSError, ValueError, TypeError, KeyError` → exit 2）。

深さ100,000のネスト JSON で `RecursionError` → トレースバック + exit 1 を統合側で再現。PreToolUse の exit 1 は非ブロッキングなので Read が通過し契約状態は適用されない。fail-closed 方針（§306）との不一致。到達性は低い — tool_input を運ぶ harness が深いネストを生成する経路は未確認。

## 偽陽性・設計内として除外した候補

| 候補 | 再確認と結論 |
|---|---|
| `a[0]=v cat f`（敵対 F2 の副例） | 実 bash が `not a valid identifier` で拒否 → 漏洩しない。`+=` 形のみ F2 に残した。 |
| 「現ツリーでも `fixtures/gen` 不在」（俯瞰 F5 の細部） | 未追跡ファイルは現ツリーに存在。クリーン checkout での失敗のみが本体。 |
| code-writer の Read サイズ免除・契約なし（敵対 F7） | README:146 の免除表・191 の機械的切り詰めなしで明記 → 設計内。バックストップの薄さは F8/F10 に集約。 |
| 分割・変形による本文検出回避の閾値部分（敵対 F6 の一部） | >2KiB 連続/21 連続行の基準は README:231 で文書化済み → 設計内。fixture 限定・thinking 除外のみ F8 に残した。 |
| 敵対報告の「設計内」「防がれる」一覧全般 | README:182-192・設計 §15 と照合して一致を確認（`<` 入力、`$''`、コマンド置換、未列挙 reader、未知パイプ末尾 fail-open、前置形、`<(...)` 拒否、引用/エスケープ正規化、cd 追跡、heredoc、fd/tee 側経路、head/tail 全形態、入力堅牢性、reader 契約状態遷移、judge の fail 方向）。 |

## 検証と限界

- F1/F2/F3/F6/F16 は統合担当がフックへ合成 stdin を与えて pass/deny を実行確認し、実 bash の意味論も対照確認した（`/tmp/tsv`、400行/800バイトの合成ファイル）。F7 は `bash_recovers_body` を直接呼んで非検出を確認。F4 は生成式の実行・`cases.json`・`judge.py` のゲートを照合。F5 は `git ls-files` で追跡 0 件を確認。F9-F15 は静的照合。
- 敵対的レビューは静的解析のみ。読み取り専用のため実テストスイートの走行は各担当未実施。`evals/run.sh`・`unittest discover` の現ツリー実行は本統合でも未実施。
- 有料のモデル実行、全ケースの新規実機比較、削減率の測定は実施していない。F9-F11 の実機発現は transcript 依存で未検証。
- F1-F3 の実害化にはモデルによる意図的回避が前提。Grep 本文・`bash -c`・`<` 入力など文書化済みの迂回が既に存在するため、本指摘は「実装済み機構の未文書化の穴」としての意義が主である。

修正の優先順は、リリース経路を壊す F4/F5、主要機構の未文書化バイパス F1/F2/F3、続いて評価器の盲点 F6-F11、契約の fail-open F16、文書ドリフト F12-F15。いずれも今回の作業では修正していない。
