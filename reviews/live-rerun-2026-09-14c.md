# 実機再実行（2026-09-14 15:30–16:12）

対象: `evals/compare/tmp/repeats/repeat.DSpuB3b5/run-1.json`（transcript は
`evals/compare/tmp/runs/run.C6D9FM4u`）。コードは HEAD 4c2fa1e に、
[live-rerun-2026-09-14b-fixes.md](live-rerun-2026-09-14b-fixes.md) と
[clean-context-three-triage-fixes-2026-09-14.md](clean-context-three-triage-fixes-2026-09-14.md)
の未コミット修正を載せた作業ツリー。`repeat.sh 1` で全30ケース75実行を1周した。

プランを Pro から Max に変更したため、前回まで測定を阻んでいた利用上限には
一度も当たっていない。**利用上限による未測定は0件**である。

## 集計

| 項目 | 今回 | 前回（[live-rerun-2026-09-14b.md](live-rerun-2026-09-14b.md)） |
|---|---|---|
| pass / fail / runs | **60 / 15 / 75** | 39 / 36 / 75 |
| 失敗ケース数 | 8 / 30 | 19 / 30 |
| probes | pass 3 / fail 0 | （実行数に混入していた） |
| `errors` | なし | なし |
| `selected_run_valid` | false | false |
| `release_eligible` | false | false |

解消したクラスタ: `verification_execution` 13 → **0**、`accuracy` 4 → 0、
`agent_type` / `agent_calls`（委譲不発）各3 → 0、`parent_reads` 2 → 0、
`edit_flow` 2 → 0、`single_invocation` 2 → 0、`parent_no_full_read`
`parent_bash` `no_parent_write` `deny_route` `child_msg_cap`
`child_ref_before_write` 各1 → 0。`foreign_hooks` は前々回の49件以降0のまま。

`probes:` と `done:` の分離により、前回指摘した計数のずれ（`done: pass=45
fail=33 runs=75` が実行数と合わない問題）は解消した。今回の `done:` は
aggregate と一致する。

## 残る失敗 15件

```
7 gold_confirmed        4 verification_control   4 isolation
3 verification_level    3 child_format           2 retry_policy
2 deny_bypass           2 child_status           1 child_reads_once
1 batch_evidence
```

失敗ケースは `auto-explicit-multifile` `compare-bulk-facts`
`compare-explicit-multifile` `reader-batch-ambiguous` `reader-batch-evidence`
`reader-bounds` `writer-bounds` `writer-verification-levels` の8件。

### 1. `gold_confirmed` 7件 — 原因は親のパス省略

`gold_paths` の fixture 相対パスへの訂正は正しく効いている。残るのは**親が絶対パスを
`...` で短縮している**ことである。`compare-explicit-multifile/haiku` の最終回答:

```
- confirmed: `.../app/models/user.rb` — User includes Notifiable concern (line 2)
- confirmed: `.../app/models/concerns/notifiable.rb` — deliver_notifications ...
- confirmed: `.../app/jobs/welcome_email_job.rb` — WelcomeEmailJob sends ...
```

関係の同定（concern・job・mailer とその参照関係）は正しく、パスの前半だけが
省略されている。対処は二択:

1. `bulk-reader/SKILL.md` の親最終回答規則に「絶対パスを省略記号で短縮しない」を
   明記する
2. 判定器がサフィックス一致を許容する

2 は「別実行の絶対パス引用・basename だけの引用は不合格」という
`live-rerun-2026-09-14b-fixes.md` の方針と衝突するため、**1 を推奨**する。

### 2. `isolation` 4件 — `compare-bulk-facts` の新規退行

```
delegate=[31723, 18123, 16801] direct=18877 fixture=65669
```

**auto モードの親取り込み 31,723 バイトが direct の 18,877 バイトを上回った**。
同一実行に `retry_policy: only one auto Sonnet retry is permitted` が2回と
`child_reads_once` が出ており、auto の Sonnet 再試行が規定回数を超えて親に
テキストを積んだ結果である。委譲がベースラインより悪化した唯一のケースで、
本製品の目的に直結するため優先度が高い。

### 3. writer 系の返答契約 `writer-verification-levels/auto` に集中

`verification_control` 4件と `verification_level` 3件はすべてこのケース。
`child_status` 2件（`reader-bounds/auto` `writer-verification-levels/auto`）と
`child_format` 3件（`writer-bounds/auto` ほか）も返答書式である。前回より
件数は減ったが、子の `status:` / `stop_reason:` と writer の書式要求は
まだ安定して守られていない。

### 4. その他

- `deny_bypass` 2件 — `auto-explicit-multifile` の sonnet / auto で親が Bash で
  `user.rb` の本文を回収
- `batch_evidence` 1件 — `reader-batch-ambiguous/auto` が曖昧な TOKEN 関係を
  confirmed に昇格

## 4. コスト・トークン（4大ケース、単発）

`evidence_complete: true`。

| モード | 合計 USD | 前回 |
|---|---|---|
| direct | 0.2947 | 0.3006 |
| haiku | 0.5819 | 0.5930 |
| sonnet | 0.8163 | 0.6637 |
| auto | 0.6101 | 0.5608 |

- `auto - direct` = **+$0.3155**（前回 +$0.2602）、`regression: true`、
  `release_gate: false`
- `auto - sonnet` = -$0.2062（前回 -$0.1029）

ケース別 `auto - direct`: `auto-one-line` +$0.1450、`auto-large-writer` +$0.0715、
`auto-explicit-multifile` +$0.0576、`auto-bulk-facts` +$0.0414。

親トークン I/O 差分は4ケースすべてで委譲が多い。

| ケース | `delta_input` | `delta_output` | `delta_io` |
|---|---|---|---|
| auto-bulk-facts | +71,125 | +1,291 | +72,416 |
| auto-one-line | +109,216 | +1,936 | +111,152 |
| auto-explicit-multifile | +128,980 | +2,143 | +131,123 |
| auto-large-writer | +78,870 | +629 | +79,499 |

**トークン・料金の削減は今回も観測されていない。**

### Read 上限 40,000 の影響についての訂正

`live-rerun-2026-09-14b-fixes.md` のネイティブ Read 上限変更について、
「direct の費用を押し上げて `auto - direct` を製品に有利に歪めるのでは」と
懸念していたが、**実測は逆**だった。`auto-one-line/direct` は
$0.0358 → **$0.0218 に下がっている**。1回の成功 Read のほうが、拒否されてから
Grep に逃げる経路より安いためである。上限変更は製品に有利なバイアスを
生んでいない。

一方でバイト隔離は両ケースとも成立した。

```
compare-one-line: delegate=[16149, 16528, 16154] direct=70122 fixture=69886
auto-one-line:    delegate=[17069, 15675, 17229] direct=70126 fixture=69886
```

**本文バイトは確実に隔離できているのに、料金は direct の約2倍**という構図が
はっきりした。これが現時点の中心的な事実である。

## 次の一手

1. `compare-bulk-facts/auto` の Sonnet 再試行超過（`isolation` + `retry_policy`）—
   委譲がベースラインを上回る唯一の退行
2. 親最終回答での絶対パス省略の禁止を `bulk-reader/SKILL.md` に明記（7実行）
3. writer 系の返答契約（`verification_control` 4 / `verification_level` 3 /
   `child_format` 3 / `child_status` 2）
4. `repeat.sh 3` でコストの中央値を取り、単発測定のばらつきを外す

---

# 3周反復（2026-09-14 15:56–17:5x、`repeat.sh 3`）

証跡: `evals/compare/tmp/repeats/repeat.FLlTt0Kl/run-{1,2,3}.json`。コードは上記と
同一の作業ツリー。225実行すべて測定でき、利用上限エラーは0件。

## 周ごとの集計

| | 周1 | 周2 | 周3 | 参考: 単発 |
|---|---|---|---|---|
| pass / fail | 67 / 8 | 61 / 14 | 61 / 14 | 60 / 15 |
| probes | 3 / 0 | 3 / 0 | 3 / 0 | 3 / 0 |
| `release_gate` | false | false | false | false |

## コストの中央値（4大ケース合計、3周）

| モード | 周1 | 周2 | 周3 | **中央値** |
|---|---|---|---|---|
| direct | 0.3622 | 0.3605 | 0.3634 | **0.3622** |
| haiku | 0.6262 | 0.5485 | 0.7507 | **0.6262** |
| sonnet | 0.7806 | 0.7163 | 0.7956 | **0.7806** |
| auto | 0.7726 | 0.6325 | 0.6304 | **0.6325** |

- `auto - direct` の中央値 = **+$0.2703**（各周 +0.4104 / +0.2719 / +0.2669）
- **3周とも `regression: true` / `release_gate: false`**

ケース別 `auto - direct` の中央値:

| ケース | direct | auto | 差（中央値） | 各周の差 |
|---|---|---|---|---|
| auto-explicit-multifile | 0.0216 | 0.1539 | **+0.1311** | +0.1326 / +0.1311 / +0.0633 |
| auto-large-writer | 0.0739 | 0.1550 | **+0.0797** | +0.0578 / +0.0797 / +0.0838 |
| auto-bulk-facts | 0.1079 | 0.1565 | **+0.0497** | +0.0454 / +0.0497 / +0.1121 |
| auto-one-line | 0.1557 | 0.1672 | **+0.0115** | +0.1746 / +0.0115 / +0.0078 |

親トークン I/O 差分の中央値も4ケースすべて増加側:
`auto-explicit-multifile` +131,801、`auto-one-line` +111,032、
`auto-large-writer` +78,935、`auto-bulk-facts` +73,182。

**結論: 単発測定のばらつきを外しても、委譲は direct より高い。**削減幅がゼロに
近いケースは `auto-one-line` の +$0.0115 が最小で、符号が反転した周は一つもない。

## 失敗理由の合計（225実行、延べ）

```
15 gold_confirmed   15 retry_policy     11 requested_model  11 resolved_model
10 child_reads_once  7 deny_bypass       7 child_format      6 child_status
 4 batch_evidence    4 isolation         3 agent_calls       2 accuracy
 2 child_no_body     2 agent_type        1 single_invocation 1 parent_reads
 1 child_result_evidence  1 parent_no_full_read  1 child_msg_cap
```

## 再現性で分けた優先度

**3周とも落ちる（構造的）**

| ケース | 失敗実行数 | 主因 |
|---|---|---|
| `auto-explicit-multifile` | 9 / 9 | `gold_confirmed`（パス省略）、`deny_bypass` |
| `compare-explicit-multifile` | 7 / 9 | `gold_confirmed` |
| `reader-batch-ambiguous` | 3 / 3 | `batch_evidence`、周2は `retry_policy` も |

`gold_confirmed` 15件は全周に分布しており、親の絶対パス省略が**再現性のある契約
違反**であることが確定した。上記「次の一手 2」の優先度は高い。

**2周で落ちる**: `auto-bulk-facts`（6実行）、`writer-bounds`、
`writer-verification-levels`、`retry-policy`

**1周だけ**: `auto-edit-grep-ambiguous`、`auto-routing-boundary-16k-equal`、
`compare-code-writer-ok`、`auto-routing-boundary-16k-plus`、
`compare-hook-deny-route`

## 新たに見えた問題: auto のモデル解決と再試行

単発では見えなかったが、`requested_model` 11 / `resolved_model` 11 / `retry_policy`
15 が周2・周3に集中している。内訳は2種類:

1. **`--worker-model auto` の未解決** — `requested None; expected haiku`、
   `requested 'auto'; expected haiku`。親が文字列 `auto` をそのまま渡すか、
   model を指定していない。`compare-explicit-multifile/auto`
   `reader-batch-ambiguous/auto` で観測
2. **Sonnet 昇格の不履行と再試行超過** — `requested 'haiku'; expected sonnet` が
   繰り返され、同時に `only one auto Sonnet retry is permitted`、
   `total Agent budget exceeds four`、`retry began without a previous worker
   result`。`writer-verification-levels/auto` 周3 で5回連続、
   `compare-hook-deny-route/auto` でも観測

auto 経路のモデル選択と再試行制御は、単発1周では過小評価されていた。

## `isolation` 4件の再確認

周3の `auto-bulk-facts` 4モードのみ。

```
delegate=[18013, 17411, 17650] direct=4828 fixture=65669
```

委譲側は fixture 65,669 バイトに対し 17〜18KB で正常。落ちた原因は **direct が
4,828 バイトしか取り込まなかったこと**（direct がほとんど読まずに答えた）で、
委譲の退行ではない。単発測定で観測した `compare-bulk-facts` の
delegate=31,723 > direct=18,877（再試行の積み上がり）は、3周では再現しなかった。

判定器の `delegate_lt_direct_and_fixture` は direct 側が縮むと機械的に落ちるため、
**direct のベースラインが有効かどうかの下限チェック**（例: fixture に対する最低
取り込み率、または direct の必須 Read 成立）を別条件として持たせるべきである。

## 次の一手（更新）

1. 親最終回答の絶対パス省略禁止を `bulk-reader/SKILL.md` に明記（15実行、全周）
2. auto のモデル解決（`auto` 文字列の素通し）と Sonnet 昇格・再試行上限
   （延べ37実行）
3. `reader-batch-ambiguous` の `batch_evidence`（全周）
4. `isolation` 判定に direct ベースラインの有効性チェックを追加
5. コストは3周中央値でも `auto - direct` = +$0.2703。**リリース可否の判断材料
   としては、現状「削減なし」が確定**であり、方式そのものの再検討が要る
