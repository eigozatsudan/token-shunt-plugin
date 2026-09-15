# 差し戻しの小規模再測定（2026-09-15、実測 $1.65 / 12実行）

`reviews/sendback-input-path-2026-09-15.md` で入力経路を
`last_assistant_message` に替えた版の再測定。仕様は
`reviews/sendback-trial-spec-2026-09-15.md` のまま、観測項目も変えていない。

**差し戻しは6回送られ、6回とも親が再開し、6回とも全行保持まで回復した。**

## 1. 実行条件

| 項目 | 値 |
|---|---|
| チェックアウト | scratchpad 内の detached worktree（専用、前回とは別） |
| 固定コミット | `983fcbe` |
| 事前確認 | `judge.py --selftest` 通過。`evals/compare` 322件中321件通過（既知の1件は §1.1） |
| 条件 | フック登録あり 2周 = 12実行 |
| 対照 | `sendback-trial-2026-09-15.md` の対照12実行を再利用 |
| 実測費用 | **$1.6466**（フック側のみ。対照は既計上の $1.6479） |

対照を再利用したのは、`688cbde` と `983fcbe` の差分が `evals/compare` に閉じており、
**`plugin/` が両コミットで完全に同一**だからである（`git diff` で確認）。
対照実行はフックを登録せず、判定器 `judge.py` にも差分は無い。

### 1.1 測定経路外の既知の差分

前回同様、24→12実行に収めるためチェックアウトの `cases.json` から
`direct` を外しており、その副作用で `test_aggregate` の
release-eligibility 検査1件が落ちる。測定経路外である。

## 2. 観測結果

### 2.1 block 送出

**12実行中6件**（各周3件）。周・ケース・モードの内訳:

| 周 | ケース | モード | フックの記録 | `gold_confirmed` |
|---|---|---|---|---|
| 1 | auto-explicit-multifile | auto | `blocked(3行)` → `reblock_suppressed` | pass |
| 1 | auto-explicit-multifile | haiku | `no_block`（子側の欠落） | fail |
| 1 | auto-explicit-multifile | sonnet | `no_block`（子出力取得不能） | fail |
| 1 | compare-explicit-multifile | auto | `blocked(4行)` → `reblock_suppressed` | pass |
| 1 | compare-explicit-multifile | haiku | `blocked(4行)` → `reblock_suppressed` | pass |
| 1 | compare-explicit-multifile | sonnet | `no_block`（子出力取得不能） | fail |
| 2 | auto-explicit-multifile | auto | `early_stop` → `blocked(7行)` → `reblock_suppressed` | pass |
| 2 | auto-explicit-multifile | haiku | `no_block`（子側の欠落） | pass |
| 2 | auto-explicit-multifile | sonnet | `no_block`（子出力取得不能） | fail |
| 2 | compare-explicit-multifile | auto | `blocked(3行)` → `reblock_suppressed` | pass |
| 2 | compare-explicit-multifile | haiku | `blocked(3行)` → `reblock_suppressed` | pass |
| 2 | compare-explicit-multifile | sonnet | `no_block`（保持 ok） | pass |

判定不能・子側の欠落・保持 ok の実行に block を送ったものは**0件**。

### 2.2 親の再開

**6件中6件で `resumed`。** 判定は仕様 §4.1 のとおり、block 時点に記録した
親の assistant 応答数・ツール呼び出し数と、実行後の同じ数の比較による。
transcript 行数は補助情報にとどめた。`原因不明` は0件である。

### 2.3 保持の回復

**6件中6件で、差し戻し時に欠けていた行が全て戻った。**

| 周 | ケース/モード | block 時の欠落 | 再開後の保持 | 再開後の欠落 |
|---|---|---|---|---|
| 1 | auto/auto | 3 | 3 | 0 |
| 1 | compare/auto | 4 | 4 | 0 |
| 1 | compare/haiku | 4 | 4 | 0 |
| 2 | auto/auto | 7 | 7 | 0 |
| 2 | compare/auto | 3 | 3 | 0 |
| 2 | compare/haiku | 3 | 3 | 0 |

この判定は `gold_confirmed` とは独立に、子の `confirmed:` 行と
再開後の最終回答を突き合わせたもの（逐語一致）である。

参考として `gold_confirmed` は**対照 12実行中1件 → フック 12実行中8件**。
block を送った6件はすべて pass になった。残る fail 4件は
子側の欠落2件と子出力取得不能2件で、いずれも親の差し戻しの対象外である。

### 2.4 再ブロック抑止・上限

block を送った6件すべてで、直後に `stop_hook_active` が真の起動が1回あり、
フックは規約どおり成功を返した（`再ブロック抑止` 6件）。
**`上限到達` は0件。** CLI の既定上限は8回で、到達時は
「A hook blocked the turn from ending N consecutive times」を出すが、
今回その証跡は出ていない。1回の差し戻しで足りたため上限に近づいていない。

### 2.5 子の完了前の Stop

`early_stop` 1件（周2 `auto/auto`）。子が走っている間の停止であり、
未着の報告を保持違反に数えずに済んでいる。同じ実行はその後 block され、
再開して全行を保持した。

### 2.6 費用とターン数

`観測差`（同一ケース・同一モード、各条件2周の平均）:

| ケース | モード | ターン | 費用 |
|---|---|---|---|
| auto-explicit-multifile | auto | 6.0 → 3.0 | $0.1354 → $0.1276 (−$0.0078) |
| auto-explicit-multifile | haiku | 3.5 → 6.5 | $0.1218 → $0.1177 (−$0.0040) |
| auto-explicit-multifile | sonnet | 1.0 → 3.0 | $0.1593 → $0.1406 (−$0.0187) |
| compare-explicit-multifile | auto | 6.0 → 6.5 | $0.1209 → $0.1401 (+$0.0192) |
| compare-explicit-multifile | haiku | 5.5 → 6.5 | $0.1185 → $0.1371 (+$0.0186) |
| compare-explicit-multifile | sonnet | 5.5 → 5.0 | $0.1681 → $0.1601 (−$0.0080) |

平均の観測差は**ターン +0.50、費用 −$0.0001**。周回間ばらつきは
対照が ターン中央値0.5・最大5／費用中央値 $0.0066・最大 $0.0214、
フック側が ターン中央値1.0・最大2／費用中央値 $0.0130・最大 $0.0603。

`直接観測` は block 送出6回・再開6回。差し戻しが6回起きているので、
今回の観測差は**差し戻しの再生成分を含む**。ただしその大きさは
周回間ばらつきに埋もれており、**この n（セルあたり各条件2件）では
差し戻し1回あたりの費用を分離できない**。
`sendback-scope-2026-09-15.md` §4.2 の推定（中央値 $0.0136）と
矛盾しないが、裏づけにもならない。

## 3. 判断

- **差し戻しは実機で成立する。** 送出6件、再開6件、全行回復6件。
  `原因不明` 0件、誤って送った実行0件。
- 回復は1回の差し戻しで足りており、再ブロック上限には触れていない。
- 数値は**母数つきの観測値**であり、一般的な回復率ではない。
  セルあたり各条件2件、合計フック12実行の規模である。
- 親が回復しても、子側の欠落（2件）と子出力取得不能（2件）は残る。
  これらは Stop の差し戻しでは扱えない（`sendback-scope` §2.1）。

## 4. 残件

| 項目 | 状態 |
|---|---|
| 製品実装（`plugin/hooks/hooks.json` への登録） | 未実施。今回もフックは登録していない |
| 差し戻し1回あたりの費用 | 分離できていない。測るなら別設計が要る |
| 子側の欠落への対処 | SubagentStop か再委譲。未着手 |
| 破棄経路の実発生率 | 今回は全件再開したため観測されていない |
| Grep フック2件 | 設計済み・実装保留 |
