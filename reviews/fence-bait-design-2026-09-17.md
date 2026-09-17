# 送り返しの機構を誘発 case で測る・事前登録（2026-09-17）

`reviews/fence-prevalence-2026-09-17.md` の続き。**走らせる前に本記録をコミットする。**

## 1. なぜ自然発生を待つのをやめるのか

前段で自然発生率は **1/81 = 1.2%、Wilson 95% 上限 6.7%** と出た。
**この率で効果測定は組めない。** control 腕に 5 件出すには 400 run 前後、
**$70 以上**かかる。**残額 $6.4 でも、総枠を倍にしても届かない。**

**事象を待つのをやめ、事象を作る。**
測る対象が変わることを先に明記する:

| | |
|---|---|
| **測る** | **送り返しの機構が実機で効くか**（フェンスが出た報告は言い直されるか） |
| **測らない** | **母集団での効果率。** それは 1.2% の側の問題であり、本測定は答えない |

**本測定の数字を「製品の何割が直る」に読み替えてはならない。**

## 2. 誘発の根拠（観測された 1 件）

唯一のフェンス run `run.9ooxkL0s`（`redmine-last-helper`、worker は haiku）の
最終報告:

```
confirmed: .../application_helper.rb — last method is `autocomplete_data_sources` defined at line 1974

The exact def line is:
<fence>
  def autocomplete_data_sources(project)
<fence>

status: complete
stop_reason: entire file read, last method identified
```

**答えは prose で正しく出ており、その後に「念のため」で def 行を貼っている。**
**違反は誤答ではなく装飾である。**

したがって誘発は「行そのものを答えにする」のではない
（それは違反を指示することになり、測定にならない）。
**装飾したくなる問いにする** — **引数名を訊く。**
引数名は prose で答えられる（「引数は project ひとつ」）が、
**def 行を見せるのが最も手早い**。

## 3. 誘発 case（事前に 2 案を固定する）

どちらも fixture は `redmine/app/helpers/application_helper.rb`、
suite X、`modes: ["auto"]`、`gold_any: ["autocomplete_data_sources"]`、
`expect.delegate` は `redmine-last-helper` と同一（`child_no_body: true`,
`agent_type: token-shunt:bulk-reader`, `child_msg_max: 4000`）。
**正答の定義を既存 case と同じに保つ**ので、退行の比較ができる。

| 案 | 問い | 装飾の機会 |
|---|---|---|
| **V1** `fence-bait-helper` | 最後に定義されているメソッドの**名前・引数名・def 行の行番号** | 1 |
| **V2** `fence-bait-helper-3` | 最後に定義されている**3 つ**のメソッドについて、それぞれ名前・引数名・def 行の行番号 | 3 |

**2 案は今ここで固定する。見てから 3 案目を作らない。**

## 4. 手順と門（結果を見る前に固定する）

### 4.1 誘発の pilot（計器づくり、`SENDBACK=off`）

1. **V1 を 4 run。** フェンス run が **3/4 以上**なら V1 を採用し、**V2 は走らせない。**
2. 3/4 未満なら **V2 を 4 run。** **3/4 以上**なら V2 を採用。
3. **どちらも 3/4 未満なら、そこで止める。**
   **「誘発できなかった。機構は未検証のまま」と書いて終わる**（§7-5）。

**pilot は計器の較正であって outcome ではない。**
**pilot の run を本測定の control 腕にプールしない**
（採用された案は「フェンスが出たから」選ばれており、上振れした標本である）。

### 4.2 本測定（A/B）

採用した案で **`SENDBACK=off` 6 run / `SENDBACK=on` 6 run、合計 12 run。**
**run ごとに交互**（off, on, off, on, ...）に入れ替え、時間順の交絡を消す。
**結果を見て N を伸ばさない。**

## 5. N と枠

累計 **約 $93.6 / 上限 $100**、**残り約 $6.4**。
**本段階の上限 $4.5**、見込み **$3.0**。

1 run の見積り: `redmine-last-helper` の実測 **$0.1212/run**。
`SENDBACK=on` は worker のターンが 1 つ増えるので **$0.18** と見る。
pilot 最大 8 run + 本測定 12 run = **最大 20 run ≒ $3.0**。

**reserve は $0.70** — 直近ブロックの**最も高い 1 run $0.6721**
（`compare-edit-dense-lines`）を丸めたもの。**平均ではない**
（メモリ `billable-stop-rule-needs-a-mechanism`）。
**run ごとに `spend.py --cap 4.5 --reserve 0.70` を通し、exit 3 で抜ける。**

**走り終えても残額は $3 前後しかない。本測定の後、課金測定は続けられない。**

## 6. 計器

### 6.1 判定は judge が行う（フック自身ではない）

フェンスの有無は **`judge.py` の `has_code_fence`** が決める。
フックの `sendback_retention.check_code_fence` とは別実装であり、
**judge は本測定で変更しない。**

**「フェンス run」の定義:** その run の verdict が
`child_no_body: code fence in child message` で落ちていること。
`child_no_body` が別の理由で落ちた run は**数えないが、件数は記録する。**

### 6.2 フックが発火したかは別に読む

`SENDBACK=on` の run は `SENDBACK_TRIAL_LOG`（`run.sh:382-383`）に
記録が残る。**`outcome == "blocked"` かつ reason にフェンスを含む記録**を数える。

**「フェンスが消えた」と「フックが消した」は別の主張である。**
on 腕が 0 でも発火 0 なら、**効いたのはフックではない。**

## 7. 解析（走らせる前に固定する）と、外したときの書き方

**主要: フェンス run の割合、off 6 run 対 on 6 run、Fisher 正確検定（両側）。**
**6/6 対 0/6 なら p = 0.0022。** これが本設計の狙いである。

**副次、すべて事前に決めたもの:**

1. on 腕でフックが発火した run 数（§6.2）。
2. **`accuracy_any` を両腕で。** 定義は `gold_any` で既存 case と同一。
3. **`child_status` と `child_msg_cap` を両腕で。** ターンが増えて書式が壊れていないか。
4. **partial で終わった run 数**（`maxTurns` を使い切って言い直せなかった場合）。
5. 両腕の費用の**中央値を記述するのみ。検定はしない。**
6. **run ごとに解決された worker モデル**を記録する。
   観測された 1 件は haiku だった。**n=12 では効果と切り分けられない**ので、
   **記述するだけで検定しない**（§9）。

**中間解析はしない。** 採点器は**合成データでのみ**動作確認する
（前段 §12.1 で実データに当ててしまった。繰り返さない）。

**書き分けを先に決める:**

1. **on 腕でフェンスが消え、発火が 6 件**なら、「**送り返しの機構は実機で効く**」。
2. **消えたが発火 0 件**なら、「**消えた理由はフックではない**」。
3. **消えたが `accuracy_any` が落ちた**なら、
   「**これは修正ではなく別の壊し方である**」とはっきり書く。
4. **減らない**なら、「**送り返しは実機で効かなかった**」。
   **`6d2c9c2` は入れたまま、効かなかったことを記録する。**
5. **pilot で誘発できなかった**なら、§4.1 のとおり
   「**誘発できなかった。機構は未検証のまま**」で終える。**案を増やさない。**

## 8. 打ち切り

- 費用が枠に達したとき（`spend.py` が止める）。
- 計器が定義どおり動いていないと分かったときに限り中止してよく、
  そのときは**何が定義と違ったかを数字で示す**。
- **結果の向きや大きさは、止める理由にならない。**

## 9. 事前に認めている弱点

- **母集団の効果率ではない**（§1）。**誘発 case は自然な問いの標本ではない。**
- **case は 1 つ、fixture は 1 つ、問いの形も 1 つ。**
- **採用案は pilot で「出たから」選ばれる。** 選択バイアスは構造的に入る。
  **だからこそ主張を「機構が効くか」に限定している。**
- **worker モデルが run ごとに変わり得る**（`--worker-model auto`）。
  n=12 では分離できない（§7-6）。
- `SENDBACK=off` は eval の baseline 設定であり、**on 腕は baseline ではない**。
  **ここで得た数字を他の測定の baseline と並べてはならない。**
- 費用も挙動も**今日のモデル価格・今日のモデル**に依る。

## 10. 残すもの

**run ディレクトリを消す前に**
`reviews/data/fence-bait-2026-09-17.csv` にコミットする
（メモリ `keep-per-pair-rows`）。列:

`run`, `phase`（pilot/main）, `case`, `sendback`, `fenced`,
`child_no_body_reason`, `hook_blocked`, `accuracy_any`, `child_status`,
`child_msg_cap`, `status_partial`, `worker_model`, `cost_usd`

**`pairs.py` は今回も使えない**（auto 腕のみ）。**3 回続けてである。**
**本測定の後に直す。測定中は触らない。**

## 11. preflight

1. 専用チェックアウトを**本記録のコミット**に固定、生成物を除いて clean。
2. **その中で `judge.py --selftest` 全項目 pass。**
3. **case を足すので、`evals/compare` のテストを全件通してから走らせる**
   （catalog の検証を含む）。**case 追加はテストが通ってから。**
4. **run 計数に summary.json の substring 一致を使わない**
   （前段 §6.1 で 3 case を落とした）。**`summary.json` の `cases` キーを読む。**
