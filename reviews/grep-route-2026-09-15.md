# `auto-explicit-multifile` 周2 の Grep 経路の照合（2026-09-15、追加実行なし）

対象: `evals/compare/tmp/runs/run.axtYPSQH`、`auto` モード。
`reviews/worker-model-fix-2026-09-15.md` §4 で別件として切り出した実行。

## 1. 観測（トランスクリプトそのまま）

プロンプトは3パスを名指しするだけで、**委譲を明示的に要求してはいない**。
委譲が期待されるのはルーティング規則の帰結としてである。

| # | 手番 | 引数 | 返却量 |
|---|---|---|---|
| 1 | `Bash wc -c`（3ファイル一括） | — | 394 chars（22546 / 129 / 131） |
| 2 | `Grep` | `pattern=after_create\|after_save\|include\|Notifiable\|WelcomeEmail`, `path=user.rb`, `-n`（**output_mode 既定 = files_with_matches**） | 125 chars |
| 3 | `Grep` | 同パターン, `path=user.rb`, `-n`, **`output_mode=content`**（`head_limit` なし） | **59 chars**（2行） |
| 4 | `Grep` | `pattern=send_welcome_email`, `path=user.rb`, `-n`, **`-A 5`**, **`output_mode=content`**（`head_limit` なし） | **323 chars** |
| 5 | `Read notifiable.rb`（全体） | offset/limit なし | 145 chars |
| 6 | `Read welcome_email_job.rb`（全体） | offset/limit なし | 147 chars |

`user.rb` は一度も Read していない。Agent 呼び出しは0件。

## 2. 検索前に分かっていたこと

手番1の時点で親が持っていたのは**ファイル全体のサイズのみ**
（22546 / 129 / 131 B）。

**必要レンジは未知だった。** 質問は「User 作成後に何が起きるか」で、
`include Notifiable`（2行目）と `after_create`（4行目）が
どこにあるかは検索前には分かっていない。実際、手番3・4は
**その位置を突き止めるために**実行されている。

## 3. 規則との照合

判定は「ファイル全体が 16384B 超だから」ではなく、
**必要 I/O と検索前ルーティングの規定**に照らして行う。

### 3.1 違反していない項目

- **メタデータ先行の順序**。手番1の `wc -c` が全検索より前にあり、
  「ルートをメタデータから決める」順序自体は満たしている。
- **手番2 の Grep**。`output_mode` 既定（files_with_matches）で、
  §26.5 が明示的に許可する形。
- **手番5・6 の全体 Read**。129 B / 131 B は既知の小サイズで、
  規則1の「既知レンジ合計 ≤16384B は親に留める」に該当する。
  **この2ファイルの扱いは適正**であり、`user.rb` の扱いと区別される。

### 3.2 違反した条項

**(a) §26.5「境界超えのファイルで答えを content search しない」**

> On a file already over budget, don't content-search for the answer —
> delegate, and let the child read.

手番3・4 が取り出したのは**答えそのもの**（`include Notifiable`、
`after_create :send_welcome_email`、およびその後続5行）であって、
位置情報ではない。

**(b) §26.5 の許容形からの逸脱**

> Content search there stays allowed only to establish *positions* for the
> §11.6 edit contract or confirm a known range, with
> `output_mode=files_with_matches` or a short `head_limit`.

- 用途: 本ケースに Edit は無く、§11.6 の編集契約は成立しない。
  「確認すべき既知レンジ」も §2 のとおり存在しなかった。
- 形式: 手番3・4 とも `output_mode=content` で **`head_limit` なし**。
  手番4 の `-A 5` は、規則本文が名指しで挙げている本文引き出し用フラグ
  （`-o`, `-A`/`-B`, `head -c`）に該当する。

**(c) 規則1「レンジ未知で予算超過なら委譲」**

> A denied full Read, a **range-unknown read over budget**, or a needed
> size over 16384 bytes → delegate.

`user.rb` は必要レンジ未知・全体 22546 B。**検索によってレンジを
事後的に確定させても、事前に既知だったことにはならない。**
既知レンジの親保持（規則1後段）を適用できる条件を満たしていない。

### 3.3 影響の程度

実際に親の文脈へ入った本文は 59 + 323 = **382 chars** にとどまる。
本文の大量流出は起きていない。問題は流出量ではなく、
**ルーティング判断が事後的に無意味化されたこと**にある。

## 4. description から届いていなかった判断条件

現行 description（v2）の関連部分は1文だけである。

> Decide the route before Grep output_mode=content, which is not hooked.

これは「content search の前にルートを決めよ」としか言っておらず、
**手番1で `wc -c` を実行した時点で文面上は満たされてしまう。**
実際この実行は順序規則を破っていない。届いていなかったのは次の2条件で、
どちらも SKILL.md **本文にしか無い**。

1. **境界超えのファイルでは、content search を答えの取得に使ってはならない**
   （用途は位置特定または既知レンジの確認に限る。形式は
   `files_with_matches` か短い `head_limit`）。
2. **必要レンジが未知であること自体が「予算超過」側の条件である**
   — 検索でレンジを確定させて既知レンジの親保持に持ち込むことはできない。

§2.1.1 および worker-model の件と**同型の到達性欠陥**である。
規則は本文に存在するが、本文が読まれるのは親が Skill を開くと決めた後で
あり、この実行は Skill を開いていない。

## 5. 未確定事項

- 本照合は1実行のみに基づく。同じ経路の再現頻度は測っていない。
- Grep はフックされないため、いずれの条項も機械強制できない
  （設計 §15 / §448）。description への到達性以外に打ち手が無いかは別途検討。
- description をどう直すか（字数、既知レンジ保持との書き分け）は
  本記録の範囲外。
