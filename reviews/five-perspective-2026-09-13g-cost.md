# トークンコストレビュー

## 範囲と方法

現行ツリー（HEAD `cb1ab7c94952df128aa9d171217177390b4a151e`）を、親コンテキスト隔離指標・API usage・推定 USD の混同と、隔離ゲートが誤った数値のまま通る会計バグに限定して読んだ。対象は `evals/compare/judge.py`、`evals/compare/run.sh` の集計、`evals/compare/cases.json` の isolation / cost 欄、README、設計書 §13 指標表と §26.5 / §26.6。`reviews/` と `docs/history/` と §27 は根拠に使っていない。

実機 `evals/compare/run.sh` は起動していない。`PYTHONDONTWRITEBYTECODE=1` で現行 `judge.py` を import し、合成 JSONL と既存トランスクリプト（`evals/compare/tmp/runs/run.xv9H1gDW/transcripts/`）で `parent_added_text` / `metrics` / `leakcheck` / `aggregate` を直接呼んだ。

## 確認した不具合

### P1: 同一 message id の thinking → tool_use 分割で tool_use.input が parent_added から落ち、isolation_ok と writer leakcheck が偽陰性になる

- 場所
  - `evals/compare/judge.py:175-196` — assistant イベントを 1 行ごとに `context_text` 化する。`thinking` ブロックは無視し、`tool_use.input` と `text` だけを載せる。
  - `evals/compare/judge.py:302-335` — `parent_added_text` が親 assistant を `("a", message.id)` で先勝ち除外する。空の thinking イベントが id を確保すると、後続の tool_use イベントは捨てられる。
  - `evals/compare/judge.py:337-352` — `parent_added_utf8_bytes` / `parent_added_chars` / `parent_added_tokens_est` は上の連結文字列だけを測る。
  - `evals/compare/judge.py:1665-1681` — `writer_body_absent` の `leakcheck` も同じ `parent_added_text()` を見る。
  - `evals/compare/judge.py:1778-1786` — `delegate_lt_direct_and_fixture` / `delegate_lt_fixture` は `parent_added_utf8_bytes` だけを比較する。
  - `evals/compare/run.sh:542-557` — 委譲の `writer_body_absent` は `judge.py --leakcheck` の終了コード 1 だけを成功証拠にする。
  - 設計 §13 指標表（`docs/2026-09-12-token-shunt-design.md:671-673`）と README（204-206 行付近）は、親 assistant の `tool_use.input`（Agent prompt / Write content / Bash command）を隔離バイトに含めると明記している。「同一 message id は重複計上しない」は同一メッセージの二重加算禁止であり、後続ブロックの破棄ではない。

- 再現
  現行 CLI の stream-json は、同じ `message.id` を thinking 専用イベントと tool_use 専用イベントに分割する。実ファイル `evals/compare/tmp/runs/run.xv9H1gDW/transcripts/auto-bulk-facts.auto.jsonl` では親 assistant 5 id のうち 4 id が `(thinking,)` の直後に `(tool_use,)` だった。現行関数では `parent_added_utf8_bytes=2761` で、親 Grep / Bash / Read の input 合計 768 バイトが文字列に含まれない。`tool_uses` リスト自体には残っている。

  合成（本文 38800 UTF-8 バイトを Agent `prompt` に載せ、thinking と tool_use を同一 id で分割）:

  | 条件 | `parent_added_utf8_bytes` | 本文が parent_added に含まれるか |
  |---|---:|---|
  | 同一 id（現行 CLI 形） | 56 | 否 |
  | id を分けた対照 | 38908 | はい |

  隔離式 `delegate < direct かつ delegate < fixture` に `direct=50000` / `fixture=38800` を入れると、現行値 56 では **isolation_ok=True**、prompt を数えた 38908 では **False**。

  `leakcheck`（生成本文を同一 id の Write `content` または Agent `prompt` に載せる）: 分割形は終了コード 1（clean）、id を分けた対照は終了コード 0（leak）。`quote_leak` を子の同期 `tool_result` に直接掛ける経路は、同じ本文を正しく検出した。

- 影響
  隔離ゲートは「親へ追加された量」を測っているつもりで、実際には thinking 先行イベントの空 `context_text` と user `tool_result` が主になる。直接モードの主量は Read の `tool_result`（user、計上される）にあり、委譲モードで親コンテキストを膨らませる Agent prompt / Write / Bash は落ちる。比較は委譲側に偏る。親が fixture 本文を Agent prompt や Write に貼っても `isolation_ok` と `writer_body_absent` が通る。`parent_added_tokens_est` も同じ過少値の `bytes/4` になる。経路契約（`tool_uses`）や子→親の `child_no_body`（`child_return_of`）はこの穴を埋めていない。

- 修正方向
  同一 `message.id` は先勝ち破棄せず、ブロックを和集合する（thinking 先行・tool_use 後続の CLI 形をテストする）。空 `context_text` で id を占有しない。`leakcheck` は修正後の `parent_added_text` に乗せるか、親 `tool_use.input` を直接見る。回帰は「thinking イベントと巨大 prompt/Write が同じ id」の RED を必須にする。既存の同一イベント二重配信テストは、和集合でも 1 回計上のまま通るべきである。

- 確信度
  高。現行 CLI トランスクリプトで欠落を観測し、合成 JSONL で isolation_ok と leakcheck の合否が反転することを現行関数で確認した。

## 不具合としない観察

- 費用削減が未証明であること自体は、README と §26.5 / §26.6 の製品方針であり欠陥にしない。
- `release_eligible` は `total_cost_usd` の null / USD 不合格を見ない。§13・§26.5 の「費用欠測は出荷 fail にしない」と一致する。`usage_tree`（`result.modelUsage`）と `parent_input_tokens`（`result.usage`）と `parent_added_utf8_bytes` は別キーで、集計が isolation に usage や USD を代入してはいない。
- `estimated_api_cost_usd` の単価付き再計算は §26.6 PR3 の費用回帰であり、現行が CLI の `total_cost_usd` を記録するだけでも出荷ゲートを偽らない。
- `cases.json` の isolation 欄は §13 必須ケース（`delegate_lt_direct_and_fixture` / `delegate_lt_fixture` / `writer_body_absent`）と B 大容量 4 件の `require_parent_tokens` に揃っている。境界ケースに isolation が無いのは §26.5 の経路表どおり。
- 同期の子 `tool_result` に対する `quote_leak`（2048 バイト超の連続引用、21 行）と async `task_notification` の summary 計上は、設計どおり子本文契約と parent_added に載る。今回の偽陰性は parent assistant の id 先勝ちに限る。
- `judge.check_parent_tokens` は cache 内訳が null でも `parent_input_tokens` オブジェクトがあれば通すが、`aggregate` は uncached / cache_read / cache_creation と output の数値を要求して fail-closed する。ランナーは必ず aggregate するため、必須親トークン欠測で `release_eligible` は立たない。
- 元ユーザープロンプトは stream-json に user イベントとして出ない。両モード共通の観測限界であり、今回の非対称な過少計上とは別。

## 検証

```text
PYTHONDONTWRITEBYTECODE=1
python3 -c "import sys; sys.path.insert(0,'evals/compare'); import judge"
# 実トランスクリプト: auto-bulk-facts.auto.jsonl
#   split ids 4/5, parent_added=2761, tool_use.input 欠落 768 bytes
# 合成 Agent prompt 38800 bytes / 同一 id:
#   parent_added_utf8_bytes=56, isolation_ok vs fixture 38800 → True
#   id 分離対照: 38908, isolation_ok → False
# leakcheck Write/Agent 同一 id: rc=1 (clean) / id 分離: rc=0 (leak)
# quote_leak(child tool_result): True
# aggregate: total_cost_usd=null でも isolation 判定とは独立
```

実機比較評価（`evals/compare/run.sh`）は未実行。オフラインで現行関数の戻り値だけを使った。
