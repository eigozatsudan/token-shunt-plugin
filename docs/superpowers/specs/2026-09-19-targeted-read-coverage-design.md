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

- **親と worker を混ぜない。** 別行として出し、合算しない。
- **`total` が途中で変わったら（間に Edit が入った）`total_changed` を立て、
  その行を率の rollup から外す。** 平均に黙って混ぜない。
- **`covered > total` になったら `impossible` を立て、率を出さない。**
  `check-reader-contract:143` が `start+count-1 <= total` を妥当性条件に
  使っている。破れたのはデータが壊れた合図であって、1.4 という被覆率ではない。
- **`rollup` は除外件数（`excluded`）を必ず出す。** `total_changed` の除外は
  **編集の多い会話を系統的に落とす** —— 残った母集団は「読んで終わった会話」に
  偏る。件数を出さないと、その偏りが見えない。
- **`coverage` は「親が何をしたか」であって、成果でも費用でもない。**
  高い被覆率が良いとも悪いとも、この計器は言わない。
  **低い被覆率も同様である** —— 刻み読みで 30% だけ取った親（汚染）と、
  Grep で要約だけ取った親（健全）を、この計器は**区別しない。同じ 0.30 に見える。**
  本文にそう書くだけでは足りないので、**`rollup` の出力自身に
  「これは順位ではない」と 1 行刻む。**
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
