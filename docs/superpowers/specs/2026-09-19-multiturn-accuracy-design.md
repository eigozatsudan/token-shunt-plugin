# 後続ターンを採点する（設計 §5.1 の改訂、2026-09-19）

対象の限界: `docs/superpowers/specs/2026-09-19-cumulative-intake-design.md` §5.4
（Lock B の deny は verdict の無いターンに集中する）。
下敷き: `reviews/multiturn-context-2026-09-18.md` §6-1
（「片腕が薄い答えで安く済ませた可能性は排除できない」）。

**本書は設計のみである。実装は承認後、TDD（RED を先に見る）で行う。**
費用で成果を語らない。

## 0. なぜ要るか

`judge.py` は 1 ケース 1 transcript しか採点しない（設計 §5.1）ので、
後続ターンに verdict が無い。turn completion（答えを返したか）だけが分かる。

**Lock B の deny は、その verdict の無いターンに集中する。** 累積が
16,384 バイトを跨ぐのは turn 3〜4 で、設計上そうなる。

| | 取り込みバイト | 答えの質 |
|---|---|---|
| turn 1 | 測れる | **測れる**（gold あり） |
| turn 2〜5 | 測れる（`parent_turn_reads.py`） | **測れない** |
| Lock B が発火する場所 | — | **↑ここ** |

cap-overflow では §6-1「上限は守らせたが答えが痩せた」を
**両腕 39/39 pass で棄却できた。** turn 1 のケースで gold があったからである。
**Lock B では同じ検算ができない。** 「取り込みは減った、答えは知らない」
という報告しか書けず、それは §26.5 が「ゴールド正答や安い費用で経路違反を
相殺しない」と書いた構えの裏返し —— **隔離の改善で品質劣化を相殺する**形になる。

**「新しい採点器を書かない」との関係。** この規則の由来は、自作スキャナが
judge と食い違ったことと、拒否された Read を突破として数えたことである。
禁じているのは **judge と競合する別の採点器**であって、judge の機構を
後続ターンへ広げることではない。**判定ロジックを 1 本に保ったまま
適用範囲だけ広げる**、というのが本書の形である。

## 1. 機構と境界

### 1.1 `judge()` は変えない

後続ターンには turn 1 の経路契約（`single_invocation`、`child_reads_once`、
`agent_calls_max`）が**そのまま適用できない** —— 2 回目の委譲は正常である。
`judge()` を多ターン化すると、これらの契約の意味を全部再定義することになる。
**やるのは accuracy だけ**、と境界を引く。

| | turn 1 | turn 2 以降 |
|---|---|---|
| accuracy | `judge()` | **`judge_turn()`（新）** |
| 経路契約 | `judge()` | **判定しない** |
| 親の corpus Read | — | `parent_turn_reads.py` |
| verdict への影響 | あり | **なし（記録のみ）** |

`judge_turn(transcript_path, spec, turn)` は `Transcript` / `load_events` /
`final_text` と **gold 判定そのもの（`g in final` の部分文字列一致）**を
再利用し、`{turn, gold, missing}` を返すだけである。
`run.sh` が `run_followups` の後（`run.sh:799-806` の位置）に turn ごとに呼ぶ。

### 1.2 記録のみ、を機構として保証する

`judge_turn` は verdict ファイルを書かない。`run.sh` が `.turns[]` として
別フィールドに足すだけで、**ケースの合否判定コードを一切通らない。**
「記録のみのつもりが fail に効いていた」が起こりえない形にする。

（判定の力について: 記録のみとする。現在 `prompt_turns` を持つのは
suite X の `reader-followup-scope` と `django-multiturn-context` だけで、
どちらも A / B の必須スイートに入っていない。まだ一度も採点したことの無い
ターンを、いきなり合否に使わない。）

### 1.3 欠測と誤答を分ける

turn ファイルがあるのに `Transcript` が作れない場合は `{turn, error}` を残す。
`gold` を外したこと（`missing` が非空）とは**別のフィールド**にする ——
混ぜると「採点できなかった」と「答えられなかった」が同じ数字になり、
cumulative-intake spec §5.8 で分けると決めた区別が最初から壊れる。

### 1.4 turn 5 は採点しない

総合問題で、正答が複数の言い方を許すため、部分文字列一致では
**落とし方が恣意的になる。** `gold_turns` に宣言せず、記録に
`{turn: 5, scored: false}` が残る。**採点していないことを明示的に記録する**
ほうが、緩い gold を作って通すより正直である。

## 2. gold の固定手順とアーカイブ検証

### 2.1 `gold_turns` の形

`cases.json` に turn 番号をキーにした宣言を足す。**既存の `gold` / `gold_any`
と同じ判定にかけるだけ**で、新しい規則は作らない。

```json
"gold_turns": {
  "2": ["IrreversibleError", "reversible"],
  "3": ["MIGRATION_TEMPLATE", "MIGRATION_HEADER_TEMPLATE", "as_string"],
  "4": ["RunPython", "reverse_sql"]
}
```

turn 5 は**キーが無い＝採点しない**。`spec_evidence_error` に形の検証を足す
（キーが数字文字列、値が非空文字列の非空リスト）。

### 2.2 順序 —— ここが手続きの要

**gold は本書の作成時点で確定しており、まだ 1 本の transcript も見ていない。**
この順序を壊さないために、作業を次の順に固定する。

1. **gold を commit する**（Django ソースから導出済み。§2.4 の出典つき）
2. `judge_turn` を **TDD で実装**（RED を先に見る）。合成 transcript で単体テスト
3. **その後で初めて**アーカイブに当てる

**2 と 3 を入れ替えない。** アーカイブを先に見れば、gold も判定規則も
「当たる側」に寄せられる。cap-overflow §6.5 で「指標を表を見た後に選んだ」と
書かざるを得なかったのと同じ形を、ここでは**最初から避けられる** ——
gold の出どころが実行結果ではなくソースだからである。

### 2.3 アーカイブ検証が答えること、答えないこと

対象: `~/measurements/token-shunt/multiturn-context-2026-09-18-transcripts.tar.gz`
（sha256 `44ff1aea4278e04649fc731768323d8572f530d1c3f67170a32be4c543370135`、
`reviews/multiturn-context-2026-09-18.md` §7 の記録と照合済み）。
direct 14 × auto 14 × 5 turn = 140 transcript。**$0。**

**答えること:**

- `judge_turn` が実データで動くか（機構の検証）
- **v0.1 の後続ターンの accuracy のベースライン** —— 一度も見ていない数字である
- **direct と auto の差。** 同じ問いに対し、委譲した腕の後続ターンの答えが
  薄いかどうか。§6-1 が「排除できない」と書いた穴に、**課金なしで数字が入る。**

**答えないこと:**

- **Lock B の影響は測れない。** アーカイブは Lock B 以前の実行であり、
  これは**ベースラインであって比較ではない。**
- **部分文字列一致の限界。** 正答を別の言い方で書いた答えは落ちる。
  `as_string` のようなシンボル名は頑健だが、**`reversible` は散文にも現れうる**
  ので、偽陽性側に緩い。**緩い方向の誤りであることを記録に書く。**
- **n=14 である。** 差が出ても出なくても、それが最終的な精度になる。

### 2.4 gold の出典

盲検の証拠として、各 gold がソースのどこから来たかを spec の `note` に残す。
Django 5.2.1 / `bc833e8`（`~/corpora/django`）。

| turn | gold | 出典 |
|---|---|---|
| 2 | `IrreversibleError`, `reversible` | `django/db/migrations/migration.py:158-159` |
| 3 | `MIGRATION_TEMPLATE`, `MIGRATION_HEADER_TEMPLATE`, `as_string` | `django/db/migrations/writer.py:304, 298, 129` |
| 4 | `RunPython`, `reverse_sql` | `django/db/migrations/operations/special.py:138, 144, 97-98` |

**理由は再現性ではなく盲検の証拠である。** 「実行結果を見ずに決めた」は
後から主張しても弱い。**行番号がソースを指していれば、出どころがそこである
ことを読む側が確かめられる。**

## 3. 本書が答えていないこと

1. **実装していない。** TDD で書くのは承認後の別作業である。
2. **`reader-followup-scope` の gold は決めていない。** 本書は
   `django-multiturn-context` の 3 ターンだけを対象にする。
3. **turn 5 は採点しない。** 総合問題の採点方法は本書の範囲外である。
4. **これは Lock B を測る器具ではない。** Lock B の副作用を見るには
   Lock B を実装した腕が要る。本書はその前提条件を $0 で用意するだけである。
