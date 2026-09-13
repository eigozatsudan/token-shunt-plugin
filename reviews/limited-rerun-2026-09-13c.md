# 限定実機再実行 2回目（2026-09-13, run.5iqYfCeg）

指示・判定器修正後、同じ10ケース19実行。**13 pass / 9 fail**（前回 run.Dxreyefr は 7 pass / 12 fail）。

## 効いた修正

**descriptionへの数値閾値が reader の委譲不発を解消した。** 3実行→1実行。

- `auto-one-line/sonnet`・`auto-one-line/auto` — pass。
- `auto-bulk-facts/haiku` — 親が全文Readを試みてフックに拒否され、Skill→Agent と委譲。前回は Grep で完結していた。
- `compare-explicit-multifile` の haiku/sonnet/direct、`writer-verification-levels` の表セル、`compare-code-writer-ok` も pass。

## 残る失敗 9実行

### 1. 子が拒否後に「絞らず先へ飛ぶ」（4実行・最大の残課題）

契約は「拒否されたら未読行から範囲を狭めて継続、先へ飛ばない」。実機では逆の動きが繰り返された。

| 実行 | 実際の Read 系列 | 逸脱 |
|---|---|---|
| auto-bulk-facts/haiku | 1–175, 176–350, **351–518 拒否**, 400–517, 350–399 | 351から狭めず400へ飛び、後から350を再読 |
| retry-policy/auto | 1–175, 176–350, **351–519 拒否**, 450–518, 351–450 | 同上。450行が1行重複 |
| reader-batch-ambiguous/auto | user.rb 1–183, **184–532 拒否**, 184–363, 450–532 | 364–449 が未読のまま |
| auto-bulk-facts/auto | 1–100, **100–199**, 400–499, 468–517, 200–299 (+別Agentで300–399) | offset=100 の1行重複、200–399を飛ばす、468–499重複 |

`offset=N` は N行目を**含む**ため、`最後に返った行 + 1` を守らないと必ず1行重複する。
auto の系列はこの off-by-one が起点になっている。

### 2. 委譲不発の残り1件（auto-one-line/haiku）

description の閾値は届いている。親は全文Readを試み、フックに拒否された上で、

> 「the file was a single 68KB line (exceeds the bulk-reader threshold), but the key/value was extractable directly without needing the full contents」

と明示的に閾値超えを認識しながら Grep で完結させた。指示の不足ではなく、
「Grep で足りるなら委譲は不要」という判断がフックも description も上書きしている。
§15 の既知の限界（Grep はフックされない）が実機で再現した形。

### 3. `compare-edit-dense-lines/auto` — 精度 fail（KM-4w5v6 未取得）

親は正直に partial を報告しており、動作は契約どおり。
40000行のファイルに対し、子は Grep を持たず **6 Read 上限**で region サンプリング
（1, 9990–10009, 19950–20049, 29990–30009, 39999–40000）を行い KEEP_MARK に到達できなかった。
親は「編集位置特定以外で Grep を使わない」規則を守って探索を止めている。
6 Read 上限と「子に Grep なし」の組み合わせが、この規模では解けない質問を作る。
上限値か、子の探索手段か、ケースの期待値のいずれかを決める必要がある。

### 4. `compare-explicit-multifile/auto` — `confirmed:` の形式崩れ

内容は正答。`after_create :send_welcome_email` を述べた後に
`(confirmed: \`user.rb\`)` と**末尾の括弧**に置いたため、
`confirmed: <パス> — <事実>` の項目形式に一致しない。相対名・バッククォート付き。
他3モードは pass しているので、形式指定の位置づけを強める余地がある。

### 5. `writer-verification-levels/auto` — `control_trunc.json`

表セルが `failed/error, partial` と両論併記になっている。
切り詰めJSONは failed に確定すべきで、partial を併記した時点で対照の意味が消える。

## 証跡

`evals/compare/tmp/runs/run.5iqYfCeg/`、ログ `/tmp/token-shunt-rerun-2.log`
