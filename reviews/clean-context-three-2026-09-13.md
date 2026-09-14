# クリーンコンテキスト・3観点レビュー（俯瞰・通常・敵対的）と偽陽性チェック

対象: `b66c13f4` の現行作業ツリー（未コミット変更を含む）。実施日: 2026-09-13。

俯瞰・通常・敵対的の3担当を、会話を継承しない別コンテキスト（サブエージェント）で並行起動した。各担当には `reviews/`、`docs/history/`、git履歴を根拠にしないよう指示し、現行ソース・設計書・READMEのみを確認させた。独立レビュー後、統合担当が候補を重複排除し、全指摘を現行コードでの静的照合とフック・テストの実実行で再検証した。

**レビュー中のツリー変動:** レビュー実施中（23:37〜23:51 JST）に `plugin/hooks/check-reader-contract`（新設）・`hooks.json`（5フック化＋PostToolUse/PostToolUseFailure 登録）・`check-jq`（python3 依存の警告追加）・`judge.py`・`run.sh`・`cases.json`・`build-zip.sh`・`plugin.json`・bulk-reader 系 SKILL/agents が変更された。敵対的担当は主に変更前、俯瞰・通常担当は変更後のツリーを確認した。偽陽性チェックは全て**変更後の最新状態**で実施した（対象の `check-bash-read`・`check-file-size`・`check-agent-model`・`doctor.sh` は変動前後で同一）。なお通常担当は指示に反して既存 `reviews/` の記録を一部参照していた（「以前の作業の記録として扱った」と明言）ため、完全なクリーンコンテキストではない点を記録する。各指摘は統合側で現行コードから独立に再確認した。

## 統合結果

独立レビューの報告対象候補は延べ7件（俯瞰2・通常2・敵対的4、うち重複1）。敵対的担当の「未検証の疑念」1件を統合側の計測で確定させ、**最終的に8件**を残した。P1が1件、P2が4件、P3が3件。

| # | 観点 | 重要度 | 内容 | 偽陽性判定 |
|---|---|---|---|---|
| F1 | 敵対的 | P1 | 先頭リダイレクトで Bash 検査を完全迂回 | 真陽性（実測再現） |
| F2 | 敵対的（未検証→統合で確定） | P2 | `>` ごとの前置再字句化で超線形、~250個で10sタイムアウト→fail-open | 真陽性（実測） |
| F3 | 俯瞰＝通常（重複統合） | P2 | `test_reader_contract.py` が全実行経路から漏れ | 真陽性 |
| F4 | 敵対的 | P2 | 2箇所の deny メッセージに `token-shunt` 無し、judge の帰属判定と不整合 | 真陽性 |
| F5 | 敵対的 | P2 | judge.py の Read パス照合が事実上リテラル一致 | 真陽性 |
| F6 | 通常 | P3 | check-jq の python3 警告文が実挙動と不一致＋reader-contract の非 object 入力耐性 | 真陽性（軽微） |
| F7 | 俯瞰 | P3 | 配布 README が「4フック」のまま（実装は5フック） | 真陽性 |
| F8 | 敵対的 | P3 | doctor.sh が記録ファイル書込み失敗を検出せず「recorded」を表示 | 真陽性（軽微） |

## F1 — P1: コマンド先頭のリダイレクトで Bash フックの読み取り検査を完全に迂回できる

位置: `plugin/hooks/check-bash-read`（`strip_vars` が `VAR=` 前置のみ除去 :330-335、`check_stage_full` :557-565、パイプ末尾ディスパッチ :672-698、単一コマンド :706-713）。

`tokenize` は先頭トークンを redirect 種別（`2>` 等）として生成するが、`base=${VTOKS[0]##*/}` はそれを除去しないため `base='2>'` となり `case` が既知 reader に一致せず `*)` で pass。統合側で `plugin/hooks/check-bash-read` に実 JSON を流して再現した:

- `2>/tmp/err cat large-80k` → **pass**（実 bash は本文を stdout＝親へ出力）
- `1>&2 cat large-80k` → **pass**（本文は stderr＝親へ）
- `<<EOF cat large-80k` → **pass**（`<` は演算子として字句化されず先頭ワード化）
- `cat large-80k | 2>/tmp/err cat` → **pass**（パイプ末尾の `2>f cat` も同機構）
- `echo x; 2>/tmp/err cat large-80k` → **pass**（複合区間でも同じ）
- 対照: `cat large-80k` は deny、`>f cat large-80k`（stdout 前置）は CLEAN_GT で pass — ただし後者は本文がファイルへ行くため pass が正しい

README.md:182-183 の制限事項は「先頭トークンを変えるグループ化・制御構文・wrapper コマンド」と「中置の入力リダイレクト `<`」を列挙するが、**単純コマンド内の前置リダイレクトはどちらにも該当しない**（`2>f cat f` は `cat f` をそのまま実行する記法であり wrapper ではない）。設計 §10・§15 にも対応記述なし。カタログ `bash-hook-evals.json` にも先頭リダイレクトのケースは存在しない。通常担当は README:182 を根拠に除外候補としたが、統合側の文言照合で「網羅しない」列挙の対象外と判断し、**真陽性**とした。`evals/run.sh` の deny 期待は reason の `bulk-reader` 含有を要求するため、この系統の deny ケースは現状カタログに追加しても誤 FAIL する（F4 と同源）。

修正方向: `base` 決定前に先頭の redirect トークンとそのターゲットを `VAR=` と同様にスキップする（`<`/`<<` も演算子として認識する必要がある）、または `VTOKS[0]` が redirect/operator 種別なら fail-closed で deny。

## F2 — P2: `>` ごとの前置再字句化が超線形で、~250個のリダイレクトで10sタイムアウト→fail-open

位置: `plugin/hooks/check-bash-read` `scan_ops`（:267-269。各 `>` で `tokenize "${s:0:fdpos}>"` と前置全体を再字句化＋TOKS 配列の保存・復元コピー）。

敵対的担当が未検証とした二次計算量の疑念を統合側で計測（`cat small` に `> /dev/null` を n 個連結）:

| n | 実測 |
|---:|---|
| 50 | 1.95s |
| 200 | 8.45s |
| 800 | >20s で未完了（kill） |
| 3000 | >4分で未完了（kill） |

`hooks.json` の timeout は10s、タイムアウトした PreToolUse は公式に fail-open（設計 §15 も認知）。`cat large 2>/dev/null 2>/dev/null …`（fd 付き `>` も同じ再字句化を踏む）のような ~2KB の入力でフックが殺され、実 bash は大きなファイル本文を stdout へ流す。設計 §15 の「遅い FS で予算チェックより先に timeout」という既知限界とは別経路（小さい入力に対するパーサ自身の計算量）であり、文書化された制限とは言い切れない。ただし実運用でモデルが数百個のリダイレクトを自然に出力することは稀で、敵対的入力前提の問題。

修正方向: `>` ごとの前置再字句化を廃し、直前トークンを保持する走査で fd 判定する等の線形化。

## F3 — P2: `test_reader_contract.py` が文書化された全実行経路から漏れている

`evals/test_reader_contract.py`（8テスト: 6試行予算・拒否後半減・pending 直列化・3パス上限・並列プロセス状態共有）は新設フック `check-reader-contract` の回帰を検証するが、実行経路が存在しない:

- `evals/run.sh:181-222` の個別起動リストに無い（symlink/cd/scan-budget/bash-operational/review/harness-input/model/archive の8群はある）
- README.md:202・docs/distribution/README.md:73 の `python3 -m unittest discover -s evals/compare -p 'test_*.py'` は `evals/compare/` 配下のみ再帰し `evals/` 直下に届かない
- リポジトリ内の `test_reader_contract` 参照はテスト自身のみ。CI 設定なし

統合側で実実行し 8 テスト全パスを確認（実行可能で未配線）。worker の Read 強制契約という中核機構の退行が、文書化された検証を全通しても検出されない。俯瞰・通常の両担当が独立に同一指摘（重複統合）。

修正方向: `evals/run.sh` の回帰ブロックに `python3 -B "$ROOT/evals/test_reader_contract.py"` を追加。

## F4 — P2: 2箇所の deny メッセージに `token-shunt` が無く、判定ハーネスの帰属判定と不整合

位置: `plugin/hooks/check-bash-read:563`（cd 未解決: `"A preceding cd has an unresolved destination or redirection. Use absolute file paths in a separate Bash call."`）と `:625`（プロセス置換: `"Process substitution cannot be checked safely. Use separate commands with literal file paths."`）。他の deny は全て `token-shunt`/`bulk-reader` を含むのに対し、この2件だけ含まない。

影響（現行 judge.py で確認）:

- `foreign_hooks`（judge.py:979-980）は非空ペイロードに `token-shunt` を含まない応答を `PreToolUse:Bash(non-token-shunt output)` として `fail("foreign_hooks")` に追加 → 正当な自プラグイン deny が外来フック混入として誤判定される
- `ts_deny_payload`（judge.py:1006）は reason に `token-shunt` が無い deny を無視 → `deny_route`/`ts_hook_denies` 系チェックがこの deny を見落とす
- `evals/run.sh` の `check_expect deny` は reason の `bulk-reader` 含有を要求（:71-75）→ この2系統を通るカタログケースは追加すると誤 FAIL（現カタログに該当ケースは無く、カタログ上の影響は潜在）

設計 §13 は deny の帰属を「reason 内の `token-shunt` 含有」に依存すると明記しており、実装がその前提を破っている。修正方向: 両メッセージに `token-shunt` を含める（行為規範の文言は維持可）。

## F5 — P2: judge.py の Read パス照合が事実上のリテラル一致

`norm_path`（judge.py:492-493）は `rstrip("/")` のみで、`.`/`..`/`//`/相対→絶対を解決しない。`use_targets_path`（:733-739）はこの文字列一致で、以下に使われる:

- 禁止系（`parent_no_full_read` :1237、`deny_bypass` :1326）: `/abs/./gen/x.py`、`//abs/x.py`、`/abs/x/../y`、`cd` 後の相対パスでの成功 Read を検出漏れ → 違反見逃しで **false PASS**
- 必須系（`parent_reads` :1228、`parent_targeted_read` :1253）: 別名表記の正規 Read を数えない → **false FAIL**

フック側は `[[ -f "/abs/./gen/x.py" ]]` で同一ファイルを正しく検査し bounded Read は成功し得るため、deny 済みパスへの別名 Read がハーネスを潜る。比較として `writer_use_matches`（:770 付近）は `tool_cwd` を join しており非対称、Bash 側 `bash_mentions_path` は basename 一致で補助的に捕捉するため Read 側だけが弱い。

修正方向: Read/Edit の `file_path` を `spec["tool_cwd"]` 基準で `abspath`→`normpath`（必要なら `realpath`）して比較する。

## F6 — P3: check-jq の python3 警告文が実挙動と不一致＋reader-contract の入力耐性の不統一

- `plugin/hooks/check-jq:19-21`: 「Python 3 is required for the bulk-reader runtime contract. **Worker Reads remain blocked** until it is available.」— しかし python3 不在時、shebang `#!/usr/bin/env python3` の `check-reader-contract` は起動自体に失敗し非0終了する。exit 2 以外は非ブロッキングなので worker の Read は**ブロックされず、契約未適用のまま通過**する（`check-file-size` は worker を allowlist で pass）。警告文が実際の保証を誇張している。
- `plugin/hooks/check-reader-contract:82`: 有効 JSON の非 object 入力（`[]`・`"x"`・`null`）で `event.get` が AttributeError となり :110-112 の捕捉範囲（OSError/ValueError/TypeError/KeyError）を外れて exit 1（非ブロッキングエラー）。統合側で実実行して確認。`check-agent-model` は exit 2、Read/Bash フックは黙って pass と、同一の不正入力クラスで3挙動が不統一。実ハーネスは常に object を送るため実害は限定的。

## F7 — P3: 配布ドキュメントが「4フック」のまま

`docs/distribution/README.md` は :13「4つのフックに実行権限」、:21-28 の ZIP 構成に `hooks/check-reader-contract` が無い、:30「4つのフックにUnixの実行権限」「manifestと同じルートに4フック」。一方で実装側は5フックに更新済み: `build-zip.sh:10,48,75`（chmod・Python・zipinfo 検証すべて5本）、`evals/test_build_zip.py:12`、`judge.py:24`（TS_HOOKS）、`hooks.json`（3イベント登録）。文書だけが取り残されたドリフト。

## F8 — P3: doctor.sh が記録ファイル書込み失敗を検出しない

`scripts/doctor.sh:219-235`: `set -u` のみ（`-e` なし）で、`mkdir -p` や `{ ... } > "$record"` が失敗しても :235 の `recorded probed CLI version in %s` が無条件表示される。診断出力の信頼性のみの問題でリリース証拠に直結しない。

## 偽陽性・仕様内の制限として除外した候補

| 候補 | 再確認と結論 |
|---|---|
| `cat <f`（中置入力リダイレクト）、`cat < f` | README:183・設計 §15 で既知の穴として明示。除外 |
| `>f cat f` 等の stdout 前置リダイレクト | 誤検出に見えたが実 bash では本文がファイルへ行く。`is_isolating_target` 経由で正しく pass。除外 |
| 中間 `cd` 後の相対パス評価（`echo x; cd d; cat f`） | README:185「他のコマンドの後の cd」で文書化済み。除外 |
| `$(...)`・バッククォート内 reader、未知末尾コマンドのパイプ、wrapper/制御構文・グループ化 | README:180-182・設計 §15 で意図的 fail-open / 網羅外。除外 |
| 逐次 targeted Read（offset ずらし） | §15・README:187 で明示＋eval の `deny_bypass` で二層検出。除外 |
| `tool_input.agent_type` なりすまし | 両フックともトップレベルのみ参照。`run.sh:112-118` の spoof テストで deny 確認。除外 |
| `check-agent-model` 各エッジ（model 欠落/null→deny、非対象 agent→pass、非 object→exit 2） | 実実行で仕様どおりを確認。除外 |
| `Agent\|Task` マッチャが正規表現として解釈されるか | 公式フック仕様はマッチャの `|` 交互を許容（`Edit\|Write` 等）。除外 |
| 非通常ファイル（fifo・/dev/zero・procfs の st_size=0） | `-f` 通過は §8「ツール側のエラーに任せる」。バウンドスキャンが実バイトを数えるため安全側。除外 |
| worker 契約の機械的強制でない部分（最終メッセージ品質等） | §15「契約ベースで script 境界ではない」。除外 |
| doctor の live 項目が unconfirmed でも exit 0 | jq 欠落/Bash<4 のみハード失敗の意図明記。除外 |
| `test_reader_contract` 以外の compare テストが run.sh で走らない | README が discover コマンドを別途案内する意図的分離。除外 |
| 複合コマンド中の `head`/`tail` が全文閾値判定 | §10-4 の規定どおり（複合では早期通過を使わない）。除外 |

## 検証と限界

- F1・F2・F6 を hook 実実行・計測で再現。F3 はテスト実実行（8テスト全パス）と全経路の grep で確認。F4・F5・F7・F8 は現行コードの静的照合で確認。
- 未検証のまま残す項目: `check-reader-contract` が依存するペイロード（`agent_id`/`session_id`/`tool_use_id` のトップレベル供給、`tool_response.file.{startLine,numLines,totalLines}` の形状、`PostToolUseFailure` の発火有無と PreToolUse deny との関係）は実機 CLI 依存で静的確認不能。`agent_id` 未供給なら worker Read が全て exit 2 で止まる（fail-closed だが委譲経路は機能停止）。PostToolUseFailure が PreToolUse deny 後に発火しなければ `pending` 残留で以後の Read が連続 deny となる。実機比較評価（費用を伴う）は未実施。
- 通常担当が既存レビュー記録を一部参照した点、およびレビュー中のツリー変動を踏まえ、各指摘は統合担当が現行コードから独立に再検証した。
- `claude --version` は 2.1.270。有料のモデル実行・実機比較評価は実施していない。

修正の優先順: 強制機構の迂回である F1・F2、リリース判定の信頼性に関わる F3〜F5、文書・診断の正確性である F6〜F8 の順。
