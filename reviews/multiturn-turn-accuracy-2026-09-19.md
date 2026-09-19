# 後続ターンを初めて採点した（$0、アーカイブ、2026-09-19）

設計: `docs/superpowers/specs/2026-09-19-multiturn-accuracy-design.md`
（gold の固定 `f4e221f`、実装 `f80dac9`）。
対象: `~/measurements/token-shunt/multiturn-context-2026-09-18-transcripts.tar.gz`
（sha256 `44ff1aea…`、`reviews/multiturn-context-2026-09-18.md` §7 と照合済み）。
**実費 $0。新規課金なし。**

## 0. 先に書くこと

**1. 落ちたターンは 1 つも無い。** 採点対象 **84/84**（direct 42、auto 42）で
gold 全一致。**欠測 0、エラー 0。**

**2. §6-1 の懸念は、この計器では支持されなかった。**
「片腕が薄い答えで安く済ませた可能性は排除できない」に対し、
**両腕とも同じ 3 ターンで同じ gold を返している。**
ただし **§3 の通り、これは「差が無い」の証明ではない。**

**3. 後続ターンに契約違反は無い。** worker 返答は auto の turn 5 に
**5 件のみ、最大 3,025 字**（上限 4,000）。turn 2〜4 は**両腕とも 0 件**である。

**4. turn 2〜4 で auto は委譲していない。** worker 返答 0 件は、
`parent_turn_reads.py` が同じ区間で数えた**親の直接 Read 21 回・10/14 会話**と
同じ方向を指す。**委譲は turn 1 で終わっている。**

## 1. 採点結果

| 腕 | turn 2 | turn 3 | turn 4 | turn 5 |
|---|---|---|---|---|
| direct | 14/14 | 14/14 | 14/14 | 採点対象外 |
| auto | 14/14 | 14/14 | 14/14 | 採点対象外 |

gold は `f4e221f` で Django 5.2.1（`bc833e8`）のソースから固定したもので、
**1 本の最終回答も読む前に決めてある**（設計 §2.2・§2.4）。

| turn | 採点する gold | 採点しない |
|---|---|---|
| 2 | `IrreversibleError` | `operation.reversible` |
| 3 | `MIGRATION_TEMPLATE`, `MIGRATION_HEADER_TEMPLATE`, `as_string` | — |
| 4 | `RunPython`, `reverse_sql` | — |
| 5 | — | 総合問題のため全体 |

## 2. worker 返答長

| 腕 | turn 2 | turn 3 | turn 4 | turn 5 |
|---|---|---|---|---|
| direct | 0 件 | 0 件 | 0 件 | 0 件 |
| auto | 0 件 | 0 件 | 0 件 | **5 件、最大 3,025** |

turn 1 では `child_msg_cap` 違反が **5/14** あった（§4-2）。
**後続ターンには 1 件も無い。** ただし後続ターンの委譲自体が 5 件しか無いので、
**「後続では契約が守られる」とは読めない。分母が小さい。**

## 3. この記録が答えていないこと

1. **天井に当たっている。** 84/84 では**腕の差を解像できない。**
   この計器が使えるのは「下がったこと」の検出であって、
   **今回の一致は上限に張り付いた状態である。**
2. **部分文字列一致は緩い。** 採点した 6 語はいずれもシンボル名だが、
   正答を別の言い方で書いた答えを落とす可能性と、
   文脈違いで当たる可能性の**両方が残る。**
3. **turn 5 は採点していない。** 5 ターンのうち 1 つは中身を見ていない。
4. **turn 2 の設問の半分は採点していない。**
   `"reversible" in "IrreversibleError"` が True なので、
   属性側は独立に採点できない（設計 §2.1）。
5. **Lock B の影響は測っていない。** これは Lock B 以前の実行であり、
   **ベースラインであって比較ではない。**
6. **n=14。**

## 4. 実装中に見つけて直した欠陥

**採点しない turn では worker 返答長が丸ごと落ちていた。**
最初の実装は `gold_turns` に宣言の無い turn を
`{turn, scored: false}` だけで返しており、**返答長を測らずに返していた。**
アーカイブの Agent 起動 5 件が**すべて turn 5 にある**ため、
この形では**後続ターンの契約違反が 1 件も見えない。**

返答長は gold の判定ではないので、採点しない turn でも記録する形に直した
（設計 §1.6 の目的に合わせた。テスト `UnscoredWorkerReplyTests`）。

**見つかった経緯を書いておく。** 「worker 返答 0 件」を報告する前に、
transcript を直接走査して Agent の `tool_use` を数えたところ **5 件あった。**
**計器が壊れていても 0 は返る**ので、0 を報告する前に独立に数えた。
結果として計器は正しく、**落ちていたのは採点しない turn の扱いだった。**

## 5. 残したもの

- `reviews/data/multiturn-turn-accuracy-2026-09-19.csv` — 112 行
  （run × mode × turn の scored / gold / missing / unscored / 返答長）
  sha256 `3cae2b0c6bf4b8882f71a1b8254d1742a91170eca3c48acf9c983c125b5e38c5`
- 展開した transcript は `~/measurements/token-shunt/turn-scoring-2026-09-19/`
  （repo の外。元アーカイブの sha256 は上記）

採点は `judge.judge_turns` / `judge.judge_turn` で行った。
**別の採点器は書いていない。**
