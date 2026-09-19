# `gold_confirmed` が 12 実行すべてで落ちた理由を名指しした（2026-09-20、$0）

`docs/superpowers/plans/2026-09-14-reader-protocol-reduction.md` §8.3 の終了条件 2 つの
うち 1 つ —— **`gold_confirmed` が `auto-explicit-multifile` の 6 実行すべてで
3 項目（`Notifiable` / `after_create` / `WelcomeEmailJob`）欠落** —— を追った。
`reviews/reader-protocol-reduction-2026-09-14.md` は
「退行ではなく既存の欠落」までは決着させたが、**どこで落ちたかは名指ししていない。**

当時それができなかったのは、原因を 3 つに分ける
`judge.gold_confirmed_source` が **2026-09-16（`9346d19` 以後）に入った**からである。
**新しい採点器は書いていない。** その関数をそのまま当て直しただけで、
入力は 2026-09-14 の probe が残した transcript
（`evals/compare/tmp/cost-probe/20260914-204044` と
`…/cost-probe-baseline/20260914-214327`、どちらも tracked ではない）。**$0。**

## 1. 原因は 36 件すべて同じ —— 親が worker のパスを捨てている

| | 実行 | 欠落 gold | `judge.gold_confirmed_source` の答え |
|---|---|---|---|
| 変更後（`bare`/`skill` 各 3 周） | 6 | 18 | **`parent dropped the worker's path` 18/18** |
| 変更前（同じ、`1ad21b0` の `plugin/`） | 6 | 18 | **`parent dropped the worker's path` 18/18** |

**worker 側は 12 実行すべてで正しい。** 毎回 3〜5 個の `confirmed:` 項目を返し、
3 つの gold すべてを**照合対象の絶対パス付き**で確認している。例（`bare.1`）:

```
confirmed: /…/fixtures/rails/app/models/user.rb — User class includes the
Notifiable concern (line 2) and defines an after_create callback …
```

**親の最終回答に `confirmed:` 項目が 1 つも無いのが 12 実行中 10。**
残る 2（変更前の `skill` rep1/rep3）は 4 項目あるが、引用元が `user.rb` のような
basename で、`item_citations` が拾う絶対パスではない。
**どちらの形でも「親が落とした」である。**

つまり `reader-protocol-reduction` が動かした範囲（deny に契約を載せる）と、
この終了条件が測っているもの（親が worker の bullet を最終回答へ運ぶか）は
**同じ親の振る舞いであり、変更前後で 18/18 と 18/18、まったく動いていない。**

## 2. ただし、その指示は 6 実行中 5 実行で親に届いていない

親に「worker の `confirmed:` bullet を絶対パスごと残せ」と言っている唯一の場所は
`plugin/hooks/reader-call-contract` の最終行である:

> In your final answer keep each confirmed bullet with its full absolute
> path, unabbreviated.

**この行は契約の初出コミット `0f99da5` から入っている**（後付けではない）。
そして契約は **deny に載って届く。**

**12 実行で deny は 1 度も起きていない。**

| 実行 | `parent_reads` | hooklog | 契約の到達 |
|---|---|---|---|
| `bare` ×3 | **0** | `check-file-size` が worker の 3 read を pass、deny 0 | 無し |
| `skill` rep2/rep3 | **0** | 同上 | 無し |
| `skill` rep1 | 1 | 同上 | **契約ファイルを自分で Read した** |

親は **1 度も Read を試みていない**（プロンプトが 3 パスを名指しし、
`wm_hint` が委譲を示唆するので、そのまま委譲した）。
サイズゲートを踏まないので deny が出ず、契約も出ない。
`skill` rep1 だけが契約ファイル本体を Read しているが、
受け取ったのは **`{REASON}` / `{PATHS}` が未展開のテンプレート**であって、
deny として描画されたものではない。

**この終了条件は、それが試す指示が届かない経路で採点されていた。**

## 3. 2026-09-14 の再判定は相対 `fixture_root` で走っていた

同じ transcript を当時の `rejudge.*.json` のまま採点すると、原因は
`worker cited no matching absolute path` と出る。**これは誤りである。**

- probe 本体は絶対パスで走っている（`report.json` の `source_fixtures`、
  worker の引用、hooklog の `file_path`、いずれも `/home/dev/…`）。
- **`rejudge.*.json` の `fixture_root` だけが相対**
  （`evals/compare/tmp/cost-probe/20260914-204044/fixtures`）。
- `gold_path_needles` は相対 needle を作り、`item_citations` は絶対パスしか拾わない。
  **積集合は構造的に空になり、どんな完璧な回答でも `gold_confirmed` は通らない。**

**上位の判定（× / 6 実行とも失敗）は生き残る** —— 親は実際に適格な項目を
1 つも出していないので、絶対パスに直しても落ちる。
**壊れていたのは理由の方である**（§1 の表は絶対パスに直して取り直した）。
`reviews/reader-protocol-reduction-2026-09-14.md` の
「worker の引用元が相対ファイル名だった」という付随所見は、**この artifact である。**

## 4. 判断が要る（$0 では決まらない）

**この終了条件を今のまま残すなら、親が deny を踏まない委譲でも保持契約を
見られる場所に置く必要がある。** 選べるのは概ね 2 つで、どちらも出荷物を触る:

1. **保持要件を deny の外にも置く。** `bulk-reader` SKILL.md は
   description に「Copy each worker `confirmed:` line into the final answer
   verbatim」と持っているが、**`bare` 条件は skill を読み込まない。**
   §8.3 のもう 1 つの終了条件が「Skill 読み込み 0 回」を目標にしている以上、
   **skill に置くのは目標と衝突する。**
2. **終了条件の範囲を deny が出た実行に限る。** 今の測り方は
   「契約が届いていない親が契約に従わなかった」を数えている。

> **後記（同日、$0）。選択肢 1 は既に出荷されていた。**
> `7f5fb43`（2026-09-16）が worker 起動時に保持要件を述べており、
> その docstring はここと同じ穴を名指ししている。**作るものは無かった。**
> ただし**効いていない** —— リマインダ到達後の 213 ターン中 108 で
> 親は worker の `confirmed:` 行を落としており、うち 98 は全滅である。
> さらに、それを直す send-back は評価ハーネスでは既定 off
> （`evals/compare/run.sh:396`）で、アーカイブで 1 度も発火していない ——
> **これは 2026-09-15 の意図された設計判断であり**（登録判断 §3.4）、
> **差し戻し自体の実効性は 6/6・`gold_confirmed` 1/12→8/12 で測られている。**
> —— `reviews/retention-after-reminder-2026-09-20.md`

**どちらも設計判断なので、ここでは実装していない。**

## 5. これが言っていないこと

1. **n=12、1 ケース、1 プロンプトである。** `auto-explicit-multifile` は
   3 パスを名指しするプロンプトで、**委譲が最初から自明**という形をしている。
   パスを名指ししないケースなら親は Read を試み、deny が出る可能性がある。
   **「deny は起きない」ではなく「このケースでは起きなかった」。**
2. **`cost_probe` の `direct`/`bare`/`skill` は `run.sh` の
   `direct`/`auto` モードとは別物である。** 実機のゲートでこのケースが
   どう出るかは、ここでは測っていない。
3. **課金していない。** 既存の transcript を読み直しただけである。
