# 残る2点の照合（2026-09-15、追加測定なし）

対象は `reviews/grep-route-fix-verify-2026-09-15.md` §5 の2件。
本文（SKILL.md）・description・編集契約（§11.6）の文面と突き合わせる。

## 1. メタデータ未確認（`auto-edit-grep-location`、3周とも `meta1st=False`）

### 1.1 観測

道具列は3周とも **Grep が最初の手番**である。

```
周1  Grep(content) → Read(range) → Edit
周2  Grep(content) → Read(range) → Edit
周3  Grep(content) → Grep(content) → Read(range) → Edit
```

`stat` / `wc -c` は一度も実行されていない。ファイルは 5613 B で
予算内のためルートは正しいが、**親はそれを測って知ったのではない。**

### 1.2 文面との照合

**本文は要求している。**

> **Route before searching (§26.5).** Decide the route from metadata
> *before* running a content search.

**description は要求していない。** 該当箇所は2つあるが、どちらも
この経路を捕まえられない。

| description の文 | なぜ届かないか |
|---|---|
| `Judge size from metadata (stat / wc -c) **before the first Read**, never from the body.` | 義務の対象が **Read** に限定されている。最初の本文接触が Grep の流れでは発火しない。 |
| `**After the metadata check:** needed range unknown and over budget -> delegate before any content search.` | 「メタデータ確認が済んだ後」を前提とする**条件文**であり、確認そのものを義務づけていない。測らなければ前件が成立せず、規則全体が空振りする。 |

つまり今回追加した `After the metadata check` は、
**検索前の確認を十分に伝えていない**。伝えているのは
「確認した場合にどう振るか」であって、「検索の前に確認せよ」ではない。

### 1.3 診断

§2.1.1・worker-model・content search と**同型の到達性欠陥**。
規則は本文にあるが、description だけで動く親には届かない。
今回の修正は content search の**判断内容**を description に載せたが、
**判断の前提となる計測の義務**は Read 経路にしか載っていない。

### 1.4 修正（適用済み: SKILL.md 6915 → 6933 B）

description 第1文の義務対象を Read から本文接触一般へ広げる。

```
- Judge size from metadata (stat / wc -c) before the first Read, ...
+ Judge size from metadata (stat / wc -c) before the first Read or
+ content search, ...
```

差分は +18 B（6933 B、テスト上限 7000 B）。
`After the metadata check` の条件文はそのまま活きる
（前件が成立しやすくなることで、初めて意味を持つ）。

到達性を検証するテストを追加し、ハーネス 125 pass / 0 fail、
契約テスト 42 OK。

> **未検証**: この修正で `auto-edit-grep-location` の道具列が
> `meta → Grep → Read(range) → Edit` に変わるかは**確認していない**。
> 追加の課金測定を行っていないため、**動作上の解消は未検証**である。
> 現時点で言えるのは、本文にあった検索前の計測義務が description に
> 載ったことまで。

## 2. `head_limit` 欠落（`dense-lines` 周1、`grep-location` 全周）

### 2.1 観測

| 実行 | ファイル | 予算 | content Grep の形 | 返却 |
|---|---|---|---|---|
| `dense-lines` 周1 | 80034 B | 超過 | `^EDIT_MARK=` + `-n`、`head_limit` なし（**委譲後**） | 1行 |
| `dense-lines` 周2・3 | 80034 B | 超過 | `files_with_matches` → 短い content Grep | 少量 |
| `grep-location` 全周 | 5613 B | **予算内** | `-n`、`head_limit` なし | 少量 |

### 2.2 文面との照合：2つの規則が一致していない

**§26.5（予算超過ファイル向け）は手段を名指しする。**

> Content search there stays allowed only to establish *positions* for the
> §11.6 edit contract or confirm a known range, with
> `output_mode=files_with_matches` or a short `head_limit`.

**§11.6（編集契約）は結果を要求する。**

> Position authority is the parent's Grep (short unique pattern, line
> numbers, **limited output**) or an already verified known range

`dense-lines` 周1 は `^` アンカー付きの一意パターンで1行しか返しておらず、
**§11.6 の「limited output」は満たすが、§26.5 が名指しする2手段の
どちらでもない。** すなわちこれは単純な違反ではなく、
**本文内の2規則が同じ行為に異なる基準を与えている**状態である。

`grep-location` は 5613 B で予算内のため §26.5 の制限自体が適用されない。
§11.6 の基準で見れば、周3 の2回目の Grep は
「If Grep matches multiple times, narrow it」に沿った絞り込みであり、
逸脱ではない。

### 2.3 診断

- **到達性の問題ではない。** description は
  `position-only search for the edit contract is unchanged` と用途を書いており、
  用途の面では守られている。
- **規則間の整合性の問題である。** §26.5 が手段（`files_with_matches` /
  `head_limit`）で書かれ、§11.6 が結果（limited output）で書かれているため、
  「アンカー付き一意パターンで1行だけ返す Grep」の可否が文面上定まらない。
- 実害は確認されていない（委譲後・1行返却・ルーティングへの影響なし）。

### 2.4 判断が必要な点（設計確認事項として記録）

§26.5 を結果基準（limited output）に寄せて §11.6 と揃えるか、
§11.6 を手段基準に寄せて §26.5 と揃えるか。

> **現時点の判断（2026-09-15）**: 結果基準へ緩める方向は採らない。
> 今回たまたま一意パターンが1行を返したことと、**出力量を事前に
> 制限できること**は別の性質であり、前者は後者の保証にならない。
> 保留のまま、§26.5 の手段基準を維持する。
`4+ paths` と `file count alone is not a trigger` の整合性
（`reviews/repeat3-2026-09-15.md` §5）と同じ枠の課題として扱う。

## 3. まとめ

| 項目 | 種別 | 対処 |
|---|---|---|
| メタデータ未確認 | **到達性欠陥**（本文にあり description に無い） | description 第1文の対象を拡張（§1.4、**適用済み**。動作上の解消は未検証） |
| `head_limit` 欠落 | **規則間の不整合**（§26.5 と §11.6 の基準が別） | 設計確認事項として判断待ち（§2.4） |

いずれも追加の課金測定は行っていない。

## 4. 残件（2026-09-15 時点の確定整理）

### 4.1 未解決

（2026-09-15 更新）原因を特定し、到達性修正を適用した。
`reviews/gold-confirmed-2026-09-15.md` を参照。子は絶対パス付き
`confirmed:` をおおむね返しており（359項目中344、完全遵守ではない）、
親が落としていた（85実行中69）。**親の保持義務に到達性の欠陥があった** —
§2 の分割時段落と `hooks/reader-call-contract` にしかなく、3パス単一起動
には届かない — ため、description へ移した（−24 B）。契約が見えていても
失敗している実行があるので、**到達性だけが原因とは確定していない**。
**行動が変わるかは未検証**なので、§4.2 と同じ扱いで動作測定を待つ。

### 4.2 動作検証待ち

いずれも**適用と静的確認は完了、行動が変わるかは未測定**。

| 項目 | 適用 | 未検証の内容 |
|---|---|---|
| 検索前メタデータ確認 | `83e1c91`（description に `before the first Read or content search`） | 実際の道具列でメタデータ確認が content search より先に来るか |
| `4+ paths` での親保持 | `03f9fb4`（description を C 案に、検証ケース `auto-small-files-four` を追加） | 4パス・合計 ≤16384 B・明示委譲なしで親保持になるか |
| `confirmed:` 項目の保持 | description へ移設（`reviews/gold-confirmed-2026-09-15.md`） | 親が絶対パス付き `confirmed:` 項目を実際に残すか |

### 4.3 実装・判定整備済み

| 項目 | 状態 |
|---|---|
| `head_limit` の §26.5 / §11.6 不整合 | 本文整合・数値基準（1〜20）・`-A`/`-B`/`-C` 禁止・判定側検出・過去24実行の照合まで完了（`reviews/head-limit-consistency-2026-09-15.md`）。**ただし文言変更による行動改善は未検証** |

## 5. 確認の種類について

本連続作業で「OK」と記録した検査は、**すべて静的・オフラインの確認**である。
課金を伴う動作測定とは種類が異なる。

| 検査 | 種類 | 何を確かめたか |
|---|---|---|
| `./evals/run.sh` 125 pass / 0 fail | 静的・オフライン | フック挙動、契約文書、アーカイブ等のリグレッション |
| `evals/compare` 272 tests OK | 静的・オフライン（**モデル実行なし**） | 判定器・ランナーのユニットテスト。合否は判定コードの正しさであって、親の挙動ではない |
| `judge.py --selftest` | 静的・オフライン | 合成トランスクリプトに対する判定の期待一致 |
| 契約テスト 54 tests OK | 静的・オフライン | 本文・description・判定定数の文言と値の一致 |
| 既存トランスクリプト照合（`head_limit` 24実行ほか） | **過去の実測の再解析** | 新しい検査が過去の実行をどう判定するか。新規実行なし＝追加課金なし |
| 課金を伴う動作測定 | — | **今回は実施していない**。§4.2 の2件はこれを待っている |

つまり 272 件の OK は「判定側が仕様どおり動く」ことの確認であり、
「親が規則どおり振る舞う」ことの確認ではない。
