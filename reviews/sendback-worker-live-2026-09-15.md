# 子側の小規模実行（2026-09-15、実測 $0.8656）

`sendback-worker-side-2026-09-15.md` §5 で残した1点
──「SubagentStop の block で子が実際に再生成するか」── の確認。

**再生成する。** 専用プローブで、block 後に子が新しい報告を書き、
それが親まで届くことを確認した。
ただし**製品フックが実際の違反報告に block を出す場面は、今回も観測できていない**（§3）。

## 1. 実行条件

| 項目 | 値 |
|---|---|
| チェックアウト | scratchpad 内の detached worktree（専用、`7977ba6` 固定） |
| 登録 | そのチェックアウトにだけ SubagentStop を追加。主線は未登録のまま |
| 事前確認 | `judge.py --selftest` 通過 |
| 実行 | 比較評価 2実行（`compare-explicit-multifile` / `auto-explicit-multifile`、いずれも haiku）＋ 専用プローブ1実行 |
| 実測費用 | **$0.8656**（評価 $0.7738、プローブ $0.0918。途中停止した2回分を含む） |

### 1.1 途中停止

最初の2回は、システムのメモリ不足でバックグラウンドのまま停止させられた
（フックの記録は0〜1件、課金は1実行の途中まで）。
前景で1ケースずつ走らせ直して完走している。測定内容とは無関係の環境要因である。

## 2. 観測結果

### 2.1 比較評価 2実行（製品フック）

| 実行 | SubagentStop の記録 | 親側 |
|---|---|---|
| compare-explicit-multifile / haiku | `no_block`（`items=3`、契約どおり） | `no_block`（保持 ok） |
| auto-explicit-multifile / haiku | `no_block`（`items=4`、契約どおり） | `early_stop` → `blocked(4行)` → 再ブロック抑止 |

- フックは **SubagentStop で実際に起動し**、`agent_type` を見て
  `token-shunt:bulk-reader` だけを判定している。
- **契約どおりの報告に block を出した実行は0件**。
  オフライン再実行（563報告で block 70）の選別が、実機でも過剰に働いていない。
- 2実行とも子は契約を守ったため、**子側の block は発生しなかった**。

### 2.2 判定器の許可リスト（実機で判明）

1実行目は `foreign_hooks: SubagentStop` で fail した。
`judge.py` の `TS_HOOK_NAMES` に `"Stop"` は入れていたが `"SubagentStop"` を入れていなかったためで、
登録するなら**この1行が必要**である。追加後の2実行目では出ていない。
（2実行目の fail は `deny_bypass` で、フックとは別件。今回は追っていない。）

### 2.3 block 後の子の挙動（専用プローブ）

製品フックは契約を守った報告に block を出さないため、
**最初の SubagentStop だけを無条件に block する**使い捨てプローブを `--settings` で登録し、
`bulk-reader` に1ファイル読ませた。

- 1回目の SubagentStop：`stop_hook_active: false` で block を送出。
- 子の transcript に `Stop hook feedback:` が **user 行として届き**、
  その後に子の assistant メッセージが**2件**（出力 327 トークン）。
  つまり**子は再生成した**。
- 2回目の SubagentStop：`stop_hook_active: true`（製品フックはここで見送る）。
- 親の最終回答には、書き直された `confirmed:` 行がそのまま入っていた。
  子の再生成は**親まで届く**。
- 費用 $0.0918（親 sonnet ＋ 子 haiku、1ファイル）。

## 3. 言えること・言えないこと

- **言える**：SubagentStop の block は子に届き、子は新しい報告を書き、それが親に渡る。
  `stop_hook_active` は2回目で真になり、製品フックの見送り条件は子側でも同じに働く。
  製品フックは契約どおりの報告を送り返していない（実機2件、オフライン411件）。
- **言えない**：製品フックが**実際の違反報告**を送り返して直った、という観測はまだ0件である。
  今回の2実行では子が違反しなかった。違反の再現は確率的で、
  再測定では 4実行中2件で子側の欠落が出ていた。
- 母数のある回復率は、親側と同じくここでも出せない。

## 4. 登録に必要な差分

```jsonc
// plugin/hooks/hooks.json
"SubagentStop": [{ "hooks": [{ "type": "command",
    "command": "${CLAUDE_PLUGIN_ROOT}/hooks/check-final-answer",
    "args": [], "timeout": 10 }] }]
```

```python
# evals/compare/judge.py — §2.2。これが無いと全委譲ケースが外来フックで fail する
TS_HOOK_NAMES = {..., "Stop", "SubagentStop"}
```

`judge.py` の側は先に入れてある（登録しても評価が壊れない状態にしておくため）。
`hooks.json` への追加は**未実施**である。
