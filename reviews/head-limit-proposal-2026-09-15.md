# `head_limit` 整合性：文言修正案と影響範囲（2026-09-15、未適用）

方針（確定済み）: **§26.5 の手段基準を維持**し、§11.6 の適用が重なる箇所に
同じ制限を明記する。**予算内の編集経路には制限を広げない。**

## 1. 問題の再確認 — 到達性ではない

`compare-edit-dense-lines` 周1（arm D `run.IcUCbRc4`）の道具列:

```
Skill → Bash(wc -c) → Read(hooks/reader-call-contract)
     → Agent(haiku) → Grep('^EDIT_MARK=', -n, head_limit なし)
     → Read(offset,limit) → Edit
```

**親は `Skill` を開いており、SKILL.md 本文は文脈にあった。**
そのうえで `head_limit` なしの content Grep を実行している。
したがってこれは description への到達性の問題ではなく、
**本文内で §26.5 と §11.6 が同じ行為に別の基準を与えていること**が原因、
という §2.3 の診断が裏づけられる。

現行の食い違い:

| 規則 | 基準の型 | 文言 |
|---|---|---|
| §26.5 | **手段** | `output_mode=files_with_matches` または短い `head_limit` |
| §11.6 | **結果** | `short unique pattern, line numbers, limited output` |

周1 の Grep は §11.6 を満たし、§26.5 を満たさない。

## 2. 修正案（SKILL.md 本文 step 4、第1文の直後に挿入）

```
   On a target over budget, that Grep also takes the §26.5 form:
   `output_mode=files_with_matches`, or `content` with a short
   `head_limit`. A unique pattern that happens to return one line does
   not substitute — the bound has to hold before the call, not after.
   Within budget, limited output is enough.
```

- 「一意パターンでたまたま1行だった」ことと「出力量を事前に制限できる」
  ことを明示的に切り分ける。
- **予算超過の対象に限定**する。最後の1文で、予算内は §11.6 の結果基準
  （limited output）のままだと明記する。

§26.5 側は変更しない（手段基準を維持するため、書き換える理由がない）。
description も変更しない（§4 参照）。

## 3. 影響範囲

### 3.1 挙動が変わりうるケース

| ケース | サイズ | 予算 | 現状 | 修正後の要求 |
|---|---|---|---|---|
| `compare-edit-dense-lines` | 80034 B | **超過** | 周1 は `head_limit` なし、周2・3 は `files_with_matches`→短い content | 3周とも周2・3 の形に揃う |

**対象は実質このケースのみ。** 予算超過かつ編集を伴う唯一のケースである。

### 3.2 影響を受けないケース

| ケース | サイズ | 理由 |
|---|---|---|
| `auto-edit-grep-location` | 5613 B | 予算内。§26.5 の制限は元々適用されず、追記の最終文でも除外 |
| `auto-edit-grep-ambiguous` | 5674 B | 同上 |
| `auto-known-range` | 25953 B | content search を行わない（範囲指定 Read のみ） |
| `auto-explicit-multifile` | 22546 B | 修正後は content search を行わず委譲 |
| 境界3ケース | ≤16385 B | content search を行わない |

**予算内の編集経路（`grep-location` / `grep-ambiguous`）の要求は変わらない。**

### 3.3 サイズへの影響

SKILL.md 6933 B → **7249 B**（+316 B）。
**現在のテスト上限 7000 B を超える。**
適用するなら上限を 7400 程度へ移す判断が要る。
これまでの上限移動（6144 → 6500 → 6700 → 7000）はいずれも
「deny が運べない到達性規則を description に載せるため」だったが、
**今回は本文の追記であり理由が異なる**。本文の増加は
親がスキルを開いたときのみ課金されるので、往復削減の趣旨とは競合しない。

### 3.4 機械検証への影響

`head_limit` / `files_with_matches` を検査する仕組みは**現在どこにも無い**
（`judge.py`・`flow_checks.py`・フックいずれにも該当検査なし。Grep は
そもそもフックされない）。したがって本修正は

- **検出可能性を変えない。** 違反しても現行ハーネスは落ちない。
- 効果を測るには、判定側に「予算超過ファイルへの content Grep が
  `files_with_matches` か `head_limit` を伴うか」を見る検査を足す必要がある。

文言だけ直して検査を足さない場合、**遵守は観測できない**。

## 4. description を変更しない理由

現行 description は
`position-only search for the edit contract is unchanged` と
**用途**のみを述べており、用途の面では周1 も逸脱していない。
形式基準を description に載せるかは別問題だが、

- §1 のとおり周1 は Skill を開いており、本文が届かなかったわけではない。
- 予算超過＋編集という組み合わせは、いずれにせよ本文を読む経路に入りやすい。

ため、**まず本文の不整合を解消し、description への追加は
挙動を再測定してから判断する**のが妥当と考える。

## 4.4 訂正（2026-09-15、適用後）

- 「周1 のみ非適合、周2・3 は適合」は**誤り**。arm D の3周とも
  `head_limit` なしの content Grep を実行しており、3周とも非適合だった
  （`reviews/head-limit-consistency-2026-09-15.md` §4.1）。
- 「+316 B で上限 7000 を超える」も解消した。説明の重複を避けた短い
  文言で +63 B に収まり、上限の変更は不要になった。

## 5. 判断が必要な点

1. 本修正を適用するか（+316 B、テスト上限 7000 → 7400 の移動を伴う）。
2. 判定側の検査を同時に足すか（足さなければ遵守は観測できない、§3.4）。
3. 再測定を行うか（`compare-edit-dense-lines` のみ、または見送り）。
