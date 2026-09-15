# Stop フック実装前の仕様確認（2026-09-15、実データ・CLI 2.1.271）

`reviews/final-answer-detection-2026-09-15.md` §4 の未確認3点を、
実セッションのトランスクリプトと CLI 実体から確認した。実装は行わない。

## 1. 子出力の取得方法

**親の transcript から取得できる。**ただし tool_result 経由ではない。

| 経路 | 実体 | 確認 |
|---|---|---|
| Agent の `tool_result` | 起動メタデータのみ（`Async agent launched successfully` と `agentId`） | **子の本文を含まない** |
| `<task-notification>` を含む `user` メッセージ | 子の最終本文を**インラインで含む**（`<result>` と `<usage>` 付き） | 親 jsonl 内に存在。`confirmed:` 行が一致 |
| `<output-file>` | `…/<session-id>/tasks/<agent-id>.output` | 実在を確認 |
| 兄弟ディレクトリ | `…/<session-id>/subagents/agent-<id>.jsonl` と `.meta.json`（`agentType` を含む） | 実在を確認 |

重要な訂正: 実セッションの親 jsonl に `isSidechain: true` の行や
`parent_tool_use_id` は**現れない**。評価用 stream-json とは構造が違う。
したがって、評価ハーネス用に書いた抽出（`parent_tool_use_id` 付き
assistant メッセージ）は実フックにそのまま流用できない。
実フックは `<task-notification>` 本文、または `subagents/` の
`agent-*.jsonl`（`agentType` で bulk-reader を判別可能）を読む必要がある。

## 2. 最終回答の特定

親 jsonl の最後の `assistant` エントリのうち、`isSidechain` が偽で
本文テキストブロックを持つもの。子の本文は `user` 型エントリとして
入るため、`assistant` に限ればワーカー出力と混ざらない。

## 3. 差し戻しが有効な終了経路

CLI 2.1.271 の文字列より。

| 事項 | 内容 |
|---|---|
| 差し戻し | `decision: "block"` + `reason`（Stop / PostToolUse / UserPromptSubmit 用） |
| 停止 | `continue: false` + `stopReason`。「`continue` - Set to `false` to block/stop (default: true)」 |
| **無効になる経路** | `[end-turn] Stop hook block discarded (turn ended by {tool result / MCP end-turn / loop tick}, no model re-invoke)` |
| 無限ループ防止 | `For Stop/SubagentStop hooks, check stop_hook_active in the input and return success while it's true. Set CLAUDE_CODE_STOP_HOOK_BLOCK_CAP to raise this limit.` |
| 子文脈での変換 | `Converting Stop hook to SubagentStop for …` |
| 入力 | Stop は `transcript_path`。SubagentStop は `agent_id`・`agent_type`・`agent_transcript_path` |

つまり **停止（`continue:false`）と差し戻し（`decision:"block"`）は別物**で、
差し戻しはモデルの通常 end-turn でのみ有効。ツール結果・MCP の end-turn・
ループ tick で終わったターンでは破棄される。この経路では検査が素通りする。

### 3.1 子側の違反は SubagentStop が正しい位置

SubagentStop は `agent_type` と `agent_transcript_path` を受け取るので、
「ワーカーが実在パス付き `confirmed:` を返したか」はそこで検査できる。
親の Stop で検出しても、親には写す対象が無く回復できない
（`reviews/final-answer-detection-2026-09-15.md` のクラス B、14件）。

## 4. オフライン検査（実装済み・課金なし）

`evals/compare/retention_checks.py`。3つを**別々に**返す。

| 検査 | 何を見るか | 回復手順 |
|---|---|---|
| `child_items` | 子の出力を取得できたか、写せる項目があるか | 再委譲（または SubagentStop で子に再出力させる） |
| `file_coverage` | 子が挙げたファイルを最終回答が全て引用しているか | 親へ差し戻し |
| `line_retention` | 各 `confirmed:` 行が逐語で残っているか（保持／改変／欠落） | 親へ差し戻し |

**被覆は契約の代替ではない。** 製品契約は全 `confirmed:` 行の逐語転記で
あり、被覆は同一ファイルからの2件目の欠落を原理的に検出できない。
`test_retention_checks.py` にその合成ケースを置いた
（`test_coverage_cannot_see_a_second_fact_from_the_same_file`：
被覆 ok・逐語検査が欠落を指摘）。

**判定不能を親の欠落と混同しない。**

| 状況 | 扱い |
|---|---|
| 子出力を取得できない | `undetermined` |
| 引用パスのファイルが実在しない（移動・削除） | `undetermined` |
| パスが中略（`/tmp/.../x.rb`）または相対 | `violation`（本文だけで判定できる） |
| 子の行が `unconfirmed:` に降格されている | 転記対象に数えない（降格は契約が指示する回復手順） |

### 4.1 保存済み実行での結果

旧 spec 実行は全コーパスから除外（期待パスが解決し得ないため）。

| コーパス | 実行 | `child_items` (ok/違反/不能) | `file_coverage` | `line_retention` |
|---|---|---|---|---|
| 今回の測定 | 18 | 12 / 6 / 0 | 5 / 7 / 6 | 5 / 7 / 6 |
| 過去の保存実行 | 103 | 96 / 5 / 2 | 17 / 79 / 7 | 8 / 88 / 7 |

### 4.2 gold 判定との関係（一致率ではなく差の所在）

| gold | `line_retention` | `file_coverage` | 実行数 |
|---|---|---|---|
| 不成立 | violation | violation | 86 |
| 不成立 | undetermined | undetermined | 13 |
| 成立 | ok | ok | 13 |
| 成立 | **violation** | ok | 9 |

最下行の9件は、**契約違反だが gold 判定は通る**実行である
（子の行を言い換えつつ、パスと gold 語を残した）。
前回の記録ではこれを「誤検出」と書いたが、それは誤り。
現行契約は逐語転記なので、これらを違反と呼ぶことは契約に照らして正しい。
表は「gold との一致」であって「契約遵守の検出精度」ではない。

## 5. 残る未確認

- `<task-notification>` の本文が常に子の最終回答全体を含むか
  （長い出力での打ち切りの有無）は未確認。打ち切りがあるなら
  `<output-file>` か `subagents/agent-*.jsonl` を読む必要がある。
- 判定器（`judge.py`）へは組み込んでいない。既存の合否の意味を
  変えないため、当面は独立モジュールとテストのみ。
- Stop フック自体の実装可否は未判断。§3 の破棄経路がある以上、
  これは全面的な強制にはならない。
