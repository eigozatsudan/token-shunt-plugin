# 被覆率計器をアーカイブ全体に当て直した（239 会話、2026-09-20、$0）

`reviews/read-coverage-2026-09-20.md` は実機 3 本（$1.7261）で、
**「親がスライスを繋いでファイルを組み立てた例は 1 つも無い」**と書き、
同じ節で **「n=3 である。率でも傾向でもない」**と断った。
その n を、課金せずに 239 会話へ広げた。

行データ: `reviews/data/read-coverage-archive-2026-09-20.csv`
（24 行、sha256 `4eec9d2bba4cf48332ee366e34d3a85cb13ecb4c80d995cd90b46f72e03eb727`）。
再現スクリプト: `reviews/data/read-coverage-archive-2026-09-20.py`。
入力は `~/measurements/token-shunt/*.tar.gz` の 5 ブロックと
`~/measurements/coverage-2026-09-20/` の 3 run —— `intake-replay-wide` と同じ母集団である。

## 0. 新しい集計器を書いていない

区間の和集合・グループ化・rollup は**出荷している
`evals/compare/read_coverage.rows` / `.rollup` そのまま**である。
新しいのは adapter 1 つだけで、transcript の `tool_use_result.file` から
フックが `tool_response.file` から取るのと**同じ 3 フィールド**
（`startLine` / `numLines` / `totalLines`）を組み立てる。

**この adapter は実機 3 本でフック由来の CSV を完全に再現する:**

| | files | reads | covered | total | coverage | overlap | full_file_reads |
|---|---|---|---|---|---|---|---|
| フック（`reviews/data/read-coverage-2026-09-20.csv`） | 2 | 2 | 35 | 718 | 0.0487 | 0 | 0 |
| **この adapter（同じ 3 run）** | 2 | 2 | 35 | 718 | 0.0487 | 0 | 0 |

行単位でも一致する（`writer.py` 30/317 `segments=1`、`edit_hint.py` 5/401 `segments=1`）。
**`bytes` 列だけは再現せず、CSV から外した** —— フックは配信された本体を数え、
transcript はその写しを持つ。他の全列は一致する。

> **書いている途中で 1 度外した。** adapter から `offset`/`limit` を落としたら、
> `read_coverage.rows` は 2 行とも `full_file_reads=1` と数えた（フックは 0）。
> **全文/スライスの内訳が丸ごと逆になる取り違えである。**
> 検証をフックの CSV に当てていなければ気付かなかった。

## 1. 数字

親の corpus Read 26 回、`(会話, ファイル)` 24 行。**`totalLines` の欠けた読み取りは 0 件、
除外も 0 件**（サイズ変化・不可能値・分母なし、いずれも無し）。

```
rollup:  files=24 reads=26 covered=2031 total=5958 coverage=0.3409 overlap=0
whole-file  rows=6   reads=6   covered=1393  total=1393  rate=1.0000
sliced      rows=18  reads=20  covered=638   total=4565  rate=0.1398
```

- **全体 0.3409 は混ぜた数字である。** 全文 Read 6 本が定義上 1.0 に張り付いて引き上げている。
- **targeted Read だけを見ると 0.1398。** 18 行 20 回の targeted Read が、
  触れたファイルの **14%** を回収した。
- **`overlap=0`。** アーカイブ全体で、同じ行が 2 度親に入った例は 1 行も無い。

`reads` の分布は `{1: 22, 2: 2}`、和集合後の `segments` は `{1: 23, 2: 1}`。

## 2. 逐次回収は「0」ではなく「24 行中 2 行」だった

実機 3 本では 0 だったが、**アーカイブには 2 例ある。** 数字を弱める方向の訂正である。

| run | ファイル | reads | covered/total | segments | 何が起きたか |
|---|---|---|---|---|---|
| `run.L1DqGoOV` | `special.py` | 2 | 110/212 = **0.519** | **2** | 1 ターン内で離れた 2 区間を取った |
| `run.sM7k6XGD` | `migration.py` | 2 | 100/240 = **0.417** | 1 | **turn 2 と turn 5** の 2 回が連続していて 1 区間に融合した |

**2 例目はターンをまたいでいる。** `read_coverage.rows` が hooklog 名ではなく
会話でグループ化する（`ac8c1b3`）と決めていなければ、この行は
**0.21 が 2 行**に割れて、実際に回収された 0.417 はどこにも出なかった。
docstring が「sequential recovery across turns is what this instrument is for」と
書いた設計判断は、**実データで 1 度だけ効いている。**

同時に、**上限も出た。スライスから組み立てた最大は 0.519 である。**
アーカイブのどの親も、刻み読みでファイルの過半を超えて回収してはいない。

## 3. `read_coverage.py` の docstring が事実に反していた

> It parses no transcript: the denominator (totalLines) is in the hook
> event and nowhere else, so the input is the hook's own log.

**`totalLines` は transcript にもある**（`tool_use_result.file`）。
26 回の親 corpus Read すべてに載っていて、欠損は 0 だった。
この一文が「アーカイブでは測れない」という前提を作っていたので、直した。
**フックが不要になったわけではない** —— フックは実機の観測点であり、
transcript 経路は事後の $0 再生である。訂正したのは「nowhere else」だけである。

## 4. これが言っていないこと

1. **腕の比較をしていない。** direct 腕はプラグインを読み込まないので
   フックが走らず、transcript 経路でも `agent_id`/`agent_type` が無い。
   ここにあるのは **auto 腕の親だけ**である。
   `reviews/direct-arm-read-shape-2026-09-20.md` の direct 199 Read（195 が全文）とは
   **母集団も計器も違う。並べて引き算しない。**
2. **worker を集計していない。** 親判定に transcript は `parent_tool_use_id` を使う
   （フックは `agent_id`/`agent_type`）。worker の被覆率は設計上 1.0 に張り付く（spec §6）。
   なお worker の corpus Read 739 回のうち **刻み読みは 1 回**で、
   **同じ worker が同じファイルを 2 度読んだ例は 0 件**だった。
3. **ケースが少ない。** 24 行のうち 19 行が `django-multiturn-context`、
   3 行が `subthreshold-routing`、2 行が実機 3 run 由来である。
   **239 会話のうち親の corpus Read があるのは 13 本だけ**で、
   `n=239` は独立な 239 問ではない（`intake-replay-wide` §4 と同じ制約）。
4. **閾値を出していない。** spec は「線を引く根拠になる実測は 1 本も無い」と書いた。
   本測定は分布を 1 つ与えたが、**24 行・6 ケースの分布から線を引くのはまだ早い。**
