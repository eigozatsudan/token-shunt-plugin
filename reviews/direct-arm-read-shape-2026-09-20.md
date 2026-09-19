# プラグイン無しの親はファイルをどう取り込むか（アーカイブ 55 会話、$0）

`docs/superpowers/specs/2026-09-20-transcript-coverage-design.md`
（transcript 側の被覆率計器）を書くにあたり、**先に direct 腕の
transcript を見るべきだった。** 見た結果、spec の動機が成り立たないと
分かったので spec は取り下げた（§4）。ここに残すのは、そのとき $0 で
出た実測である。

行データ: `reviews/data/direct-arm-read-shape-2026-09-20.csv`
（sha256 `e7a2f03af5a00b657647768c2ba65ddf6f97b15c33ba055cef0c6e83335f2cc4`、199 行）。
再現スクリプト: `reviews/data/direct-arm-read-shape-2026-09-20.py`。
入力は `~/measurements/token-shunt/*.tar.gz` の 5 ブロック
（cap-overflow 2026-09-19、multiturn-context / plan-phase-routing /
subthreshold-cost / subthreshold-routing 2026-09-18）。
**新しい run は 1 つも買っていない。**

## 1. 数え方

新しいパーサを書いていない。

- 親の Read は `parent_turn_reads.read_rows` が返すものだけ。
  これは `parent_tool_use_id is not None` を落とし、**`is_error` の
  tool_result を落とす** —— 拒まれた Read を親の取り込みに数えない。
- corpus の根は `parent_turn_reads.derive_root`（`/work/fixtures/` で分割）。
  プラグイン自身のファイルを読んだ分は入らない。
- 会話の単位は `<case>.direct.jsonl` とその `.turnN.jsonl`。
- 「切片」は `offset` または `limit` が入っている Read のこと。

## 2. 出た数

```
direct conversations with >=1 parent corpus Read: 55
parent corpus Reads:                              199
rows (run, conversation, file):                   199
reads/row:                                        {1: 199}
rows with any offset/limit (a slice):               4
rows read more than once:                           0
```

**同じファイルを 2 度読んだ会話が 1 つも無い。**
199 回の Read が 199 個の (run, 会話, ファイル) に 1 対 1 で対応する。

切片は 4 回だけあり、すべて `django-multiturn-context.direct` で、
すべて**その 1 回きり**である（corpus は 5.2.1 / `bc833e8`）:

| run | ファイル | 範囲 | 全行 | その 1 回で取った割合 |
|---|---|---|---|---|
| run.Uj6yO7We | `db/migrations/writer.py` | 129 から 40 行 | 316 | 0.127 |
| run.L1DqGoOV | `db/migrations/writer.py` | 129 から 40 行 | 316 | 0.127 |
| run.L1DqGoOV | `db/migrations/operations/special.py` | 60 から 140 行 | 211 | 0.664 |
| run.BlFx27pa | `db/migrations/operations/special.py` | 64 から 100 行 | 211 | 0.474 |

残る 195 回は `offset`/`limit` 無し、つまり**全文で取っている**。

## 3. これが言っていること・言っていないこと

**言っている:** 妨げられない親は、corpus を**ファイル単位の一括で**取り込む。
切片を繋いで 1 ファイルを組み直す動きは、55 会話・199 Read で**0 回**だった。
これはこのプラグインが防いでいる形そのものの実測であり、
親コンテキスト汚染を「1 Read = 1 ファイル全文」で見積もってよいことを示す。

**言っていない:**

- **一般化しない。** 199 Read はすべて、このリポジトリが書いた
  `prompt_direct` に従った結果である。`prompt_direct` を持つ 37 ケースのうち
  **24 件が読み方に触れている**（`Read tool` / `consecutive range` /
  `offset` / `limit` /「全体」のいずれかを含む。例:
  「use consecutive ranges if needed」「ファイル全体を見ないと答えられない」）。
  `prompt_delegate` にはその指示が無い。
  **ここで測っているのは、モデルの素の読み方ではなく、この fixture の読み方である。**
- **切片 4 件を「部分読みの証拠」と読まない。** 4/199 で、いずれも
  1 回で止まっており、続きを取りに戻っていない。n が小さすぎる。
- 費用の話はしていない。主要指標は親コンテキストの汚染量である。

## 4. transcript 側被覆率計器（spec 2026-09-20）を取り下げた理由

spec は「プラグイン無しの親が targeted Read で corpus を組み直す形」を
測るために書いた。**その形が起きていない**（§2）ので、計器を作っても
`segments`・`overlap`・区間の和集合はすべて自明な値を出す。
通常レビューと敵対的レビューでさらに 4 点が出た:

1. **分母の在り処が消える。** `run.sh` の `gen_fixtures` は
   `rm -rf "$TMP"` を**モードごとのループの中**で実行する（`run.sh:747`、
   749 行の repo 自身のコメントが「corpus は mode ごとに staged される」と書く）。
   spec §1 は「run ディレクトリは corpus を抱えたまま残る」と書いており、**偽**。
   4/4 で合ったのは、今日の 3 run がいずれも 1 ケース × 1 モードだったからにすぎない。
2. **「新しいパーサを書かない」が守れていなかった。**
   `routing_checks._returned_range`（`routing_checks.py:104`）が
   `\t` と `→` の両方・先頭空白・連番性・上限まで既に見ている。
   spec が提案した `N\t` 固定の解析は、
   このリポジトリ自身のテスト fixture（`test_flow_checks.py:29`,
   `test_judge_integration.py:72`）が使う `→` 形式で**無言の 0.0** を出す。
3. **検証ゲートの公差が間違っていた。** §4 は正しく「桁数 + 1 B/行」と書き、
   §5 は「4 B/行」と書いていた。**訂正のために書いた検証手順の中に
   古い定数が残る**という、既に 1 度やった形である。
4. **`total_changed` は transcript 側では構造的に常に 0**、
   `read_rows` が返すキーは `file_path` ではなく `path`、
   `origin` 列は `read_coverage.py` に存在しない。

偽陽性として棄却したもの: 「`gen/edit_hint.py` の分母は入手不能」。
生成器（`run.sh:325-338`）は決定的で、再生成すると `newlines + 1 = 401` と
hook の記録に一致し、288-292 行も transcript の `tool_result` と一致する。
なお **`totalLines = 改行数 + 1` の規則は敵対的レビューの攻撃に耐えた**
（こちらの hook 記録 4/4 と、レビュー側が別に取った標本の両方で一致）。
**この規則だけは生きている。** 標本数は §5 の訂正対象の走査から取ったので
ここでは引かない。

## 5. 訂正

このブロックの途中で「41 会話・123 Read、切片 0、全件 coverage 1.000」と
一度書いた。**その走査はアーカイブ 5 ブロックのうち一部しか見ていなかった。**
全ブロックを走らせた値が §2 の 55 会話・199 Read であり、切片は 0 ではなく 4 件ある。
結論（同一ファイルの再読 0 件）は変わらないが、
「全件が全文読み」は誤りで、正しくは 195/199 である。

## 6. 次に direct 腕の読み方を測るなら

`prompt_direct` が読み方を指示していないケースを作ることが先である。
**計器を作り直すのではなく、fixture を直す。**
それをやるまで、被覆率という量は direct 腕について何も言えない。
