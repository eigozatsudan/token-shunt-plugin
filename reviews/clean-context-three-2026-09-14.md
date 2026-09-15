# クリーンコンテキスト3視点レビュー — 2026-09-14

方法: `reviews/` 非参照の独立エージェント3名が「俯瞰(アーキテクチャ整合)」「通常(正しさ)」「敵対的(攻撃者視点)」で `plugin/` + README + 設計書 + scripts + evals をレビュー。集約後、すべての指摘を実コード精読 + フック実実行(JSONをstdin投入)で検証した。

検証環境: Linux/bash, jq あり。big.txt = 400行/800B(行しきい値超過)。

## 確認済み: 実害のある指摘(検証済み)

### A. ゲート回避(実実行で再現)

| # | 指摘 | 再現(実測) | 文書化状況 | 判定 |
|---|------|-----------|-----------|------|
| A1 | **`$VAR`/特殊パラメータ/`$'...'` 展開が operand・コマンド名ともに素通り** | `cat $PWD/big.txt`、`cat "$PWD/big.txt"`、`F=big.txt; cat $F`、`X=cat; $X big.txt`、`cat$IFS big.txt` → すべて pass | 設計 §403 で「変数展開のパス解決は保証しない」と明記あるが **README 制限事項に未記載**。コマンド名の `$X` / `cat$IFS` / `$'cat'` は設計書にも未記載 | **実バグ級の文書 gap + 完全回避**。check-bash-read:328 の展開集合に `$` がない |
| A2 | **解釈不能なパイプ末尾は先頭ステージしか検査しない** | `echo ok \| cat big.txt $(true)` → pass | 設計 §401 で仕様通り(先頭のみ判定)だが、2段目以降・末尾自体の reader は無検査 → 仕様レベルの穴 | spec-level hole。実回避として有効 |
| A3 | **未知のパイプ末尾は全ステージ無検査。stderr 側チャネルも** | `cat big.txt \| grep ''`、`\| sed -n p`、`\| base64` → pass。`cat big.txt 1>&2 \| wc -l`、`cat big.txt \| tee /dev/stderr \| wc -l` → pass | 未知末尾の fail-open は文書化済(§398, README:182)。`1>&2`/`tee /dev/stderr` による stderr 排出と中段既知 reader の逃避は未明記 | 文書化の範囲を超える変種あり |
| A4 | **denylist は5コマンドのみ** — `sort`/`tac`/`awk 1`/`jq .`/`base64`/`nl`/`fold`/`xxd`/`cp f /dev/stdout`/`git show :f`/`tar xOf`/`curl file://`/`eval`/関数定義 など | `sort big.txt`、`tac`、`awk 1`、`jq .` → pass | 「未対応コマンド」として類型は文書化済だが個別列挙なし | denylist 設計の既知限界。列挙で実効性を示す価値あり |
| A5 | **パーザが O(n²) で 10s タイムアウト超過 → fail-open** | 100KBコマンド → **11.7秒**(実測)。タイムアウト設計は fail-open(§269) | タイムアウトfail-open自体は文書化済だが「遅いFS」前提で、**コマンド長によるパース停滞は未文書** | エージェントがコマンド長を制御できるため確実な回避経路。`TOKEN_SHUNT_HOOK_LOG`→FIFOでも同型 |
| A6 | **非引用 heredoc 本文内の `$(...)` はマスクされ実 bash で展開** | `cat <<E` + `$(cat big.txt)` + `E` → pass | `$(...)` 類型は文書化済だが「マスカー自身が死角を作る」点は未明記 | 実回避として有効(下記 A7 と同根) |
| A7 | **非引用 heredoc 区切り `<<$D` / `<<${D}` / `<<$(cmd)` が誤マスク → 後続コマンド隠蔽**(通常レビューの新規指摘) | `cat <<$D` + `EOF` + `cat big.txt` + `$D` → pass | README:133・設計:977 は「安全に解釈できない区切りは拒否」と明記 → **コードは `$'`/`$"` のみ拒否で `$D` 系を見落とし** | **明確な実装バグ**。文書化ポリシーと矛盾 |
| A8 | **拡張子免除の rename 回避 + `NotebookRead` 未フック** | `.ipynb` 免除は check-file-size:174-176。`cp big.txt big.ipynb`(cp は無検査)後 Read → pass。hooks.json の matcher は `"Read"` のみ | 免除自体は文書化済、rename/NotebookRead 回避は未記載 | 確認済み |
| A9 | **呼出し内集計なし(オペランド毎判定)** | `head -c 131072 big.txt \| tail -c 65536` → pass(任意64KB窓)。`head -c 65536 f1..fN` → N×64KB | 設計:424 で per-file は仕様 | spec-vs-goal gap |

### B. 状態・ライフサイクル(実実行で再現)

| # | 指摘 | 検証 | 判定 |
|---|------|------|------|
| B1 | **`check-reader-contract` の `pending` デッドロック**: Pre で pending 設定(46)、Post/PostFailure の tool_use_id 一致でのみ解除(50)。喪失(割込み・他フック deny・ID不整合・書込前例外)で以後全 Read が "still pending" 拒否 + 予算消費 | **再現済み**: 一致しない post → 次の Pre が永久 deny。残留 state で初回呼出しから deny になるケースも確認(/tmp に ~65個の残留 state が実在) | **確認済み・中** |
| B2 | **状態ディレクトリ改ざん・停滞**: `rm -rf /tmp/token-shunt-reader-$UID`(Bash `rm` は無検査)で予算リセット — docstring「resumed invocations cannot reset it」と矛盾。`flock` 保持 → 契約フック停滞 → 10s timeout → fail-open で無契約 Read | コード確認(rm→次回mkdir+初期state)。新 agent_id で新規予算になるため影響は anti-thrash 範囲 | 確認済み・中〜低 |
| B3 | **環境変数の信頼境界**: `TOKEN_SHUNT_MIN_*` を巨大値に → 全通過(コード確認、int_env は ≤15桁を受理)。`PATH` で `head`/`tail`/`wc`/`jq` 偽装 → 判定偽造。`BASH_ENV` → フック内コード実行。`TOKEN_SHUNT_HOOK_LOG=/dev/stdout` → **stdout に2JSON実測**(プロトコル汚染)。`TMPDIR` → worker DoS | HOOK_LOG→/dev/stdout は実測。settings.json `env` 到達は未検証だが CLI の標準動作 | **確認済み・高(配布面)** |
| B4 | **`agent_type`/`agent_id`/`tool_use_id`/`tool_response.file` の stdin スキーマ未検証**: フィールド未供給なら免除不発 → worker の Read が deny + 契約不活性 → 親も読めず委譲も死ぬ(プラグイン無しより悪い)。doctor も「要手動確認」 | コード確認(case一致必須、非該当は早期return) | 最大のデプロイリスク・中 |

### C. 正しさ・UX(確認済み)

- **C1** `head -n 0` / `tail -n 0` → deny(実測)。実際は0バイト出力 → **誤拒否**。check-bash-read:632
- **C2** `head -n 5 big | cat` → deny(実測)。パイプ内 head/tail が全文しきい値で判定される。`cat big | head -c5` は pass との非対称 → 過剰拒否
- **C3** `check-jq` の警告が「Read and Bash」だが実際は `check-agent-model` も exit 2 → **全 Agent/Task 起動もブロック**(check-jq:16 vs check-agent-model:4。README:15 は正しい)
- **C4** deny 理由が常に `/token-shunt:bulk-reader` 案内のみで code-writer を示さない(check-file-size:145, check-bash-read:162)
- **C5** ヘルパー ~120行が2フック間で重複(int_env/now_ms/hook_log/file_size/range_scan/full_file_verdict)— ドリフト危険
- **C6** `check-agent-model` は `tool_input.subagent_type` のみ検査。フィールド名変更でサイレント無効化(judge.py:391 は複数エイリアス受理で不整合)
- **C7** `jq -e .`(両サイズフック)は複数JSON文書を受理、`check-agent-model` は `-s` + length==1 を要求 — 入力検証不整合(実害なし)
- **C8** `cd` 追跡の `*'('*` 判定が引用内 `(` にも反応 → `cd sub; cat "f(1).txt"` 誤拒否(fail-safe方向)
- **C9** stdin `cwd` 非参照: Bashツールの永続cdとフックcwdが乖離すると相対パスを誤解決 → `cd /data` 後 `cat big` が pass になり得る(ハーネス依存・中低)
- **C10** python3 不在時、`check-reader-contract` が全 Read の Post/PostFailure で spawn 失敗 — README は bulk-reader のみと説明(ハーネスの spawn 失敗セマンティクス依存)
- **C11** 同一uidによる `$TMPDIR/token-shunt-reader-$UID` 先取り(squat) → uid/mode検査が exit 2 → worker DoS(実害低)
- **C12** TOCTOU(stat→head→Readの3回open) — 狭いが実在。README:244 は同一コマンド内変異のみ言及
- **C13** awk が NUL でレコード打ち切る処理系では byte 計上が過少 → 条件付き pass(awk依存・低)
- **C14** `TOKEN_SHUNT_HOOK_LOG` にコマンド全文記録 → env 指向先によってはコマンド/パス漏洩
- **C15** build-zip.sh は plugin/ 内 symlink を辿って収録(`.claude-plugin` 外が信頼済みなら実害なし)

## 偽陽性チェック結果(棄却・格下げ)

| 指摘 | 判定 | 理由 |
|------|------|------|
| 敵対的: `exec 3<big; cat <&3` が単一呼出しで pass | **棄却(単一呼出し形)** | 実測 deny — `exec` が stage_may_mutate で FS_UNCERTAIN → 拒否。`cat <&3` 単体 pass は事実だが fd の事前openが別呼出し必要(永続fd前提)。ドキュメント済 `<` 族の変種として格下げ |
| 通常: plugin.json の "Do not enable alongside Spotify shunt" は残渣 | **棄却** | 意図的な併用警告。README:50 に Spotify `shunt@portal` との併用禁止が明記 |
| 俯瞰: big-scan.txt / token-shunt.zip が gitignore 未登録 | **棄却** | `git ls-files` で両者とも追跡済み(意図的)。run.sh コメントも「tracked fixture」 |
| 敵対的: `$VAR` 回避は「未文書」 | **一部格下げ** | 設計 §403 で変数展開パス解決は保証外と明記。ただし README 制限事項と、コマンド名 `$X`/`$'cat'`/`cat$IFS` はどこにも未記載 → A1 として残存 |
| 敵対的: 解釈不能末尾の先頭のみ検査は「バグ」 | **格下げ** | 設計 §401 が明示する仕様 → 実装バグではなく設計レベルの穴(A2) |
| 敵対的: check-agent-model の配列 `subagent_type` で pass | **実害なし** | ハーネス側が起動自体を拒否するはず。型ゆれのみ |
| 通常: `cat $f` operand 回避 | **文書化済と確認** | 設計 §403 明記(README gap は A1 に集約) |
| worker の6呼出し/3パス制約を「境界破り」とする表現 | **精度修正** | 新規 agent_id で新規 state のため anti-thrash 措置であり堅い境界ではない(指摘者自身も認識済み) |

## 総合評価

- **実装品質**: denylist パーサの防御済み経路(リテラル cat/head/tail、リダイレクト、引用、cd追跡、heredoc 大半)は堅牢で、3名とも「コードは仕様に忠実」と一致。eval ハーネスも文書の主張を実際に計測している。
- **ただし境界としては成立しない**: A1(`$`展開)・A4(denylist)・A5(パースDoS)など複数の独立した完全回避経路が実測確認された。トークン節約の「誘導」としては協力的エージェント相手に機能するが、軽度に敵対的な入力への「境界」ではない。
- **最優先の修正候補**: (1) 非引用 `$`/`$'`/`$"` をコマンド・オペランド双方で uninterpretable 扱い(A1) (2) `<<$D` 系区切りの拒否(A7、文書ポリシーとの矛盾) (3) パースの O(n) 化 or コマンド長上限→超過は deny(A5) (4) stdin `cwd` の尊重(C9) (5) `pending` の自己修復(期限/孤立検出)(B1) (6) 環境変数・PATH・BASH_ENV の信頼境界明文化(B3)。
- **残留リスクは文書通りの集中先**: `agent_type` 等の stdin フィールド供給がプラグイン全体の成立条件であり、doctor でさえ「要手動確認」。CLI スキーマ検証を機械化するのが最大のデプロイ改善。

証跡: /tmp/ts-test(検証後削除)。実測値は本ファイル記載のコマンドを stdin JSON で各フックに投入して得た。
