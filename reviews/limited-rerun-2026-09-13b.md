# 限定実機再実行（2026-09-13 17:06 JST, run.Dxreyefr）

利用上限解除後に、`reviews/limited-rerun-2026-09-13.md` と同じ10ケース・19実行を実施した。
今回はロード/隔離プローブも実際に通過し、19実行すべてが応答を返した（前回は全件が上限メッセージ）。

結果: 7実行 pass / 12実行 fail。

## 修正が効いた点

- `compare-code-writer-no-ref` — 親が不存在を検出して停止せず、worker に委譲。子の拒否契約を検証できた。
- `writer-bounds` — 委譲成立。
- `compare-code-writer-ok` — 委譲成立（後述の誤検出のみで fail）。
- `compare-edit-dense-lines` — `quote_leak` 誤検出が解消し pass。

前回 `agent_calls: 0` だった writer 4件のうち、実機で委譲まで到達したのは3件。

## 残る本物の失敗（2系統）

### 1. reader 側の委譲不発（auto-one-line/sonnet, auto-one-line/auto, auto-bulk-facts/haiku）

3件とも **Skill を一度も起動していない**。親はサイズを確認した直後に
`Grep output_mode=content` で本文を取り出して回答している。

```
Bash  ls -la .../oneline.json
Grep  "payload_sha"  output_mode=content
→ 「File was small enough — 68KB, single line — to grep directly rather than delegate.」
```

原因は指示の置き場所である。「本文検索より前に経路を決める」も MIN_BYTES=65536 という
具体値も SKILL.md の本文にしかなく、Skill 未起動の時点では文脈に存在しない。
起動判断に効くのは frontmatter の description だけで、そこには数値がないため、
親の主観（68KB は小さい）が勝つ。68KB は実際には閾値超えである。

対策案: description に発動閾値（350行 / 64KB 超）と「サイズ確認後は本文検索より先に経路判定」を
一文で入れる。SKILL.md 本文の追記だけでは届かない。

### 2. 子の Read 逸脱（auto-bulk-facts/auto）

1パスに対し9回 Read（whole → 300-519 拒否 → 400-499 → 500-519 → 150-249 → 250-299 →
20-69 → 495-518 → 350-379 → 375-414）。重複多数・6回上限超過で、契約違反として真。

## 判定器の誤検出（7実行）

### a. `child_reads_once` ×3（reader-batch-ambiguous, retry-policy, auto-bulk-facts/sonnet）

**Read ツールは自身の拒否閾値未満でも全文読みを無通知で打ち切る。**
エラーにも切り詰め注記にもならない。

| ファイル | 実体 | whole read が返した範囲 |
|---|---|---|
| user.rb | 532行 / 67180B（40730トークン） | 1–183行で停止・err なし |
| bulk_facts.py | 518行 / 65669B | 1–175行で停止・err なし |

子はいずれも停止行の次（184行目 / 176行目）から連続範囲で継続しており、契約どおりである。
現行判定は「全文のトークン上限**拒否**の後だけ再 Read を許す」ため、この正しい挙動を落とす。
判定条件を「直前の Read が EOF に到達していない」に広げる必要がある。
2026-09-13 に判明した Read 上限拒否とは別系統の事象。

### b. `child_msg_cap`（compare-code-writer-ok）

800字超と判定された1108字は子の回答ではなく、ハーネスが返す
`Async agent launched successfully. ... agentId: ...` の内部メタデータ。
`foreign_hooks` と同じ帰属の誤りで、計測対象から除外する必要がある。

### c. `verification_level`（writer-verification-levels）

最終回答は正しい: `| vl_config.json | syntax | partial (JSON valid; content/requirements unverified) |`。
`flow_checks.report_fields` の表フォールバックは
`(?:^|[|+])\s*(partial|...)\s*(?=[|+]|$)` で、状態セルが語単独のときしか一致しない。
括弧の補足が付いた時点で statuses が空になる。
セル先頭一致に緩めるか、補足を禁じるかのどちらかに決める必要がある。

### d. `gold_confirmed` ×3（compare-explicit-multifile の haiku/sonnet/auto）

子は `confirmed: <絶対パス> — <事実>` を正しく出している。
親が日本語の散文に書き直し、`user.rb:2行目` 形式の引用に置き換えて
`confirmed:` と絶対パスを落とした。内容は正答。
「親の最終回答にも confirmed: と該当パスを保持」という契約が実機で守られていない。
判定器の誤りではなく、指示の強度不足。direct モードのみ pass している。

## 証跡

`evals/compare/tmp/runs/run.Dxreyefr/`（transcripts / verdicts / manifest）
ログ: `/tmp/token-shunt-rerun-1706.log`
