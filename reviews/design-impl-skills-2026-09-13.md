# Design vs skills/agents (齟齬) — 2026-09-13

正本: `docs/2026-09-12-token-shunt-design.md`（承認済み）。対象は
`plugin/skills/*/SKILL.md`、`plugin/agents/*.md`、README の skills / model /
small-task 節のみ。スタイルは対象外。フック未強制は設計どおりなので未計上。

## Summary

スキルと named subagent の主契約は正本と一致している。

- スキル frontmatter に `agent:` / `context: fork` は無い。`description` は
  §11 のトリガー／禁止トリガーのみ。手順は本文。
- 呼び出しは `token-shunt:bulk-reader` / `token-shunt:code-writer` のみ。
  bulk-reader 本文は Explore と素の `bulk-reader` を明示禁止。
- 両 SKILL.md 本文先頭に §26.1 必須文面（`--worker-model auto|haiku|sonnet`、
  未知値は Agent 前に拒否、auto は haiku 開始、親が `model` を渡す）。
- 小仕事は 16384 バイト / 50 行。bulk-reader はメタデータのみ（`stat` /
  `wc -c`、本文 Read 禁止）。編集は親 Grep → 原本 targeted Read 成功 → Edit。
  byte-span / dd+temp / 未読 Edit なし。
- bulk-reader: 1 起動 3 パス・各 Read 1 回・探索/再 Read/resume なし。
  4+ パスは 3 パス分割とバッチ間根拠契約。code-writer: 参照必須、検証コマンド、
  拡張子フォールバック、`minimal|syntax|requirements`、親は生成本文を vis しない。
- Agent frontmatter は §12 どおり（haiku / effort low / maxTurns 4 vs 12 /
  tools `Read` vs `Read, Write, Grep, Glob`）。Agent / Edit なし。

齟齬は 3 件の実行時契約（子の 16/20 上限の係り、4000 字に status を含めない、
bulk-reader 側の総起動 4 の打ち切り）と、README §14 の欠文 1 件。

## Issues

### Issue 1 -- Severity: bug
- File: plugin/agents/code-writer.md:15
- Design: §26.3, §12
- Description: §26.3 の内容確認上限（最大 16 ファイル、Read / Grep / Glob 合計 20）は生成 worker 全体の指示上限である。実装は「既存 target を先に Read」の括弧にだけ置いている。新規 target（参照 Read だけの本線）では上限が掛からない読みになり、Grep/Glob と `maxTurns: 12` のまま探索できる。`writer-bounds` は transcript 超過を fail にする。
- Design quote: 「code-writer は生成用の別契約で `maxTurns: 12` を維持する。内容確認は最大 16 ファイル、Read / Grep / Glob 合計 20 回を指示上の上限とし、transcript 超過は fail。読み取り worker の one-shot 方針を生成の Write 手順と混同しない。」
- Implementation quote: 「If the target already exists, Read it first (content verification is bounded: at most 16 files, 20 Read/Grep/Glob calls total).」
- Suggestion: 16 ファイル / 20 回を既存 target の Read から外し、参照・既存 target を含む内容確認全体の上限として独立箇条にする。
- Status: open
- False-positive risk: medium — 「content verification」を全文の上限と読む余地はあるが、文法上の係りは既存 target 節だけ。

### Issue 2 -- Severity: bug
- File: plugin/agents/bulk-reader.md:21
- Design: §12, §26.3
- Description: 最終回答の 4000 字は起動あたりの上限で、`status` / `stop_reason` もその中に含める。code-writer は「800 字の内側」と強制停止時の `partial` を書いている。bulk-reader は status を Append し、4000 字は「structured bullet points」にだけ付けている。従うと箇条 4000 字の後に status を足して超過しうる。超過は成功条件 4 / 子→親テキスト契約の fail。強制終了で本文が無いときも `partial` を返す指示が無い。
- Design quote: 「最終回答は構造化箇条書きで 4000 文字以下。**この上限は起動あたりであり、パス数で増やさない**」「最終回答に `status: complete|partial` と `stop_reason` を既存の文字数上限内で含める。強制終了で回答が無い場合も partial。」
- Implementation quote: 「Append `status: complete|partial` and `stop_reason`.」「Final answer: structured bullet points, **4000 characters maximum per invocation** (the cap does not grow with path count).」対比: code-writer.md:18 「Append `status: complete|partial` and `stop_reason` **inside the 800 character maximum.**」「Forced stop without a Write still returns `partial`.」
- Suggestion: code-writer と同様、status / stop_reason を 4000 字内に含め、強制停止でも `partial` を返すと書く。
- Status: open
- False-positive risk: medium — 「final answer」に Append を含める解釈もできるが、文面は箇条書きと status を分け、code-writer だけ内側と明記している。

### Issue 3 -- Severity: bug
- File: plugin/skills/bulk-reader/SKILL.md:92
- Design: §26.3, §11.3, §5
- Description: 同一ユーザー質問の Agent 起動は両 worker・バッチ・境界確認・再試行を合算して最大 4。上限後は部分結果と未完了範囲。別 agent 名や resume で迂回しない。code-writer SKILL.md はこの打ち切りを Model escalation に持つ。bulk-reader は起動前の範囲縮小（4 を超える要求は始めるな）だけ。12 パス（4 バッチ）は文面どおり開始でき、その後の許可された Sonnet 再試行が 5 回目になる。バッチ節の「4 including retries」と escalation の再試行が衝突し、上限後の partial / 迂回禁止が無い。
- Design quote: 「同一ユーザー質問の Agent 起動は両 worker・バッチ・境界確認・再試行を合算して **最大 4 回**。上限後は部分結果と未完了範囲を伝える。別 agent 名や resume で迂回しない。」§11.3 は起動前の範囲縮小と対で、partial で打ち切って開始しないことと、走中に上限へ達したあとの partial 報告を分けている。
- Implementation quote: bulk-reader SKILL.md:47 「Requests that would exceed 4 total invocations (incl. retries and boundary checks; up to 12 paths when only new paths are read) must ask the user to narrow scope BEFORE starting — do not accept and truncate into partial.」同ファイル Model escalation（92–102 行）に Shared cap / 上限後 partial / 別 agent 名禁止は無い。code-writer SKILL.md:107 「Shared cap: Agent invocations for one user question (both workers, batches, boundary checks, retries) total at most 4. After the cap, report partial plus the unfinished range. Do not bypass via another agent name or resume.」
- Suggestion: code-writer と同じ Shared cap を bulk-reader の Model escalation に置き、12 パス開始後の再試行も 4 に含めて打ち切る。
- Status: open
- False-positive risk: medium — 起動前ルールが retries を算入するので 5 回目を避ける親もいる。ただし「最大 12 パス」は 4 バッチを明示許可しており、その後の escalation に停止条件が無い。

### Issue 4 -- Severity: suggestion
- File: README.md:69
- Design: §14
- Description: README 必須文の「bulk-reader の subagent は 1 起動につき明示最大 3 パスを各 1 回 Read・maxTurns 4。関連探索と再利用は v0.1 対象外」のうち、Skills 節は 3 パス・各 1 回までで、maxTurns 4 と関連探索／再利用の v0.1 対象外が無い。エージェント frontmatter と SKILL 本文にはあるので実行時契約は変わらない。
- Design quote: 「bulk-reader の subagent は 1 起動につき明示最大 3 パスを各 1 回 Read・maxTurns 4。関連探索と再利用は v0.1 対象外」
- Implementation quote: README.md:71 「delegates bounded reads (max 3 explicit paths per invocation, each read once; child answers within a 4000-char cap, …)」
- Suggestion: Skills 節に maxTurns 4 と、関連探索・fingerprint / resume 再利用が v0.1 対象外である一文を足す。
- Status: open
- False-positive risk: low — §14 の必須文が README に無く、スキル本体にはある欠文。
