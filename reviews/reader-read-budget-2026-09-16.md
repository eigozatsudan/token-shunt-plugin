# ワーカーの Read 予算切れ（2026-09-16）

`reviews/auto-bulk-facts-isolation-2026-09-16.md` §6 が「先に潰すべき」と指した
予算切れ再試行の調査と修正。**課金なし。** 材料は `9346d19` の保存済み
トランスクリプト（`run.f07a97OR` / `run.pCbVjjT9`、ケース 77 本、ワーカー起動 33 本）と
フック本体のみ。

## 1. 機構

`plugin/hooks/check-reader-contract` の予算は 1 invocation あたり Read 6 回。
`state['calls'] += 1` は予算判定の直後、他の全チェックより前にあるので、
**フック自身の拒否も 1 回分を消費する**（`A rejected request also consumes budget`、
ハンマリング防止として意図的）。

そこに CLI の上限が重なる。`File content (62702 tokens) exceeds maximum allowed
tokens (25000)` で失敗すると `cursor['retry'] = max(1, count // 2)` が立ち、
**修正前は次の Read がその値ちょうどでないと拒否された**。

## 2. 実測（`auto-bulk-facts.auto` の 1 本目、518 行 / 65669 B）

| # | 要求 | 結果 |
|---|---|---|
| 1 | `limit=2000` | CLI 上限（62702 tok） |
| 2 | `limit=100` | フック拒否 `Retry at offset=1 with limit=1000` |
| 3 | `limit=1000` | CLI 上限 |
| 4 | `limit=500` | CLI 上限（59228 tok） |
| 5 | `limit=50` | フック拒否 `Retry at offset=1 with limit=250` |
| 6 | `limit=250` | 成功（1–250 行） |
| 7 | — | `Read budget exhausted` |

半減の梯子 2000→1000→500→250 を歩かされ、さらに自分から**小さい**値
（100、50）を出すと拒否されて 2 回失った。読めたのは 518 行中 250 行。

## 3. 33 起動の統計

| 最初の Read の `limit` | 起動数 | 予算切れ | 平均 Read 回数 |
|---|---|---|---|
| 指定なし | 19 | **0** | 3.3 |
| 250 超（2000 / 424 / 400） | 7 | **3** | 5.7 |

Read 全 108 回のうち CLI 上限エラー 28、フック拒否 12。予算切れ 3 件はすべて
`bulk_facts.py`、すべて `limit=2000` 始まり。`limit` を付けない Read は CLI が
黙って途中（この file では 175 行）まで返し、契約フックはそれを受けて
`next=176` に進める。成功したワーカーは全部この経路だった。

予算 6 が小さすぎるのではなく、**最初の `limit` の選び方で決まっていた。**

## 4. 修正

### A. ワーカー指示（`plugin/agents/bulk-reader.md`）

「パスの最初の Read は `limit` を付けない。ランタイムが自分で切り詰め、
カーソルは実際に返った行から進む。大きい当て推量の limit はランタイムに拒否され、
半減 1 段ごとに 1 回を失う。limit は拒否後の継続にだけ付ける」を明記。
併せて、半減後の値が**上限**であること（少ないのは可、多いのは拒否）を書いた。

テスト: `evals/test_reader_call_contract.py::SkillDocumentTests::
test_agent_tells_the_worker_to_open_a_path_without_a_limit`。

### B. 半減値を上限にする（`plugin/hooks/check-reader-contract`）

`limit != cursor['retry']` → `limit is None or limit > cursor['retry']`。
指定より少ない要求は通す。少ない要求が本文を余計に引くことはないので、
拒否する安全上の理由がない。`limit=None`（残り全部）は「少ない」ではないので
従来どおり拒否。文面は `... (floor half) or less.` に変えた。

テスト（フック側）: `evals/test_reader_contract.py` に3件
— 半減未満は通る／半減未満が失敗したらそこから半減する／`limit=None` は拒否。

判定器側も同じ規則に合わせた（`evals/compare/routing_checks.py`）。
`count != retry_limit` → `count is None or count > retry_limit`。
拒否文面の照合は `( or less)?` を足して**新旧どちらの文面も**認識する
— `9346d19` などの保存済みトランスクリプトを再判定できなくしないため。
既存 `test_routing_checks.py::test_bounded_refusal_halves_at_the_same_cursor` の
`(101,49,False)` 期待（半減未満は違反）は、新しい規則に合わせて合格側へ移した。

## 5. 状態

オフラインは全部緑: `evals/run.sh` 240 pass / 0 fail、
`unittest discover -s evals/compare` 408 OK、`scripts/doctor.sh` ok。

**製品の挙動が変わるので、効果の確認には実機再測定（課金）が要る。**
今回は走らせていない。期待は「`limit=2000` 始まりでも梯子の各段で
ワーカーが安全側に降りられるようになり、予算切れ 3 件が減る」だが、
これは未検証の予測である。次の A/B のときに
`auto-bulk-facts` の予算切れ件数と `parent_added_utf8_bytes` を見ること。
