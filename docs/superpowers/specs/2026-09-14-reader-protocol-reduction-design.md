# reader 委譲プロトコルの往復削減（設計）

日付: 2026-09-14
状態: 設計合意済み、未実装

## 1. 背景

`reviews/cost-structure-2026-09-14.md` の切り分け実験（有効21実行）で、次が分かった。

| ケース | bare/direct | skill/direct | プロトコル分（skill−bare） | 委譲分（bare−direct） |
|---|---|---|---|---|
| auto-bulk-facts | ×0.62 | ×1.05 | +$0.0578 | −$0.0511 |
| auto-explicit-multifile | ×0.69 | ×1.38 | +$0.0783 | −$0.0355 |
| auto-one-line | ×1.48 | ×2.98 | +$0.2636 | +$0.0842 |
| auto-large-writer | ×1.51 | ×1.55 | +$0.0043 | +$0.0501 |

通常の読み取り2ケースでは、素の1回委譲（`bare`）が direct より 35% 安い
（$0.1626 対 $0.2492）。同じケースで出荷時のスキル手順を通すと $0.2986 になり
direct を上回る。親ターン数は `bare` 3.5〜4 に対し `skill` 10.5〜11.5 で、増分は
メタデータ探索 Bash・SKILL.md 読み込み・その間の説明ターンである。

したがって委譲方式そのものではなく、**スキルが要求する手順の往復**を削る。

## 2. 目的と範囲

**目的**: reader 経路の定型ケースで、親の往復を減らし、direct 比で料金を下げる。

**対象**: `check-file-size` / `check-bash-read` が deny する reader 経路。

**対象外**:

- **writer 経路（code-writer）**。`PreToolUse` に Write のマッチャがなく deny 起点を
  作れない。加えて `bare` でも direct 比 ×1.51 であり、**親の手順短縮だけでは解消
  しない追加コストが残る**ことを示す。原因は特定できておらず、n=1 のため確度も低い。
  未解決の課題として記録し、本設計では触れない。
- **複数小ファイルの総I/O超過による自動委譲**。個々のファイルが閾値を下回るため
  deny が発火しない。v0.1 では自動発火の対象外とし、親が明示的に必要と判断した
  場合のスキル経由の委譲のみ維持する。

## 3. 契約の正本と運び手

正本と運び手を区別する。

| 役割 | 置き場所 |
|---|---|
| **共通契約の正本** | `plugin/hooks/reader-call-contract`（新規、プレーンテキスト） |
| 定型ケースの運び手 | 両フックの deny `permissionDecisionReason` |
| 明示委譲（deny 非経由）の運び手 | SKILL.md が正本を Read する手順を示す |
| 子側の実行契約 | `plugin/agents/bulk-reader.md`（維持） |

SKILL.md と agent md は親向けの呼び出し仕様を再掲しない。子側の実行契約
（読み取り境界、`confirmed`/`unconfirmed` の区別、4000字上限、`status`/`stop_reason`、
未読範囲の申告）は agent md に残す。**親が受けた deny 全文が子に届く保証はない**ため、
子の自己完結性を崩さない。

## 4. deny テンプレートの仕様

### 4.1 本文（`reader-call-contract`）

```
{REASON}
Delegate now — do not read these paths yourself, and do not load the
bulk-reader skill for this call.
Agent: subagent_type=token-shunt:bulk-reader
  model: the worker model the caller specified; if none or "auto",
  use haiku. Pass a concrete model, never "auto".
  prompt must contain: your question; the paths below with sizes; and —
  "One bullet per fact: confirmed: <absolute path> — <symbol>: <fact>.
   unconfirmed for missing evidence. No source lines or code fences.
   Max 4000 chars. End with two plain lines: status: complete|partial,
   then stop_reason: <reason>."
{PATHS}
First call only. If the worker is refused by this same limit, stop and
report partial — do not delegate again. For any other partial, consult
the bulk-reader skill before retrying.
In your final answer keep each confirmed bullet with its full absolute
path, unabbreviated.
```

### 4.2 プレースホルダ

| 記号 | 内容 |
|---|---|
| `{REASON}` | 拒否理由。サイズ超過と走査予算超過で文言が異なる。冒頭のサイズ超過文を走査予算超過に流用しない |
| `{PATHS}` | `paths:` に続けて対象パスを1行1件で列挙する。各行は `<絶対パス> (<バイト数> B)`。**サイズ未取得のパスは `(size unknown)`**。Bash deny で複数パスが確定している場合は全件を列挙する |

### 4.3 規則

- **モデル解決**: 呼び出し側の明示指定を優先。未指定または `auto` は **haiku**。
  `auto` の文字列をそのまま Agent に渡さない
- **停止と再試行の分離**: 同一制限で子が拒否された場合は**再委譲せず partial で終了**。
  それ以外の partial は、再試行を検討する前にスキルを参照する
- **パス省略の禁止**: 最終回答の `confirmed` 行は絶対パスを省略しない
  （3周の実機評価で `gold_confirmed` 15件の原因）
- **サイズ目標**: 固定本文（`{REASON}` / `{PATHS}` を除く）を **900バイト以下**。
  4.1 の実測は 860 バイト。現行 SKILL.md は 12,235 バイトで、**参照する契約本文の
  バイト数**としては約93%減。トークン・料金の効果は §8 の評価で確認する
- **フェイルセーフ**: 正本が欠落・読み込み不能なら、現行の deny 文言をそのまま返す

## 5. テンプレートの適用条件

| deny の種類 | テンプレート | 条件 |
|---|---|---|
| サイズ超過（Read / Bash） | 返す | 対象パスが確定していること |
| 走査予算超過（Read / Bash） | 返す | 対象パスが確定し、**かつ委譲で処理継続が可能**なこと |
| シェル展開でパス未解決 | 返さない | 対象が不明 |
| heredoc・解析安全性 | 返さない | 委譲は解決策ではない |
| cwd 不正・時間予算超過 | 返さない | 同上 |
| バイト境界なしのパイプ | 返さない | `head -c N` の指示が正しい対処 |
| `agent_type=token-shunt:bulk-reader` の Read | 該当なし | 従来どおり pass（子は対象外） |

**「委譲で処理継続が可能」の判定基準**: 発火した制限が、worker
（`agent_type=token-shunt:bulk-reader`）に適用されない、または worker 側の
緩和された境界の下で通過しうること。worker も同じ制限で拒否されるなら、
テンプレートを返さず再委譲のループを作らない。

**この確認を実装計画の最初の作業に置く。** フックが持つ各制限（サイズ閾値、
走査予算バイト数、走査予算時間、ネイティブ Read のトークン上限）について、
worker 側の適用有無を1件ずつ確認し、この判定表を確定させる。現時点で確認済みなのは
`check-bash-read` の worker allowlist（`check-bash-read:173`）のみである。

**確認が済むまで、走査予算超過ではテンプレートを適用せず現行の deny を維持する。**
これはテンプレート適用の前提条件であり、サイズ超過（適用有無が確定している経路）
とは分けて実装する。

**確認済み（2026-09-14）**: `reviews/worker-limit-applicability-2026-09-14.md` を参照。
走査予算超過へのテンプレート適用は Task 5 で実施する。

## 6. ファイル別の変更

### 6.1 `plugin/hooks/reader-call-contract`（新規）

§4.1 の本文。両フックが読み、プレースホルダを埋めて出力する。

### 6.2 `plugin/skills/bulk-reader/SKILL.md`

**frontmatter の `description`**: 「deny 内に呼び出し仕様がある定型ケースでは不要。
明示委譲・バッチ境界・曖昧性・再試行のときに参照」とする。現行の記述は、まさに削減
対象の定型ケースでスキルを読ませている。

| 削除 | 残す |
|---|---|
| 手順1〜3の定型呼び出し仕様 | バッチ境界の確認手順 |
| 返答契約の再掲 | 曖昧性の扱い（unconfirmed / partial） |
| メタデータ探索の手順 | 再試行規則（Sonnet 昇格、上限） |
| | `--worker-model` の意味論 |
| | §11.6 編集契約のための targeted Read |
| | 明示委譲の手順（新規、下記） |
| | 複数小ファイルの v0.1 範囲外注記（新規） |

明示委譲の手順（deny を経ていない場合）:

```
${CLAUDE_PLUGIN_ROOT}/hooks/reader-call-contract を Read し、
{REASON} を "Explicit delegation (no hook deny)"、{PATHS} を対象パスと
サイズに置き換えて、その仕様どおりに Agent を呼ぶ。サイズを取得して
いなければ (size unknown) と書く。サイズ取得だけのためにメタデータ
探索を行わない。
```

### 6.3 `plugin/agents/bulk-reader.md`

親向け呼び出し仕様の重複のみ削除。子側の実行契約は維持。

### 6.4 `plugin/hooks/check-file-size` / `check-bash-read`

§5 の条件に合う deny で正本を読み、`{REASON}`・`{PATHS}` を埋めて返す。
それ以外の deny と、正本の読み込み失敗時は現行文言を維持する。

## 7. 設計文書（`docs/2026-09-12-token-shunt-design.md`）の改訂

| 箇所 | 改訂 |
|---|---|
| §26.5（L448） | フックが deny するファイルでは、**deny が経路判定そのもの**になる。事前メタデータ探索は不要。「超過と分かっているファイルを本文検索しない」禁止規則は維持 |
| §11 | 子へ渡すのは**サイズのみ**。**行数は事前取得を要求しない**（子は自分の Read の `totalLines` で把握）。**サイズ未取得時は `size unknown` を許容** |
| §26.2（L868） | 総I/O 16384バイト以下なら親が直接、は維持。超過側の自動発火は deny のある経路に限る。複数小ファイルの総I/O超過は v0.1 では自動発火しない |
| §26.1 | 契約の正本は `plugin/hooks/reader-call-contract`。SKILL.md と agent md は親向け呼び出し仕様を再掲しない |
| 新規 | §5 の適用条件表と、正本欠落時のフェイルセーフ |

## 8. テストと評価

### 8.1 フック単体（`evals/` に追加、`evals/run.sh` に登録）

**両フック（`check-file-size` / `check-bash-read`）で検証する。**

| 検証 | 期待 |
|---|---|
| サイズ超過の deny | テンプレートあり。`{PATHS}` に絶対パスと**実バイト数** |
| 走査予算超過・サイズ取得済み・継続可能 | テンプレートあり。`{PATHS}` は**実サイズ** |
| 走査予算超過・サイズ未取得・継続可能 | テンプレートあり。`{PATHS}` は `(size unknown)` |
| 走査予算超過・継続不可 | テンプレートなし |
| heredoc・cwd不正・時間予算・シェル展開・境界なしパイプ | テンプレートなし、現行文言のまま |
| 正本が欠落／読み取り不能 | 現行文言のまま deny |
| 固定本文のバイト数 | 900バイト以下（回帰で固定） |
| `agent_type=token-shunt:bulk-reader` の Read | 従来どおり pass |

### 8.2 実機での小規模比較

`evals/compare/cost_probe.py` を `direct` / `bare` / `skill`（改訂後）の3条件で、
**同条件で3回**実行する。料金差は**中央値と各回の差の両方**を報告し、単発の
ばらつきで判断しない（`auto-one-line` は既存測定で実行間4倍のばらつきがある）。

| 指標 | 現状 | 目標 |
|---|---|---|
| 親ターン（読み取りケース） | skill 10.5〜11.5 | **5前後（目標値）**。ツール以外の応答も数えているため厳密な下限ではない |
| Skill 読み込みターン | 毎回1回 | **0回**。ただし**初回の定型・正常終了ケースに限る**。明示委譲や再試行での正当なスキル参照は失敗に数えない |
| コスト（読み取り2ケース計） | skill $0.2986 / direct $0.2492 | direct 比マイナス（`bare` は $0.1626 = −35%） |
| `gold_confirmed` | 3周で15件 | 0件 |
| モデル指定違反（`requested_model` / `resolved_model`） | 3周で各11件 | **reader 経路で0件**。対象外の writer 経路は分けて報告する |
| deny 回数と注入バイト数 | 未計測 | 記録して削減幅と突き合わせる（§9 の累積リスクの検出指標） |

### 8.3 全体再評価への条件

小規模比較で**契約を維持したまま料金削減を確認できた場合のみ** `repeat.sh 3` に進み、
リリースゲートを再判定する。未達なら先に原因を調べる。

## 9. リスクと未解決

- **description を絞ってもモデルが自発的にスキルを読む可能性**がある。8.2 の
  「Skill 読み込み0回（初回定型・正常終了ケース限定）」がその検出指標。1回でも
  読まれるなら description を調整する
- deny 分の追加往復が見込まれるため、`bare`（親3.5〜4）と同水準にはならない
- **deny 1件につき約900バイト＋パス行が親のコンテキストに入る**。親が拒否される
  読み取りを繰り返すと、この注入が累積して削減を打ち消しうる。8.2 で deny 回数も
  記録する
- writer 経路の追加コストは未解明（§2）
- 単一巨大行（`auto-one-line`）は `bare` でも ×1.48。本設計で direct を下回るかは
  未確認。ルーティング除外は別課題
