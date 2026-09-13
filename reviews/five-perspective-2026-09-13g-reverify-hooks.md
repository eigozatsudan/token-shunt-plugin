# フック再検証

検証対象: HEAD `cb1ab7c94952df128aa9d171217177390b4a151e`。正本は `docs/2026-09-12-token-shunt-design.md` §§1–15・§26 と `README.md`。実験は `/tmp/token-shunt-reverify-hooks-20260913g` へフックをコピーし、JSON stdin で実行。同一 JSON を直接実行 / `bash --noprofile --norc ./check-bash-read` / `bash --noprofile --norc -c './check-bash-read'` で流し、stdout バイトは全ケースで一致。対象コマンドは `bash --noprofile --norc -c` でも実行し、実 stdout バイトを計測した。ライブ Claude API は使っていない。

## 各候補

### 1 — TRUE POSITIVE
- 再現
  - 40 バイト行 + LF を 2000 回、末尾に改行なしの `critical_marker=present` を置いた 82,023 バイトのファイル。
  - `wc -lc` → `2000 82023`。Python `open(rb)` 反復（`evals/compare/routing_checks.py` の `_line_count` と同じ）と `awk END{print NR}` はともに **2001**。
  - 子が供給 EOF=2000 まで読んだ場合: `last_returned < supplied_eof` は false、`last_returned < logical` は true。最終行は継続対象にならない。
  - `plugin/skills/bulk-reader/SKILL.md` 51 行は委譲確定後に `wc -lc` を取れと書き、107–108 行は「supplied EOF より前で終わった成功結果は連続分割せよ」と書く。`plugin/agents/bulk-reader.md` 21–23 行は全文拒否後の初期 `limit` を **supplied remaining line count の半分** にする。
  - 判定器 `routing_checks.py` 49–55 行は実ファイルを開き、プロンプト中の行数は使わない（50 行コメント: "never line counts asserted in agent prompts"）。`_returned_range` は実 `total_lines`（2001）と比較する。`incomplete = returned[-1] < total_lines` は継続を**許可**するだけで、最終行まで読んだことは要求しない（`test_answer_can_stop_before_eof`）。供給 EOF に従って 2000 で止めた子は評価器では落ちない。
- 仕様照合
  - §11: 委譲プロンプトへ各パスのサイズと行数を渡す。取得手段は「§26.2 のサイズ判定で委譲を確定した後に取得する `wc -lc` の値」。
  - §12: Read が全文拒否したとき、親が渡した行数から連続・非重複に分割する。
  - §8.6: 行は `\n` で分け、「最終行に `\n` が無ければ付けない」が、その未終端最終行自体は 1 行として数える（`range_scan` / awk `NR` と同じ）。
  - §4 / §15 に「ファイルは LF で終わらねばならない」制限はない。
- 判定理由
  - 実装は §11 のコマンド名 `wc -lc` には従っている。しかし継続契約の行数は Read が番号を振る論理行（§8.6 と同じ）でなければ、全文拒否後の分割が最終定義を落とす。POSIX `wc -l` は改行文字数であり、未終端最終行を数えない。
  - スキルが供給 EOF を停止条件にし、エージェントが供給残行数から `limit` を切るため、フック本体ではなく **委譲メタデータが現行の継続契約を満たさない**。既知の限界でもない。

### 2 — FALSE POSITIVE
- 再現（`large-80k.txt` = 81,920 バイト。フック stdout は `--noprofile --norc` 経由でもバイト一致）

  | コマンド | フック | `bash --noprofile --norc -c` stdout |
  |---|---|---|
  | `cat large-80k.txt` | deny（289 バイト JSON） | 81920 |
  | `cat <large-80k.txt`（密着） | **pass**（空 stdout） | **81920** |
  | `cat < large-80k.txt`（空白） | deny | 81920 |
  | `head -c 70000 large-80k.txt` | deny | 70000 |
  | `head -c 70000 <large-80k.txt` | **pass** | **70000** |
  | `head -c 70000 < large-80k.txt` | deny | 70000 |
  | `cat large \| head -c 70000` | deny（パイプ末尾、C>MIN_BYTES） | 70000 |
  | `cat large \| head -c 100` | pass | 100 |

  - `tokenize`（`plugin/hooks/check-bash-read` 266–301 行）は `>` を redirect にするが `<` は通常文字。密着形のトークンは単語 `<./large-80k.txt`（既存ファイルではない）。空白形は単語 `<` とパスが残り、パスが通常ファイルなら `FILES` に入る。
  - `collect_file_args` / `ht_parse` は単語オペランドだけを見る。`run_head_tail` 482 行は `FILES` 空なら即 `pass`。よって単独 `head -c 70000 <file` は `-c` 値を見ない。
- 仕様照合
  - §10-4 の演算子は `|` / `;` / `&&` / `||` / `&` / stdout の `>` `>>`。入力リダイレクト `<` は列挙されていない。
  - §10-6: 「残りの引数から `-` で始まるフラグを除いた通常ファイルを対象にする。対象が 0 なら通過。」
  - §10-7 の `head -c 70000` deny 例と §13 `bash-head-c-70000` はファイルオペランド付き。パイプ末尾だけが「stdin の `-c C` を `C ≤ MIN_BYTES` で判定」する（§10-4）。
  - §4 / §15 の既知穴は `@`、Grep content、`sed`、`python -c`、未知パイプ末尾、逐次 targeted Read、`bash -c`（README 制限事項）。`<` は未記載。
  - README Bash 表「単独の `cat` … 入力ファイル全体」「単独の `head` … バイト数指定は出力予定バイト数」は、表だけ読むと `<file` も含みうる。アルゴリズムは単語オペランド 0 件を通過と書く。
- 判定理由
  - 現象（密着 `<` が pass、実 bash は全文/70,000 バイトを出す）は再現する。しかし現行アルゴリズム §10-5/6 の「対象 0 → 通過」に一致する。コード欠陥ではない。
  - 空白付き `cat < file` の deny は `<` をリダイレクトとして見ていない副作用であり、入力リダイレクト検査の実装ではない。`<` を redirect 種別にすると密着・空白の両方ともターゲットを飛ばして pass になる。
  - README 表はアルゴリズムより広く読める。**docs-only で README 制限事項と §15 に stdin `<` を既知の穴として書くべき**（`dd if=` / `bash -c` と同列）。フックの deny 範囲を広げるのは仕様変更であり、現行契約のバグ修正ではない。

### 3 — SPEC GAP
- 再現
  - `cat $'large-80k.txt'`: フック **pass**、実 bash stdout **81920** バイト。
  - `cat 'large-80k.txt'` および素のオペランド: フック deny、実 bash も 81920 バイト。
  - tokenize: `$` は通常文字、続く `'`…`'` は単一引用。結果トークンは `$large-80k.txt`（既存ファイルではない）→ `FILES` 空 → pass。
  - 改行名ファイルとの合成 `cat $'/path/nlfile.txt\n'`: フック pass、実 bash は 80,000 バイト（ANSI-C が `\n` を改行にする）。こちらは候補 4 の「末尾 LF trim」ではなく、`$''` 非対応の別経路。
- 仕様照合
  - §10-4 状態機械は通常 / `'` / `"` / `\` の 3 種。解釈不能は `$('` / `$(` / バッククォート / 閉じない引用。`$'` は列挙されていない。
  - 見出しは「引用を踏まえて明示ファイルを検査」。`$''` は bash の引用形だが、書いた状態機械の対象外。
  - README は「シェル全体を解釈するのではなく、対応するコマンドと明示的な入力ファイルを検査」と前置きし、引用は `'` / `"` / エスケープの `|` `#` `>` を述べる。ANSI-C は未記載。
- 判定理由
  - 実装は列挙済み状態機械どおり。コードが現行アルゴリズムに反しているわけではない。
  - 一方、表題の「引用を踏まえた明示ファイル検査」だけを読むと `$'large.txt'` は明示パスに見える。README 表の単独 `cat` も同様。これは README/§10-4 がアルゴリズムより広く聞こえる穴であり、deny-reason が `$''` を捕まえるとは書いていない。
  - 製品バグにするなら §10-4 へ `$''` を状態として足すか、解釈不能（fail-closed）へ倒す仕様変更が先。現状の確定対応は **既知の穴として README / §15 に書く**（候補 2 と同型の docs）。

### 4 — FALSE POSITIVE
- 再現（小ファイル `nlfile.txt` 9 バイト、大ファイル `nlfile.txt\n` 80,000 バイトが同一ディレクトリ）

  | 入力 | フック | 実 bash stdout |
  |---|---|---|
  | Read `file_path=.../nlfile.txt\n` | deny（大ファイル） | （Read ツール。未実行） |
  | Read `file_path=.../nlfile.txt` | pass | — |
  | Bash 非クォート `cat .../nlfile.txt<LF>` | pass | **9**（小ファイル） |
  | Bash 引用内改行 `cat '.../nlfile.txt\n'` | deny | **80000**（大ファイル） |
  | Bash `cat '.../nlfile.txt'<LF>`（閉じた後の末尾 LF） | pass | 小ファイル |

  - `check-bash-read` 148–150 行: `jq -r` + 先頭末尾 `[:space:]` trim。コマンド末尾の LF は落ちる。
  - `check-file-size` 137–140 行: `jq -j` + sentinel で path 末尾 LF を保持。README Read 節「ファイル名に含まれる末尾の改行も保持」と一致。
- 仕様照合
  - §10-3: コマンドの「先頭末尾空白を trim」。改行は空白。
  - 非クォートの改行は bash でも単語の一部ではなくコマンド区切り。フックが末尾 LF を落としても、非クォートコマンドが開くファイルは小ファイルのまま。
  - 引用内改行は trim 対象ではなく、tokenize がファイル名として残す → 大ファイルを見て deny。実 bash も大ファイルを出すので、ゲートは閉じている。
- 判定理由
  - 「Bash は pass、Read は deny」は再現するが、検査対象が違う。Read は LF 付きパス（大）、非クォート Bash は LF 無しパス（小）。親へ大ファイル本文が Bash から流れる経路ではない。
  - Read 側の sentinel は README の明示契約。Bash 側の trim は §10-3。既知の実装差であり、現行契約の欠落ではない。ANSI-C で改行名を開く穴は候補 3。

## 修正すべき確定リスト

1. **候補 1（コード / スキル）:** 委譲メタデータの行数を `wc -l`（改行数）から、§8.6 / Read と同じ未終端最終行込みの論理行数へ変える。`plugin/skills/bulk-reader/SKILL.md` の `wc -lc` 取得と supplied EOF、対応する §11 の取得手段。判定器は実ファイル行数を既に使っているので、供給値と揃える。
2. **候補 2（docs-only）:** README 制限事項と設計 §15 に、単語オペランドが無い stdin `<`（例: `cat <large>`、`head -c 70000 <large>`）は検査せず通過すること、実 bash は本文を出すことを既知の穴として追記する。フックコードの変更は現行 §10-6 の外。
3. **候補 3（docs / 仕様。コードは任意の仕様変更）:** `$''`（ANSI-C 引用）を README / §15 の既知穴、または §10-4 の解釈不能へ明示する。列挙状態機械を拡張しない限りフック修正は契約変更。

候補 4 は修正対象外。
