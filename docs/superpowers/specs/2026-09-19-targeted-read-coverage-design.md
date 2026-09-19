# targeted Read の逐次回収を観測する（被覆率計器）

2026-09-19。**拒まない。ship gate に入れない。封鎖範囲を広げない。**

## 0. なぜ要るか

`reviews/intake-replay-2026-09-19.md` §4 で分かったこと:
アーカイブ 14 本の親 corpus Read 21 回のうち、**18 回が `offset`+`limit`
付きの targeted Read** だった。全文 Read 3 回は**掛かった 1 本に集中**している。

Lock B は targeted Read を deny しない（`2026-09-19-cumulative-intake-design.md`
§3.3、編集契約を殺さないため）。したがって:

> **親が corpus を取り込む通常の形は、Lock B が決して拒まない形である。**

§3.3 が「`docs/2026-09-12-token-shunt-design.md` §15 の既知の限界として残す」と書いた穴は、**このデータでは例外ではなく
多数派だった。** 本仕様はその穴を**塞がない。測れるようにするだけである。**

線を引く（何%を超えたら逐次回収とみなすか）根拠になる実測は**1 本も無い。**
根拠を作る前に閾値を書くのは、Lock B の 16,384 で既に一度やった間違いである
（cumulative-intake spec §3.1 の「実測がこの値を選んだ」は言い過ぎだった）。**本仕様は閾値を持たない。**

## 1. 決めたこと（先に）

| 問い | 答え |
|---|---|
| 目的 | **観測のみ。deny しない。ship gate でない。** |
| 定義 | **ファイル単位の被覆率**（親が原本の何割を回収したか） |
| 計器の位置 | **フック内・実機時**（PostToolUse） |
| 既定 | **無効**（`TOKEN_SHUNT_HOOK_LOG` が無ければ 1 バイトも書かない） |
| 遡及 | **しない**（§6.1） |
| 新しい課金 | **提案しない**（§6.2） |

## 2. なぜフック内・実機時か（分母の所在）

アーカイブの Read `tool_result` を直接開いて確認した。中身は `cat -n` 形式の
テキストだけで、キーは `content` / `tool_use_id` / `type` の 3 つ。
**構造化された `file` は transcript に載っていない。**

一方 `totalLines` は**フック側にはある** —— `plugin/hooks/check-reader-contract:142`
が PostToolUse の `tool_response.file` から `startLine`/`numLines`/`totalLines`
を取っている。

> **分子（どの行域を回収したか）は transcript から出る。分母は出ない。**

分母を推定した瞬間に被覆率は嘘になるので、**分母が無料で手に入る場所に計器を置く。**

## 3. 記録するもの（フック 1 回 = JSONL 1 行）

新規 `plugin/hooks/record-coverage`（Python、755）。
`hooks.json` の PostToolUse/Read に、`record-intake` の**後ろ**に足す。

```json
{"hook":"record-coverage","session_id":"…","agent_id":null,
 "file_path":"…/migration.py","start":139,"lines":50,"total":316,
 "bytes":2814,"offset":139,"limit":50,"is_error":false}
```

- `start`/`lines`/`total` は `tool_response.file` の 3 つを**そのまま**。
  **フックが数え直さない。**
- **`is_error` を見る。** エラーで返った Read は行域を主張できないので
  `start`/`lines`/`total` を `null` にし、**行自体は残す**（回数を落とさない）。
  `parent_turn_reads.read_rows` が同じ判断をしている。
- **`agent_id` と `agent_type` の両方を持たせる。** `intake_ledger.py:134` は
  親を `not (agent_id or agent_type)` で判定している —— **2 つ要る。**
  `agent_id` だけを見ると、`agent_type` しか載っていない worker の Read が
  **親の行として集計される。** 親の回収と worker の回収を混ぜたら被覆率は
  意味を失う（§6 も参照: worker 行は構造的に 1.0 に張り付く）。
- **`offset`/`limit` は生のまま。** 「刻み読み」かどうかは集計側の定義であって、
  **フックが判定してはいけない。**
- **Read のみ。** Bash 経由（`sed -n '1,200p'`）の刻みには `totalLines` が無い。
  §8.3 の非目標に置く。

ログは既存の `TOKEN_SHUNT_HOOK_LOG` に相乗りする。他のフックの
`{hook,decision,reason,…}` 行と同じファイルに混ざるので、
**集計器は `hook == "record-coverage"` で絞る。**

## 4. フックの形（安全性）

- **`hookSpecificOutput` を書く経路をコードに持たない。stdout に何も出さない。**
  deny する能力が**構造的に存在しない**のが、この計器の主要な安全性である。
- `main()` 全体を try/except で包み exit 0。`write-hook-log` 自身も例外を
  握り潰す。**二重に fail-open。**
- **状態ファイルを持たない。** `token-shunt-intake-*` にも `token-shunt-reader-*`
  にも触らない。**Lock A / Lock B の壊れ方を 3 本目に増やさない。**
- **`intake_ledger` を import しない。** Lock B は budget=0 で完全に不活性
  （cumulative-intake spec §7.8）。相乗りすると、無関係な機構の既定が
  この計器の生死を決めてしまう。

## 5. 既定と配線

- **`TOKEN_SHUNT_HOOK_LOG` 未設定なら 1 バイトも書かない。**
  新しい環境変数を増やさない。
- 出荷既定は**無効**。`unmeasured-mechanism-ships-off` に自動的に従う
  —— 判定を出さないので「昇格」という概念自体が無い。
- **`run.sh` を直す。** `_claude_call` は `TOKEN_SHUNT_*` を剥がすので、
  Lock B の腕変数と同じ pass-through が要る（`SESSION_BUDGET_BYTES` の
  `TOKEN_SHUNT_SESSION_BUDGET_BYTES` 化と同型）。
  向け先は run ディレクトリ配下、`cost_probe.py` と同じ `<out>.hooklog` 命名。
  **課金を増やす変更ではない。次に何かを回したときに勝手に行が溜まる。**
- **ただし無料ではない。** これを立てると**全フック**がログを吐く。実測で
  フック 1 回あたり **+16ms**（`check-file-size` × 20 回、0.656s → 0.975s）、
  Read 1 回は Pre 4 本 + Post 3 本なので**ツール呼び出し 1 回あたり約 +110ms**。
  **判定は動かない** —— `hook_log` は `pass()`/`deny()` の後に呼ばれて戻り値を
  使わず、`judge.py` は hooklog を読まない。主要指標（親の文脈汚染）も動かない。
  **実行時間だけが延びる。** 数字を伏せて「タダ乗り」とは呼ばない。
- **無効時も無料ではない。** `hooks.json` の登録は無条件なので、`TOKEN_SHUNT_HOOK_LOG`
  を立てなくても **Read 1 回につき `record-coverage` の python3 起動が 1 回増える。**
  実測（ローカル計時、$0、20 回 × 3 セットの最小値）: **無効時 +24ms/Read**
  （0.472s / 20）、有効時は同フックだけで **+56ms/Read**（1.128s / 20、
  `write-hook-log` の 2 プロセス目と書き込みを含む）。§5 の上の行と同じ理由で、
  **この数字も伏せない。**
- **ログを立てると Bash のコマンド文字列が run のとなりに残る。** `run.sh` の
  `_claude_call` は**全腕で**無条件に `TOKEN_SHUNT_HOOK_LOG=$out.hooklog` を
  export するので、`check-bash-read` が書く行（コマンド文字列を含む）が
  毎 run、transcript の隣に生まれる。**`SENDBACK_TRIAL_LOG` の opt-in 方針とは
  わざと違う。** 理由は 1 run に 1 ファイルを固定するためで、呼び出し元が
  export したパスを使うと 2 つの run のテレメトリが 1 本に混ざる。
  **ログは診断物として扱う**（README の該当節と同じ扱い。リポジトリに入れない）。

## 6. 集計器 `evals/compare/read_coverage.py`

**新しいパーサは書かない。** 入力は自分のフックが書いた JSONL 1 本だけで、
`json.loads` 以上のことをしない。**transcript は読まない**（読むと §2 で
捨てた分母の問題が戻ってくる）。

`(session_id, 親か否か, agent_id, file_path)` ごとに `[start, start+lines-1]`
の閉区間を集める。**親判定は `agent_id` と `agent_type` の両方から取る**（§3）。

**hooklog は turn ごとに別ファイルである**（`run_claude_resume` は turn ごとに
別の `$out` を使う）。5 ターンの会話は 5 本の hooklog に散る。集計は
`session_id` で束ね直すので正しく合流する —— **`--resume` でも `session_id` が
同じなら。これは未検証の前提である**（§8.7）。集計器は 1 会話で複数の
`session_id` を見たら stderr に警告を出す。

| 列 | 定義 | なぜ要るか |
|---|---|---|
| `reads` | 行数 | 刻みの回数 |
| `covered` | 区間の**和集合**の行数 | 分子 |
| `total` | `totalLines` | 分母 |
| `coverage` | `covered/total` | 主要な数字 |
| `overlap` | `Σlines − covered` | **同じ行を二度取り込んだ量** |
| `segments` | 和集合の互いに素な区間の数 | 1 なら連続回収、多いなら飛び石 |
| `bytes` | `Σbytes` | `parent_bytes.py` と突き合わせる先 |
| `full_file_reads` | `offset` も `limit` も無い Read の本数 | **行上限で切られた全文 Read** と刻み読みを見分ける唯一の手掛かり（§8.10）。**件数であって閾値ではない。** |
| `source` | hooklog の basename | §9 の glob は全 run・全 mode・全 case を 1 本の CSV に混ぜる。`<case>.<mode>.jsonl[.turnN.jsonl].hooklog` から**腕とケースが読める**。run ディレクトリは直後に消えるので、ここに残さないと永久に復元できない |

CSV 全体の列は 16 列（上の表のほか `source` / `session_id` / `parent` /
`agent_id` / `agent_type` / `file_path` / `total_changed` / `impossible`）。
`source` は**グループ化キーにも入る。**

- **親と worker を混ぜない。** 別行として出し、合算しない。
  **rollup も別々に取る**（`rollup(rows, parent=True|False)`）。stderr にも
  `# parent …` / `# worker …` の 2 行として出す。**見出しの数字は親の率である。**
- **`total` が途中で変わったら（間に Edit が入った）`total_changed` を立て、
  その行を率の rollup から外す。** 平均に黙って混ぜない。
- **`covered > total` になったら `impossible` を立て、率を出さない。**
  `check-reader-contract:143` が `start+count-1 <= total` を妥当性条件に
  使っている。破れたのはデータが壊れた合図であって、1.4 という被覆率ではない。
- **`rollup` は除外件数（`excluded`）を必ず出す。** `total_changed` の除外は
  **編集の多い会話を系統的に落とす** —— 残った母集団は「読んで終わった会話」に
  偏る。件数を出さないと、その偏りが見えない。
  **理由ごとに分けて出す**（`excluded_changed` / `excluded_impossible` /
  `excluded_no_total`）。1 つの数字に畳むと、どの偏りを抱えたのか言えない。
- **`rollup` は絶対量（`overlap` と `bytes` の合計）も出す。** 1-50 行を 10 回
  読んだ親は被覆率が変わらないのに 10 倍汚染されている。率だけでは見えない。
- **入力が 1 本でも読めなければ、stdout に 1 バイトも書かずに非ゼロで返る。**
  §9 の退避は `> reviews/data/….csv` なので**シェルが先に CSV を作る** ——
  途中で落ちると、run ディレクトリが消える直前に「データ無し」に見える
  空ファイルが commit される。coverage 行が 0 件なら、ヘッダだけを黙って
  出さず先頭に `# NO COVERAGE ROWS` を刻む。
- **多セッション警告は入力ファイル 1 本の中でだけ数える。** 1 hooklog = 1 turn
  なので、入力全体で数えると 40 ケース流すたびに必ず出て、§8.7 が見たい
  「1 会話が `--resume` で 2 つに割れた」を永久に見分けられない。
- **親行が 1 件も無ければ stderr に警告を出す。** `_parent` の前提が外れると
  CSV から親が消え、worker だけの 1.0 近い率が無警告で出る。
- **`coverage` は「親が何をしたか」であって、成果でも費用でもない。**
  高い被覆率が良いとも悪いとも、この計器は言わない。
  **低い被覆率も同様である** —— 刻み読みで 30% だけ取った親（汚染）と、
  Grep で要約だけ取った親（健全）を、この計器は**区別しない。同じ 0.30 に見える。**
  本文にそう書くだけでは足りないので、**`rollup` の出力自身に
  「これは順位ではない」と 1 行刻む。** stderr だけでは足りない ——
  **commit されるのは CSV の方**なので、rollup 2 行とこの 1 行は
  **CSV の先頭にも `#` 始まりの行として書く**（`reviews/data/` の CSV を
  機械で読む物が無いことは確認済み）。
- **worker 行は構造的に 1.0 に張り付く。** worker は全文を読むのが仕事である。
  親行と混ぜた rollup は**常に高く出る。** §3 の親判定が要る理由はこれである。
- 出力は `reviews/data/read-coverage-<date>.csv`。
  **run ディレクトリが消える前に出す**（88 対を 1 度失っている）。

## 7. テスト（TDD、RED を先に見る）

`evals/test_record_coverage.py` と `evals/compare/test_read_coverage.py`。
**各テストについて「これを落とす本番側の変更」を先に言えるものだけ書く。**

**`RecordTests`**（フック単体、stdin に PostToolUse イベント）
- 3 フィールドが `tool_response.file` からそのまま乗る → 数え直しに変えたら落ちる
- `is_error` の Read は `start/lines/total` が `null`、行は残る → 行ごと落とす実装で落ちる
- **`TOKEN_SHUNT_HOOK_LOG` 未設定なら 1 バイトも書かない** → 既定 ON で落ちる
- **`tool_response` が壊れていても exit 0、stdout 空** → 例外を漏らす実装で落ちる
- **どんな入力でも stdout が空**。併せて `hookSpecificOutput` という文字列が
  ソースに存在しないことを検査する → deny 経路を足した瞬間に落ちる
- **`token-shunt-*` 状態ディレクトリを 1 つも作らない** → 台帳型に寄せたら落ちる
- `intake_ledger` を import しない／budget=0 でも記録する → Lock B 相乗りで落ちる

**`WiringTests`** —— `hooks.json` の PostToolUse/Read に `record-intake` の
後ろで載っている、755 である。

**`CoverageTests`** —— 和集合の算術。重なる 2 区間、隣接区間、飛び石、
完全重複（`overlap` が立つ）、1 回で全文（`coverage == 1.0`）、
`total_changed` の行が rollup から外れる、親と worker が別行になる。

**`RunShTests`** —— `_claude_call` が `TOKEN_SHUNT_HOOK_LOG` を run
ディレクトリ配下に渡している → pass-through を消したら落ちる。
Lock B の腕変数テストと同じヘルパを再利用する。

**エンドツーエンド 1 本** —— 実物のフックを 3 回の刻み Read で叩き、
生まれた hooklog を `read_coverage.py` に食わせ、`coverage`/`overlap`/`segments`
が手計算と一致する。**計器の両端を同じテストで結ぶ**（Lock B の replay で
`parent_turn_reads` と突き合わせたのと同じ形）。

**課金は発生しない。** 全部ローカルの合成イベントで回る。

## 8. この設計が答えないこと

1. **アーカイブ 14 本には遡れない。** 分母が transcript に無く、corpus
   （`/tmp/ts-multiturn`、django 5.2.1 `bc833e8`）も消えている。
   **過去の 18 回の targeted Read の被覆率は、この設計では永久に出ない。**
   corpus を取り直せば埋まるが、それは別の仕事。
2. **次に実機が回るまで 1 行も出ない。** §7 は全部 $0 で通るが、§6 の CSV は
   空のまま。**新しい課金は提案していない。** Lock B の測定ブロックは
   走らせないと決めた（cumulative-intake spec §8.3）ので、
   **初出データがいつ出るかは未定である。**「ただ乗り」は約束であって予定ではない。
3. **Bash 経由の逐次回収は見ない**（§3）。分母を推定しないという決定の
   直接の代償で、**`docs/2026-09-12-token-shunt-design.md` §15 の既知の限界としてそのまま残る。**
4. **閾値も判定も出さない**（§0）。線は、行が溜まってから別途決める。
5. **ship gate ではない。** `evals` の release gate に入れない。
   `auto-edit-grep-location` / `compare-edit-dense-lines` の編集契約は
   **一切触らない** —— 原本の targeted Read は今まで通り成功する。
6. **Lock B の穴を塞がない。** cumulative-intake spec §3.3 が残した
   「targeted Read だけで 32 KB を取り込む会話に Lock B は何もしない」は
   **そのまま残る。** 塞ぐかどうかは、測った後の別の決定である。
7. **`--resume` をまたいで `session_id` が同じかどうかを確かめていない。**
   同じでなければ 1 会話の被覆が turn ごとに分かれ、**被覆率は系統的に低く出る。**
   実機でしか確かめられないので、**前提として書き、集計器に警告を出させる**
   （§6）。分かるのは最初の 1 run である。
8. **direct 腕は観測できない。** `evals/compare/run.sh:777-781`（と 825-828）は
   direct にだけ `--plugin-dir` を渡さないので、**direct ではこのフックが
   1 度も走らない。** したがって **「direct の coverage が 0」はプラグインの
   成果ではなく、計器がそこに無いという事実である。** 腕の比較に使ってはいけない
   （`source` 列の `<case>.direct.…` は原理的に行を持たない）。
9. **行数が変わらない Edit は見えない。** `total_changed` は `totalLines` の
   変化しか捉えないので、**Read → 同行数 Edit → Read** の並びでは旗が立たない。
   親が「現在の内容」を見ていない行があっても、被覆率は無印で 0.63 などと出る。
   **これは製品自身の中心フロー**（targeted Read → Edit）なので、稀な角ではない。
10. **行上限で切れた全文 Read は、刻み読みと同じ形で記録される。**
   `CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS`（run.sh は 25000 に固定）で
   切られた Read も `start`/`lines` は返ってきた分だけになる。
   **唯一の手掛かりは `full_file_reads` 列**（`offset` も `limit` も無い Read の
   本数、§6）であって、被覆率そのものからは区別できない。

## 9. 実装記録

**書いたファイル:**
- 新規: `plugin/hooks/record-coverage`（755）、`evals/test_record_coverage.py`、
  `evals/compare/read_coverage.py`、`evals/compare/test_read_coverage.py`
- 変更: `plugin/hooks/hooks.json`（PostToolUse/Read に `record-intake` の直後に
  6 行）、`evals/compare/run.sh`（`_claude_call` に export 1 行）、
  `evals/compare/test_runner.py`（テスト 2 件追加）

**テスト件数（最終レビュー修正を反映した現在値）:**
`evals/test_record_coverage.py` **23 件**（16 + 7）、
`evals/compare/test_read_coverage.py` **24 件**（13 + 11）、
`evals/compare/test_runner.py` に 2 件追加。リポジトリ全体は
`evals` **398 件**（3 skip）、`evals/compare` **809 件**、いずれも green
（`python3 -m unittest discover`。この環境に pytest は無い）。
CSV は **16 列**（§6）。**これらの数字は最終レビュー修正が全部入った後に
数え直したもの。** 途中の数字（Task 2 直後の 783 件、修正前の 16/13・391/798 件）を
最終値として使い回さないこと —— それが今回、一度そのまま spec に書かれて古くなった。
数字を直すときは**リポジトリ全体を grep する**（プラン側の期待値にも同じ数字が居た）。

**mutation で確かめたこと:**
- 行から `agent_type` を落とす → 自分のテスト 1 件だけが落ちる
- エラー行そのものを落とす → 自分のテスト 1 件だけが落ちる
- int 型チェックを緩める → 自分のテスト 1 件だけが落ちる
- hooklog を run 単位 1 本に固定する（call 単位をやめる）→ call 単位のテスト
  1 件だけが落ちる
- フックが書く行のタグ名を変える → エンドツーエンドだけが落ち、単体テスト 12 件は
  green のまま
- フックの `main()` を即 return させる → エンドツーエンドだけが落ち、単体テスト
  12 件は green のまま

**最終レビュー（通常・敵対）の真陽性修正:** フック 4 件（stdin を先に読む /
子の fd1・fd2 を塞ぐ / agent 2 フィールドの非文字列を `str()` で残す /
`file_path` を realpath で記録）、集計器 9 件（親と worker の rollup 分離 /
入力の事前可読性検査と `# NO COVERAGE ROWS` / `source` 列 / 多セッション警告を
ファイル単位に / 親行 0 件の警告 / `full_file_reads` 列 / `excluded` の 3 分割 /
rollup の `overlap`・`bytes` / CSV 先頭への rollup と但し書き）、
文書 6 件（§5 の無効時コストとログの副作用、§8.8-8.10、README）。
**閾値・判定列は足していない**（§8.4）。

**まだ 1 行もデータが無い。** 実機を回した run は 1 本も無く、`reviews/data/`
に read-coverage の CSV は存在しない。今回の作業に課金は発生していない
（§7 のテストは全部合成イベントで、実機 CLI を呼んでいない）。

**訂正（設計と実装の食い違い）:** `docs/superpowers/plans/2026-09-19-targeted-read-coverage.md`
の Task 5 は、`_merge` の隣接結合則を壊す mutation が
エンドツーエンドと `test_adjacent_reads_make_one_segment` の**両方**を落とすと予測し
「両方落ちるのが正しい」と書いていたが、これは誤りだった。実際に mutation を当てて
確認すると、落ちるのは `test_adjacent_reads_make_one_segment` だけで、
エンドツーエンドは PASS したままである。理由はエンドツーエンドのフィクスチャの
区間が 1-40、31-70、120-139 であり、31 <= 40 は重なり、120 > 70+1 は空隙で、
隣接（`start == 前区間の終端 + 1`）を一度も踏まないため。訂正はプラン側にも
入れ、両方の記述を直した（本節と併せて commit）。

**未検証の 2 つの境界:**
- エンドツーエンドは 1 セッション・`agent_id` が終始 null という構成でしか
  親/worker の区別を通していない。単体レベルの分岐は緑だが、
  worker 行が実配線で `parent=False` になるという**配線としての確認はまだ無い**。
- Bash 経由の逐次 targeted Read は依然として観測対象外である（§8.3）。
  `totalLines` が Bash の出力には存在せず、分母が取れないため。

**最初の実機 run が確かめる 2 点:**
(a) `--resume` をまたいで `session_id` が同じか（§8.7）。違えば集計器が
    stderr に警告を出す。
(b) worker の Read が `agent_id`／`agent_type` のどちらを載せて来るか。
    両方を記録しているので、最初に出す CSV の `parent` 列を見れば分かる。

**退避の手順（run ディレクトリが消える前に）:**

```bash
# run ディレクトリを消す前に。腕ごとに 1 ファイル。
python3 evals/compare/read_coverage.py \
    evals/compare/tmp/runs/run.*/transcripts/*.hooklog \
    > reviews/data/read-coverage-$(date +%Y-%m-%d).csv
sha256sum reviews/data/read-coverage-*.csv
```

`# NO COVERAGE ROWS` が先頭に出たら、その CSV には coverage 行が 1 本も無い
（direct 腕は §8.8 のとおり原理的にそうなる）。**入力が 1 本でも読めなければ
集計器は stdout に何も書かずに非ゼロで返る** ので、空 CSV を掴んだまま
run ディレクトリを消さないこと。

CSV は commit する。hooklog 本体はリポジトリに入れない（transcript と同じ
扱いで `~/measurements/` へ、sha256 つきで）。
