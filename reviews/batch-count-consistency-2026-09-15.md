# `4+ paths` と `File count alone is not a trigger` の整合性（整理、未適用）

`reviews/repeat3-2026-09-15.md` §5 / `reviews/residual-two-2026-09-15.md` §4 の
設計確認事項。追加の課金測定は行っていない。

## 1. 二つの文言

| 置き場所 | 文言 | 何を規定しているか |
|---|---|---|
| description（常時文脈） | `Also use for explicit delegation with no hook deny, batch boundaries (4+ paths, cross-file relationships), ...` | **スキルを参照する場面**の列挙 |
| 本文 1.（§26.2） | `File count alone is not a trigger.` | **ルート判断**（委譲するか親で読むか）の基準 |
| 本文 2.（バッチ） | `One invocation = at most 3 explicit paths. ... 4+ paths → split into batches of 3` | **委譲すると決めた後**の分割規則 |

規定している層が違うので、**本来は矛盾しない**。
`4+ paths` は「委譲の発火条件」ではなく「委譲を3件ずつに割る境界」である。
フック側もこの読み方と一致する（`check-reader-contract`:
`At most three paths per invocation.` は呼び出し単位の制約であって、
委譲するか否かの判定ではない）。

## 2. それでも問題になりうる理由

description は `Also use for ...` の直後に `4+ paths` を置くため、
**本文を開かない親には「4+ パスなら委譲」と読める**。
到達性の観点では、これは既出の3件と同じ構造（本文にある限定が
description に届いていない）。

ただし今回は**失敗の重さが違う**。

- 「Also use for」はスキルを**開く**トリガとして機能する。実測でも
  `auto-explicit-multifile` rep1 の親は、deny が出ていない状況で
  この節を根拠にスキルを開いている
  （`reviews/reader-protocol-reduction-2026-09-14.md`）。
- 開けば本文 1. の `File count alone is not a trigger` に**到達できる**。
  ただし**到達と遵守は別**であり、読んだうえで従うかは保証されない
  （`head_limit` の件では、本文を読んだ実行が本文の形式要件を満たさなかった）。
  言えるのは、description だけで委譲を決めた場合にはルート判断規則を
  参照する機会がない、ということまでである。

## 3. 観測できているか — できていない

現行スイートに**この二文を衝突させるケースがない**。

| ケース | パス数 | 合計サイズ | 委譲の根拠 |
|---|---|---|---|
| `reader-batch-evidence` | 4 | 22918 B | **予算超過**＋プロンプトがスキルを明示 |
| `reader-batch-ambiguous` | 4 | 22753 B | **予算超過**＋プロンプトがスキルを明示 |
| `auto-small-files` | 3 | 194 B | 対象外（4 未満） |

4+ パスのケースはどちらも予算超過で、かつ明示委譲である。
したがって**「パス数だけで委譲したか」を切り分ける実測は存在しない**。

決定的なケースは「**4件以上・合計 16384 B 以下・明示委譲なし**」で、
期待は `agent_zero: true`。現行スイートにはない。

## 4. 文言案（バイト影響つき）

現行 SKILL.md は **6997 B**、上限 7000 B。description も frontmatter なので
このサイズに含まれる。

| 案 | 文言 | Δ | 結果 |
|---|---|---|---|
| A | 変更しない | 0 | 6997 |
| **C（採用）** | `how to batch (4+ paths) and cross-file relationships` | **−1** | **6996** |
| D | `splitting 4+ paths into batches, cross-file relationships` | +4 | 7001 ✗ |
| B | `batching a delegation (4+ paths, cross-file relationships)` | +5 | 7002 ✗ |
| E | `batch boundaries once delegating (4+ paths, ...)` | +16 | 7013 ✗ |

C は `4+ paths` を**「どう分割するか」の問い**として提示し、
「4+ なら委譲」という読みを外す。唯一、上限内に収まる案でもある。
D・B・E は上限を超えるため、採るなら上限の移動か他所の短縮が要る。

本文側は変更不要。1.（ルート）と 2.（分割）の役割分担は既に明確である。

## 5. 適用（2026-09-15）

C 案を適用。SKILL.md **6997 → 6996 B**。

```
-  batch boundaries (4+ paths, cross-file relationships)
+  how to batch (4+ paths) and cross-file relationships
```

これは**誤読の余地を減らす修正であり、誤読の解消を保証するものではない**。
本文側は未変更。

検証ケース `auto-small-files-four` を `evals/compare/cases.json` に追加した。

| 項目 | 値 |
|---|---|
| パス | `gen/small3/{a,b,c}.txt` + `gen/collide/alpha.py` |
| 合計 | 234 B（≤ 16384） |
| プロンプト | スキル名・`token-shunt:` を含まない |
| modes | `direct`, `auto` |
| 期待 | `agent_zero: true`、`parent_reads` 4件 |

既存の4パスケース（`reader-batch-evidence` / `reader-batch-ambiguous`）は
どちらも予算超過かつ明示委譲なので、**パス数だけで委譲したかを切り分けられる
のはこのケースだけ**である。新しいフィクスチャは追加していない（既存の
生成物を組み合わせた）。

### 静的確認

`evals/test_reader_call_contract.py` に2件追加（54 tests, OK）。

- description が `how to batch (4+ paths)` を含み、
  `batch boundaries (4+ paths` を含まないこと。本文の
  `File count alone is not a trigger` が残っていること。
- `auto-small-files-four` が 4パス以上・合計 ≤16384 B・
  プロンプトにスキル名を含まない・両モードで `agent_zero` であること。

`judge.py --selftest` 全件 ok、`./evals/run.sh` 125 pass / 0 fail、
`evals/compare` の 272 tests OK。

### 未検証

**動作上の解消は未検証。** ケースを追加しただけで、まだ実行していない
（課金を伴う3周測定は今回見送り）。検索前メタデータ確認と同じ扱いで
「検証待ち」に残す。

## 6. 検証方法

静的検証では「誤読しないこと」は確かめられない。動作検証をするなら:

- 新ケース `auto-small-files-four`（4パス・合計 ≤16384 B・
  スキル名を出さないプロンプト・期待 `agent_zero: true`）を追加し、
  変更前後で各3周。判定は道具列（Agent 呼び出しの有無）で行う。

これは**課金を伴う**ため、今回は実施しない。文言変更のみ先に入れる場合、
**行動上の解消は未検証**として残すことになる（検索前メタデータ確認と同じ扱い）。
