# worker-model 解決の修正と確認（2026-09-15）

## 1. 問題

親が **description だけで委譲する経路**（Skill を開かず、
`hooks/reader-call-contract` も読まない）には、`auto` を具体モデルに
解決する規則が届いていなかった。規則は contract と SKILL.md 本文に
あるが、どちらもその経路では読まれない。§2.1.1 と同型の到達性欠陥。

観測された再発（`reviews/multifile-ab-2026-09-15.md` §1）:

| 腕 | 症状 | 回数 |
|---|---|---|
| A | リテラル `auto` のままワーカーが**起動**（契約違反） | 2 / 3 |
| B | model 省略 → フックが起動前に却下 → 再送（往復1回増） | 1 / 3 |

## 2. 修正

常に親の文脈にある2面に規則を置いた。

- `plugin/agents/bulk-reader.md` の `description`（Agent 呼び出しに付随する面）
  — `resolve auto to haiku before calling, and never pass "auto" or omit model`
- `plugin/skills/bulk-reader/SKILL.md` の `description`
  — `Resolve auto to haiku before calling Agent; never pass "auto".`

contract 側の規定はそのまま（deny 経路の担保）。到達性を検証する
テストを追加。ハーネス 125 pass / 0 fail、契約テスト 42 OK。

## 3. 確認（2ケース × 3周、mode=auto）

| ケース | 周 | 初回 model | 起動前却下 | 親の先読み | 委譲 | Skill 展開 | contract 読み |
|---|---|---|---|---|---|---|---|
| explicit-multifile | 1 | **haiku** | 0 | 0 | ○ | 開いた | 読んだ |
| explicit-multifile | 2 | — | 0 | 0 | **×** | 開かず | 読まず |
| explicit-multifile | 3 | **haiku** | 0 | 0 | ○ | 開いた | 読んだ |
| boundary-16k-plus | 1 | **haiku** | 0 | 0 | ○ | **開かず** | **読まず** |
| boundary-16k-plus | 2 | **haiku** | 0 | 0 | ○ | **開かず** | **読まず** |
| boundary-16k-plus | 3 | **haiku** | 0 | 0 | ○ | **開かず** | **読まず** |

`resolved_model` は委譲した5実行すべてで haiku（子）＋ sonnet-5（親）。

### 3.1 判定

- **初回から `requested_model=haiku` / `resolved_model=haiku`**: 委譲した
  5実行すべてで達成。リテラル `auto` の起動 0件、model 省略 0件。
- **モデル指定に起因する起動前却下・再送**: **0件**（A は 2/3 が違反起動、
  B は 1/3 が却下＋再送）。
- **親の先読みなし**: 6実行すべて 0。

### 3.2 到達性の直接的な裏づけ

`boundary-16k-plus` は **3周とも Skill を開かず、contract も読まずに**
委譲し、かつ**初回から haiku を指定**している。
規則が届いたのは description 以外にありえないため、
**今回狙った到達性の改善が直接裏づけられた**。

`explicit-multifile` は委譲した2実行がいずれも Skill を開いており、
このケースでの「Skill 非展開での委譲」は**未確認**のまま残る。

## 4. 別に見つかった問題（モデルとは無関係）

`explicit-multifile` 周2 は**委譲していない**。道具列は

```
Bash wc -c → Grep → Grep → Grep → Read notifiable.rb → Read welcome_email_job.rb
```

親は `user.rb`（22546 B）を Read せず、**content search で答えを取り出した**。
先読みチェックが 0 なのはこのためで、routing としては
「境界超えのファイルに content search で答えさせない」規則
（SKILL.md 本文 §26.5 / 設計 §448）の違反にあたる。

Grep はフックされないため機械強制できない。今回の修正対象ではないので
**別件として記録**する。委譲率は `explicit-multifile` で 2/3。

## 5. 残る限定

- 3周であり、再発率の低下を統計的に主張するものではない。
  言えるのは「6実行でモデル起因の却下・違反起動が0件」まで。
- `explicit-multifile` の Skill 非展開委譲は未確認（§3.2）。
- `gold_confirmed` は両ケースの既知失敗として継続。
