# 評価器再検証

独立検証。対象は現行コードと `docs/2026-09-12-token-shunt-design.md` §§1–15・§26 および `README.md`。`reviews/` と `docs/history/` は根拠に使っていない。優先度は常時ゲート破壊の証拠があるものだけ P1、それ以外は P2。

## 各候補

### 1 — TRUE POSITIVE（P1）

- 再現
  - `Transcript.parent_added_text`（`evals/compare/judge.py` 302–312 行）は親 assistant を `("a", message.id)` の first-wins で切り、後続イベントの `context_text`（`tool_use.input` / `text`）を捨てる。thinking ブロックは `context_text` に入らないため、先に来る thinking イベントは空文字を採用する。
  - 現行 CLI の stream-json は同一 `message.id` を thinking → tool_use に分割する。保存ログ 141 本のうち、親 assistant の同一 id 分割は 274 件、thinking→tool_use は 218 件。例: `evals/compare/tmp/runs/run.5iqYfCeg/transcripts/auto-one-line.auto.jsonl` の `msg_011Cf19ivkUwCe5gfeVAWw46` は thinking の直後に同一 id の `Agent` tool_use。Agent prompt（964 バイト）は現行 `parent_added_text` に含まれない。
  - 合成対照（`/tmp`）: 同一 id 分割では `parent_added_utf8_bytes=27` で prompt 欠落、別 id 対照では 739 バイトで prompt を含む。`leakcheck` は同一 id で rc=1（clean = 漏れなしと誤判定）、別 id で rc=0（漏れ検出）。`tool_uses` 自体は first-wins しないので path_ok の Agent 検出は残る。
  - 実ログを同一 id のブロック結合で再計算すると、132 本中 71 本で `parent_added_utf8_bytes` が過小。`run.xv9H1gDW` の `compare-bulk-facts` は現行 isolation 合格（sonnet 17181 < direct 20352）だが、結合後は sonnet 21163 > direct 20952 で不合格。隔離ゲートの偽合格が実ログで出る。
- 仕様照合
  - §13 指標: 親 assistant の `tool_use.input`（Agent prompt、Write content、Bash command 等）を含め、「同一 message id は重複計上しない」。これは同一本文の二重加算禁止であり、後続ブロックの破棄ではない。
  - README: 「親に追加された内容量には、Agentのプロンプト、Writeの本文、Bashのコマンドなど、親が出したツール引数も含めます。」
  - `isolation_ok` は §1.1 / §13 のリリースゲート。`leakcheck`（1665–1681 行）も `parent_added_text()` を見る。
- 判定理由
  - 対象ハーネスでは常時発生するストリーム分割に対し、隔離バイトと writer 漏れ検査が `tool_use.input` を落とす。実装が現行契約を満たさない。

### 2 — TRUE POSITIVE（P2）

- 再現
  - `Transcript.__init__`（158–159 行）は親 `type=result` の最後の 1 件だけを保持し、`metrics()`（337–360 行）の `parent_input_tokens` / `parent_output_tokens` / `usage_parent` はそれだけを読む。
  - 指定ログ `evals/compare/tmp/runs/run.5iqYfCeg/transcripts/auto-bulk-facts.auto.jsonl` に親 result は 3 件。
    - #87 `num_turns=5`: uncached 8 / cache_read 114810 / cache_creation 10275 / output 1355
    - #88 `num_turns=2`: 4 / 68994 / 2480 / 1113
    - #89（judge が採用）`num_turns=1`: 2 / 36492 / 947 / 97
  - 3 件の `result.usage` 合計 input は 234012。親 assistant を `message.id` で重複排除して足しても 234012。judge の `parent_input_tokens` 合計は 2+36492+947=37441。最終 result は累積ではなく区間値（後ろほど小さい）。
  - 3 件の `modelUsage` は同一（call 全体、子 haiku を含む）。`usage_tree` 側の二重計上は起きていない。
- 仕様照合
  - §13: `parent_input_tokens` は「親の累積 input」。`usage_parent` は「最終 `result.usage`」と書きつつ「assistant を足すなら message id で重複排除」。`parent_output_tokens` も最終 `result.usage`（per-step の output はプレースホルダ）。
  - §26.5: 必須観測は課題単位の累積（再試行・検証を含む）。`modelUsage` に含まれる子を親 input に混ぜてはならない。
  - このログでは最終 `result.usage` は累積ではない。last-only を「すでに累積」とみなす前提は現行 CLI 出力と一致しない。
- 判定理由
  - 必須の親トークン観測が区間値で過小になる。常時の製品破壊ではなく測定契約の破れなので P2。修正は `modelUsage` を親 input に足さないこと。

### 3 — FALSE POSITIVE

- 再現
  - `evals/compare/run.sh` 525–532 行: `rc != 0` かつ transcript が空のときだけ即 fail。非空なら 533 行コメントどおり judge に渡す。
  - 合成: 空 + exit 17 は空 transcript 分岐。成功形 3 イベント + exit 17 は judge へ進み、`auto-small-files` 相当 spec で `verdict=pass`。
  - プローブ側は別契約。`check_probe_run`（239–244 行）は CLI 非 0 を環境失敗にし、`test_runner.py` も probe の exit 17 を `selected_run_valid=false` で止めている。
  - judge は result 欠落（862–867 行）と `is_error`（868–873 行）を fail にする。途中打ち切りの非空ログは通常ここで落ちる。
- 仕様照合
  - §13 の skip/fail は `claude` 不在が skip、存在時のロード/隔離/必須ケース失敗が fail。ケース合否は transcript の accuracy / path_ok / isolation_ok。
  - README が「CLI の終了コード」を必須としているのは事前プローブ。ケース本文のプロセス rc=0 は合格条件に書いていない。
- 判定理由
  - 非空ストリームを judge する分岐は仕様の skip/fail 区分と一致する。exit 17 でも本文が契約を満たせば合格、満たさなければ judge が fail。追加の製品バグではない。

### 4 — TRUE POSITIVE（P2）

- 再現
  - `evals/run.sh` は `set -u` のみ（`set -e` なし）。77 行 `done < <(jq -c '.[]' hook-evals.json)`、92 行は `bash-hook-evals.json`。process substitution 内の jq 失敗は親を落とさない。
  - `/tmp` にツリーをコピーし両 JSON を `not-json` に置換して実行。jq は exit 5。カタログケース id は 1 件も出ず、特殊ケース 14 件だけが走り `pass: 14  fail: 0`、`run.sh` は exit 0。
- 仕様照合
  - §13: `evals/run.sh` が必須フックケース（減らさない）を stdin JSON → 決定/exit で検証する。カタログが読めないと必須ケースは未実行。未実行のまま exit 0 はゲート通過。
- 判定理由
  - 不正カタログで必須ケースを黙って 0 件にし、フック eval が成功扱いになる。破損時だけの穴なので P2。

### 5 — SPEC GAP

- 再現
  - `bash_recovers_body`（653–664 行）は path 言及かつ `cat|head|tail|less|more`、または `|` と `grep|awk|sed|cut|python|dd|xargs`。親 Grep ツールは見ない。`deny_bypass`（1119–1131 行）は成功 Read と上記 Bash のみ。
  - 合成: 親 Read deny → `Grep output_mode=content` で本文 → Agent。`deny_bypass` / `deny_route` 付き spec で `verdict=pass`。対照の `cat /abs/big.txt` は `deny_bypass` fail。
- 仕様照合
  - §11.8: Grep `output_mode=content` はフック対象外なので「契約と eval で担保する」。
  - §26.5 の deny 後迂回: ずらした連続 Read と引用外パイプ。制御 transcript は limit=350 連続 Read と cat パイプ。Grep ツールは列挙していない。
  - §15 / §4 / README: Grep 本文出力は既知のフック穴で封鎖しない。編集経路（§11.6、`auto-edit-grep-location`）は短い Grep を要求する。
- 判定理由
  - 現行 eval は deny_bypass で Grep 本文回収を捕るとは書いていない。実装は §26.5 の列挙と selftest に一致する。§11.8 の「eval で担保」と §26.5 の検出対象が食い違うのは仕様側の隙間。分析ケースの Grep content を fail にするなら仕様の検出対象を先に固定する必要がある。編集 Grep を一律 deny_bypass に足すと §11.6 と衝突する。製品フックのバグではない。

### 6 — TRUE POSITIVE（P2）

- 再現
  - `quote_leak`（733–754 行）は fixture 本文が `None` なら `continue`（検査スキップ）。
  - 合成: 欠落 fixture + 3000 バイト 1 行引用は `quote_leak` 非検出。`child_no_body` spec で judge は pass（`child_no_body=true`）。22 行の非空行はフォールバックで fail。読める 3000 バイト 1 行は `>2KiB contiguous quote` で検出。
  - `leakcheck` は対象が読めないと rc=2（1670–1675 行）。`run.sh` 548–555 行は `leak_rc==1` 以外を writer 漏れ/証拠なしで fail にする。writer 側は判定不能を pass にしない。
- 仕様照合
  - §13 子→親: 4000 字超、fixture の 20 行超または 2KiB 超の連続引用は fail。1 行 minify（`compare-one-line`）は 21 行フォールバックでは拾えない。
  - §26.5「判定不能は pass にしない」の文は deny_bypass 段落。`leakcheck` はその方針。`child_no_body` は同じ本文隔離契約（§3.4 / §13）なのに、fixture が読めないと 2KiB 検査を飛ばして pass する。
- 判定理由
  - `child_no_body` は `leakcheck` と違い判定不能を pass にする。1 行 70KiB fixture ではフォールバックが無効。本文隔離ゲートの穴。実ランで path が解決できる限り潜伏するので P2。

## 修正すべき確定リスト（file:line + 最小修正方針）

1. **P1** `evals/compare/judge.py:302-312`（`parent_added_text` の `("a", id)` first-wins）。同一 `message.id` は後続を捨てず、assistant イベントの `context_text`（text + `tool_use.input`）を結合する。空の thinking 先行を本文とみなさない。`leakcheck`（1669 行）は同じ関数を使うので追加変更は不要。
2. **P2** `evals/compare/judge.py:158-159` と `337-360`。親 `result` が複数で各 `usage` が区間値（後段が小さく、id 重複排除した assistant input と合計が一致）なら、最終件だけでなく親ループ分を合算する。input は assistant `message.id` 重複排除でもよい（§13）。output は per-step プレースホルダを足さず result 側を合算する。`result.modelUsage` は子を含むので `parent_input_tokens` に混ぜない。
3. **P2** `evals/run.sh:77` と `92`。ループ前に `jq -e . hook-evals.json` / `bash-hook-evals.json` を必須化し、失敗なら非 0 で終了する。process substitution の jq 失敗を成功としない。
4. **P2** `evals/compare/judge.py:747-748` と `1157-1167`。`child_no_body` 対象 path の本文が 1 件も読めないときは pass にしない（`leakcheck` の rc=2 と同じ判定不能）。21 行フォールバックだけに頼らない。
