# 実セッションからの検査入力抽出（2026-09-15、追加課金なし）

`evals/compare/session_extract.py`。保存済みの実セッション 456 件で
抽出から3検査まで通した。フックは実装しない。

## 1. 対応づけ

`agent_id` が3つの経路を結ぶ鍵である。

| 経路 | 鍵 |
|---|---|
| `<task-notification>` の `<task-id>` | `agent_id` |
| `subagents/agent-<id>.jsonl` / `.meta.json` | ファイル名が `agent_id` |
| `<output-file>` | ファイル名が `agent_id` |
| 親の Agent 呼び出し | `<tool-use-id>` = `.meta.json` の `toolUseId` |

`.meta.json` が `agentType` を持つので、bulk-reader の起動だけを選べる。

**同一 `agent_id` に複数の通知がある。** 進捗通知と完了通知が同じ
`task-id` を共有するため、`<status>completed</status>` かつ `<result>` を
持つ最後の通知だけを答えとして扱う。これを区別せずに集計すると、
633 組中 29 組が不一致に見えていた（実際は進捗通知を拾っていた）。

**`<output-file>` は答えではない。** 子セッションの jsonl であり、
`subagents/agent-<id>.jsonl` と同じ内容である（本文 71KB 対 1.3KB で確認）。

## 2. 完全性の比較

通知本文と子トランスクリプト末尾の本文を突き合わせる。
そのままでは一致しないので、2つの符号化を戻す必要がある。

| 差異 | 実体 | 扱い |
|---|---|---|
| `&lt;` などの XML エスケープ | 通知本文は必ずエスケープされる | `html.unescape` してから比較 |
| `[harness: … neutralized …]` の前置き | 制御タグ無効化の注記 | 除去して比較 |
| `NOTE: … PARTIAL output …` | ターン上限で打ち切られた出力 | **判定不能**（親の欠落ではない） |

632 組を照合した結果、エスケープを戻すと 619 組が一致し、残りは
PARTIAL 注記（17）と進捗通知の取り違え（29→0）で説明がついた。

`_reconcile` の結果は5種類。

| 値 | 意味 | 検査への影響 |
|---|---|---|
| `complete` | 2経路が一致 | 判定可 |
| `transcript_only` | 完了通知に `<result>` が無い | 子トランスクリプトを使用 |
| `notification_only` | 子トランスクリプトが無い・空 | 通知を使用 |
| `partial` | ハーネスが不完全と明示 | **判定不能** |
| `mismatch` | 説明のつかない相違 | **判定不能**（推測しない） |

456 セッションの内訳: `complete` 389 / `transcript_only` 133 /
`partial` 5 / `unavailable` 3、`mismatch` 0。

## 3. 最終回答の特定

**「最後の assistant 本文」では足りない。** 実セッションには
「The worker is reading the three files now — I'll report back once it
finishes.」のような**途中の説明**が assistant 本文として残っている。

採用した規則: 親のツール呼び出し・ツール結果・ワーカー報告
（`<task-notification>`）・ユーザー入力のいずれかを「中断」とみなし、
**最後の中断より後に現れた assistant 本文だけ**を最終回答とする。
中断より後に本文が無い場合は `no_final_text` として**判定不能**にする。
これはツール結果でターンが終わった形であり、CLI が Stop フックの
差し戻しを破棄する経路と同じ形である
（`reviews/stop-hook-spec-2026-09-15.md` §3）。

> 保存済み 456 セッションはすべて最終本文を持っていた（`final_ok` 456）。
> `no_final_text` の経路は合成テストでのみ確認している。

## 4. 無許可の降格

有効な絶対パスを持つワーカー行を、親が `unconfirmed:` に書き換えた場合は
**保持違反**として `demoted` に計上する。許可された降格（ワーカー行が
そもそも絶対パスを欠く場合）は、その行が転記対象にならないため計上されない。

**照合はパスではなく本文で行う。** 最初の実装はパス一致でも降格と
みなしており、実データで4件を検出したが、目視すると
**同じファイルの別の事実**を親が正当に `unconfirmed:` としたものだった。
本文一致を必須にしたところ、実コーパスでの `demoted` は 0 件になった。
この検査は現時点では合成テストでのみ発火している。

## 5. 456 セッションでの結果

| 検査 | ok | violation | undetermined |
|---|---|---|---|
| `child_items` | 377 | 68 | 11 |
| `file_coverage` | 124 | 253 | 79 |
| `line_retention` | 69 | 308 | 79 |

ワーカー行の内訳: 保持 156 / 改変 162 / 欠落 840 / 降格 0。

これは製品契約（全 `confirmed:` 行の逐語転記）に対する違反件数であり、
`gold_confirmed` の合否とは別の量である
（`reviews/stop-hook-spec-2026-09-15.md` §4.2）。

## 6. 残件

- Stop / SubagentStop フックの実装は保留。
- `no_final_text` と `mismatch` は実データで未発生のため、
  合成テストでのみ確認している。
- 判定器（`judge.py`）への組み込みは行っていない。
