# 敵対的レビュー（クリーンコンテキスト）

実施日: 2026-09-14。会話を継承しない独立コンテキストで実施。現行ソースのみを攻撃対象とし、`reviews/`・`docs/history/`・git 履歴は根拠に使わない。静的解析のみ、ファイル変更・破壊行為なし（読み取り専用）。

---

# セキュリティレビュー報告: token-shunt

## 範囲・手法

- 対象: `plugin/hooks/*`、`plugin/agents/*`、`evals/compare/{judge,routing_checks,flow_checks}.py`、`evals/*-evals.json`、README、設計書。
- 静的解析のみ。各候補は現行ソースで「通過すること」を確認したものだけを確定 finding とし、文書化済みの制限は「設計内」に分類。

## 確定した finding

### F1【P1】同一コマンド行内のステージングで `-f`/サイズ検査を素通りできる

- 箇所: `plugin/hooks/check-bash-read:457`（`collect_file_args` の `[[ -f $t ]]`）、`464-469`（`check_files_full` → `full_file_verdict`/`stat`）、`746-758`（複合区間ごとの検査）。
- 攻撃例（フックが pass、実 bash が本文を親 stdout へ出す）:
  - `cp large.txt s.txt; cat s.txt` — `s.txt` は判定時に不存在 → `cat s.txt` は FILES 空で通過。
  - `cp large.txt small.txt; cat small.txt` — `small.txt` は実在・小さい → 本文検査 OK → 実行時に上書き後 `cat` が大容量を吐く。
  - `mv large.txt s.txt; cat s.txt`、`ln large.txt s.txt; cat s.txt`、`ln -s large.txt s.txt; cat s.txt`、`tee s.txt < large.txt; cat s.txt`、`install -m644 large.txt s.txt; cat s.txt`、`python3 -c 'import shutil;shutil.copy("a","b")'; cat b`。
  - パイプ版: `cp large.txt s.txt | cat s.txt`（`cat` が最終段 → 全段 `check_stage_full` でも `cp` は未対応、`s.txt` は判定時点で小/不在）。
  - `cat` だけで完結する版: `cat < large.txt > s.txt; cat s.txt`（`<` は文書化済みの穴と併用）。
- 判定: **実装の穴**。文書化された制限（設計§403、README:182-184 の未対応コマンド群）は別経路。ここでは reader は列挙済み `cat`、オペランドは明示リテラルパスで「検査対象」のはずが、**判定時刻と実行時刻でファイル同一性が変わる**点が未文書化。`cat large > s; cat s` は seg1 の `cat large` が deny されるため不可 — `cp` 等の「reader 以外の書き込み側」が必須。
- 影響: 1 コマンド行で確実に全量リーク。閾値回避ではなく検査対象のすり替え。

### F2【P1】`+=` / `[i]=` 代入プレフィックスが strip_vars を抜ける

- 箇所: `plugin/hooks/check-bash-read:422`（`^[A-Za-z_][A-Za-z0-9_]*=` のみを代入語としてスキップ）。
- 攻撃例: `x+=v cat large.txt`、`a[0]=v cat large.txt`、`PATH+=:/tmp cat large.txt`。
- 仕組み: `x+=v` は正規表現に非一致 → コマンドワードが `x+=v` → `*)` で pass。実 bash では有効な環境代入プレフィックスとして `cat large.txt` が実行され本文が出る。`V=1 cat` は catalog（`bash-pipe-head-varprefix` 等）で対応済みだが `+=`/`[]=` 系は未対応。
- 同一ギャップが評価側にも存在: `evals/compare/judge.py:830` の `bash_recovers_body` が同じ形の代入正規表現を使うため、deny 後の `x+=v cat f` は deny_bypass 検査も通過する。
- 判定: **実装の穴**（実装済み・テスト済み機能の欠けた形）。
- ※統合側の偽陽性チェックで `a[0]=v` は実 bash が `not a valid identifier` で拒否することが判明。`+=` 形のみ成立。

### F3【P1】コマンドワードの brace/glob 展開

- 箇所: `plugin/hooks/check-bash-read:328`（`{`/`[`/`~` 等で `S_EXPANSION=1`）と `664-670`, `818-819`（展開の deny が reader アームの内部に限定）。
- 攻撃例: `{c,}at large.txt`（brace で `cat` と `at` に展開 → `cat at large.txt` → `at` は無くても `large.txt` を出力）、`ca{t,} large.txt`、`{cat,} large.txt`。`[c]at large.txt` は cwd に `cat` が存在すれば可（`{c,}at` は無条件）。
- 仕組み: base が `{c,}at` となり reader アームに入らず `*)` で pass → 実 bash の brace 展開で `cat` が生成される。README:183 の展開 deny は「対象 reader のオペランド」に限定されており、コマンドワードは未列挙。
- 判定: **実装の穴**（deny がオペランド側に限定されているのは実装上一貫）。`$(echo cat)`/`$c`/`cat$''`/`cat$""` のコマンドワード版はそれぞれコマンド置換・変数展開・`$''` として文書化済みの類。

### F4【P2】`check-reader-contract` がパス同一性をリテラル文字列で管理

- 箇所: `plugin/hooks/check-reader-contract:31-36`（`state['paths']` を `file_path` 文字列キーで管理、正規化なし）。
- 攻撃例: `/a/f` が `stopped` になった後 `/a/./f`、`//a/f`、`/a/x/../f`、シンボリックリンク表記で同一ファイルを別キーとして再 Read（`next=1` からやり直し）。
- 制約: 全体 `calls>=6`（line 26）と 3 文字列上限は有効なままなので「3 ファイルを超える」ことは不可。回避できるのは per-path の `stopped`/`retry`/カーソル。
- 緩和: 評価側 `use_targets_path`（`judge.py:744-759`）は `norm_path` で正規化するため、エイリアス Read は `check_reader_reads` の `expected` 不一致で fail になる。ランタイム側だけが抜ける構造。
- 判定: **実装の穴**（canonicalization 欠如）。※統合側で `stopped` 済みパスのエイリアス再 Read が通ることを実機再現済み。

### F5【P2】judge の `bash_recovers_body` が綴りとコマンド網羅で回避可能

- 箇所: `evals/compare/judge.py:803-876`。
- 攻撃例:
  - 綴り: `sort ./big.txt`、`cat $PWD/big.txt`、`awk x dir//big.txt`、`sed -n p x/../big.txt` — 引数正規表現 `(?<![\w/.-])target(?![\w/.-])`（line 841-843）が `/`・`.` 前置を拒否するため非検出。`sort`/`sed`/`awk`/`xargs`/`python`/`od`/`xxd`/`perl`/`nl`/`cut`/`grep`/`dd` は readers 入りだが綴りで抜ける。
  - 未列挙エミッタ: `bash -c 'cat /abs/big'`、`sh -c`、`eval`、`source f`、`. f`、`tac`、`rev`、`fold`、`fmt`、`pr`、`expand`、`base64`、`hexdump`、`git show`、`tar`、`unzip`、`zcat`/`gzip -dc`、`jq`、`yq`、`sqlite3`、`node`、`php`、`ruby`、`make`、`ssh host cat f`、`busybox cat`、`cp f /dev/stdout`、`tee /dev/stdout < f` — `readers`/`wrappers`（line 819-822）の双方に無いため検出されない。
- 影響: deny 後の本文回収がトランスクリプト判定で見えない。`cat ./f` 自体は hook が `-f` で deny するため実害は「hook を通過する未対応コマンド + 綴り」の組合せに限る（例: `sort ./big` は hook も通過、判定も通過 → 親が本文を得たのにクリーン判定）。
- 判定: **実装の穴**（評価の偽陰性）。※統合側で `./`・`//`・`..` 綴りと `tac`/`base64` の非検出を再現済み。

### F6【P2】子返答の本文検出は分割・変形・fixture 外で回避可能

- 箇所: `evals/compare/judge.py:891-951`（`long_nonempty_run`>20、`contiguous_bytes`≥2049）、`1409-1420`（`child_no_body` は fixture 限定、かつ `long_nonempty_run` は `not fpaths` の時のみ）、`1918-1938`（`leakcheck` も同一基準）。
- 攻撃例: 本文を 2048 バイトごとに任意の 1 バイトで挟む、20 行ごとに空行/コメントを挟む、base64/rot13/語順変更/言い換えで運ぶ → いずれも `child_no_body`/`leakcheck` を通過。閾値自体は README:231 で文書化済み。
- 追加の穴: `child_no_body` は `spec.fixtures` の本文のみ照合するため、**fixture 外ファイル**の本文（例: code-writer が Read した未宣言ファイル）は検査対象外。`parent_added_text`/`leakcheck` は `thinking` ブロックを除外（`judge.py:281-282`）するため thinking 経由の本文はバイト計測と引用検査を両方通過（usage の `input_tokens` には計上される）。
- 判定: 閾値は**設計内**、fixture 限定と thinking 除外は**実装の穴相当**。

### F7【P2・設計内寄り】code-writer の Read はサイズ免除かつランタイム契約なし

- 箇所: `plugin/hooks/check-file-size`（allowlist に `token-shunt:code-writer`）、`plugin/hooks/check-reader-contract:88`（`bulk-reader` のみ適用）、`plugin/agents/code-writer.md`（`tools: Read, Write, Grep, Glob`、`maxTurns: 12`）。
- 内容: code-writer は大きな Read を無制限に発行可能（契約の 6 回/3 パス/直列/カーソル強制は適用外）。README の「最大16ファイル・20回」は指示文のみで機械的強制なし（README:191 も返答切り詰めなしを明記）。唯一の実行時上限は `maxTurns`。
- 判定: 免除自体は README:146 で文書化 → **設計内**。ただしバックストップが eval の `child_msg_cap`（spec が `child_msg_max` を設定した時のみ）と `child_no_body`（fixture 限定）だけである点は構造的弱点として記録。

### F8（情報）`agent_type` 免除の信頼根拠

- `check-file-size`/`check-bash-read`/`check-reader-contract` は入力 JSON トップレベルの `agent_type`（harness 供給）でのみ免除判定（README で `tool_input.agent_type` を使わないと明記）。harness が実際に親/子で正しく供給するかは実機依存 → **未検証**。

## 設計内として確認（finding としないもの）

- `echo $(cat large)` の pass — catalog `bash-subst-cat-pass`・設計§403 で明示。
- `cat <large`/`head -c 70000 <large` 等 `<` 入力 — README:185 明記。
- `cat $F`/`cat "$F"`/`cat $PWD/x` — 設計§403「変数展開からのパス解決を行わない」。
- `cat $'x'`/`cat$''`/`cat$""` — README:186。
- `cat <<EOF\n$(cat large)\nEOF` — 非引用 heredoc 本体のコマンド置換。コマンド置換の非解釈（§403・README:182）の一実例だが、「heredoc 本体を精査している」実装姿勢と矛盾して見える点は注記に値する。
- 未列挙コマンド全般（`bash -c`/`eval`/`source`/`xargs`/`dd if=`/`find -exec`/`git show`/`sed`/`awk`/`perl`/`python`/`jq`/`base64`/`od`/`xxd`/`tac`/`rev`/`nl`/`fold`/`fmt`/`pr`/`expand`/`iconv`/`tr`/`sort`/`diff`/`gzip -dc`/`tar`/`unzip`/`sqlite3`/`ssh`/`make`/`curl`/`busybox`/`node`/`php`/`ruby`/`vim -es`/`ed` 等）— README:182,184。
- グルーピング・制御構文・関数定義、`!`/`time`/`timeout`/`command`/`env`/`nice`/`sudo`/`stdbuf`/`exec`/`nohup`/`builtin` 前置 — README:184。
- `cat large > file`/`>>`/`1>`/`01>`/`>|`/バックグラウンド — 親 stdout 非経由として文書化済み pass。
- `cat large | grep x` 等 unknown tail — §10-4/§15 の意図的 fail-open（`check-bash-read:805`）。
- `cat large | head -c 65536`（=閾値）は境界内 pass。
- `Grep`/`WebFetch`/`NotebookRead`/`Glob`/`Edit`/`Write` へのフック無し、`.png`/`.pdf`/`.ipynb` のサイズゲート除外 — `hooks.json` 実体と README:110,182,188 で一致。
- 呼出し横断のスライド Read 集計なし — README:189。
- 外来の「通過」フック（空ペイロード）の区別不能 — README:192・`judge.py:982-984` コメント。
- bulk-reader の Bash 免除 — README:143-146（現行定義では Bash 未付与で実害なし）。

## 試したが現行実装で防がれる

- クォート/エスケープ: `c'a't`、`ca""t`、`c\at`、`ca\t` → tokenize の引用除去で `cat` に正規化され deny。`cat 'la''rge'`、`cat "lar\ge"`、`cat lar\ge`、`cat 'a>b'`、`cat 'a|b'`、`cat 'a#b'` → 結合オペランドとして `-f` 検査で deny。
- `cat $(echo large.txt)` → `$`,`(`,`echo`,`large.txt` とトークン化され `large.txt` がオペランド収集→ deny。`cat "$(cat f)"` も `f` が `-f` で拾われる（結果はファイル名エラーで微少リークだが deny 方向）。
- プロセス置換: `cat <(cat f)`、`diff <(cat a) <(cat b)`、`cat >(x)` → `S_PROCESS` で一律 deny（`check-bash-read:732`）。
- オペランドの glob/tilde/brace: `cat *.txt`、`cat ~x`、`cat {a,b}`、`cat ?`、`cat [a-z]` → `S_EXPANSION` → deny（catalog・ops テストで確認）。
- `cd` 追跡: `cd d && cat f`、`cd d; cat f`、`cd d\ncat f`、`cd -- d && cat f`、`cd "d" && cat "f"`、連鎖 `cd a && cd b && cat ../f` → 全て deny（catalog `bash-cd-*`）。`cd d || cat f`、`cd d & cat f`、`echo x; cd d; cat f`、`cd d 2>/dev/null; cat f`、裸 `cd; cat f`、展開/オプション/CDPATH 依存の `cd` → `CD_UNCERTAIN` で deny。
- heredoc: 引用区切り子の本体マスク、`$'`/`$"` 区切り deny、未閉鎖区切り deny、非引用本体の `\` 継続 deny、複数 heredoc の逐次マスク。
- リダイレクト: `2>errors cat f`（前置）、`cat f 2>/dev/null`、`cat f 2>&1`、`cat f 3>out`、`cat f >&2`、`cat f &>f`、`cat f &>>f`、`cat {fd}>out f`（名前付き fd deny）、`>/dev/stdout`/`/dev/stderr`/`/dev/fd/*`/`/proc/*/fd/*`/`pipe:`/`socket:` 宛て → 全て deny。`cat f 2>err >out` は pass（正しく隔離済み）。
- fd/tee 側経路: `cat f | tee /dev/stderr | head -c 1`、`cat f 1>&2 | head -c 1` → fd ルート追跡で deny。`|&`、`2>&1 |` は pipe 側に寄る正しい判定。
- head/tail: `-n`/`-c`/`--lines`/`--bytes` の行・バイト実測（`range_scan`/`tail_scan`/`probe` は stat 非依存）、`+N`・未知フラグ・複数サイズ指定 → 全文判定で deny。`head -c 10^19` は >15 桁で uninterpretable → deny。`tail -f` → deny。
- パイプ末尾: `cat f | head`/`head -n 1`/`tail -n 1`/`cat f |`（空末尾）/`| $(x)`/バッククォート末尾 → deny。`| head -c 100` pass、`-c 70000`/巨大値 deny。`V=1` 前置の reader も段単位で正しく扱う。
- 複合: `echo ok; cat f`、`true && cat f`、`cat f; echo $(x)`、`echo $(x); cat f`、`V=1 cat f`、`cat f > /dev/null`（複合内早期 pass なし）→ deny。
- 入力堅牢性: jq 不在・非 JSON stdin → exit 2。`TOKEN_SHUNT_*` の負数/非数値/15 桁超 → 既定値。`stat` 不能 → UNDETERMINED → deny。走査バイト/時間超過 → deny。stat 後のファイル肥大は `probe` 実測で deny。
- `agent_type` 照合: 裸 `bulk-reader`、`explore` 等は非免除（catalog `read-bare-agent`/`read-explore`）。
- reader 契約: 並行 Read・7 回目・4 パス目・非絶対パス・`offset≠cursor`・`limit` 非半減リトライ・検証不能な `tool_response`・非対象 Post イベント・壊れた状態ファイル・権限/所有の不正な状態 dir → deny または exit 2。
- judge: 壊れた JSONL、非文字列入力、子返答の証跡欠落、`status`/`stop_reason` 欠落・重複、パスを伴わない `confirmed:`、deny 後の `cat f`/`Read` スライス、外来フック混入、direct へのプラグイン混入 → 全て fail 方向。

## 疑ったが未検証

- `check-agent-model` が `.tool_input.subagent_type` のみ検査 — CLI が `type`/`agent_type` フィールドで送る場合はモデル強制が無効化（`judge.agent_type_of` は両方見る）。実機入力形式は未確認。
- トップレベル `agent_type` をモデル/ツール入力側から偽装・混入できるか（harness の供給経路依存）。
- `PostToolUse`/`PostToolUseFailure` イベントに `session_id`/`agent_id`/`tool_use_id`/`tool_response.file{startLine,numLines,totalLines}` が常に付くか — 欠落時は fail-closed だが、形式差異で契約状態が素通し/全面停止する可能性。
- transcript の `thinking` ブロックに実機が本文を含めるか（含めば `parent_added_text`/`leakcheck` を通過、`usage` のみ計上）。
- `hook_name` が将来 CLI で変化し `TS_HOOK_NAMES`/`foreign_hooks` の前提が崩れる可能性。
- hook 判定→Bash 実行間の TOCTOU（バックグラウンドプロセスによるファイル差替え、FIFO 化 race）は単一コマンド行ステージング（F1）とは別に理論上存在。
- `EPOCHREALTIME`/`date` フォールバックや `wc -c`/`head -c` の環境差異（`LC_ALL=C` で緩和済みだが全環境は未確認）。
- `check-reader-contract` の state ファイルが tempdir 生存期間中残るため、`agent_id` 再利用時に旧状態が残る運用面。
- `input_text` の再帰レンダリングが極端に深い input で Python 再帰制限例外 → transcript 無効化（fail 方向だが評価不能を招く）。
- `verification_commands`/`unittest_arguments` の literal 制約は厳格（誤検出は fail 側）だが、実機の正当な検証コマンド形式との適合は spec 依存。
