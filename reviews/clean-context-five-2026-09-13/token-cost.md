# トークンコスト観点の独立レビュー

対象: `/home/dev/projects/skills/token-shunt` の README、現行設計の契約、plugin/skills、plugin/agents、evals/compare の一次実装・テスト。実装編集・課金する Claude 呼出は行っていない。既存レビュー、履歴、他エージェントのレポートは根拠にしていない。

高確度候補は2件。2件目と実ログ裏付けは、初回独立レビュー後に親から指定された保存トランスクリプトの追加確認による。

## [P2] 同一API message IDで分かれた本文を破棄し、隔離量と本文漏れを過少判定する

- 箇所: `evals/compare/judge.py:308-312`（呼出先: `metrics()` 338-352、`leakcheck()` 1669）。設計書の `parent_added_chars` 契約（672行付近）の「同一 message id は重複計上しない」も、usageの重複排除とcontentの重複排除を分離する必要がある。
- 条件: 1 API応答から複数の親assistantイベントが出力され、同じ `message.id` を持ちながら異なるcontentを含む。先のイベントが短いテキストまたは別ツール、後のイベントが大きい `Agent.prompt` / `Bash.command` / `Write.content` 等である。
- 影響: `parent_added_text()` は最初のイベントだけを採用し、後続の独立した内容を丸ごと捨てる。親へ実際に入った本文量を過少記録し、その文字列に依存する本文漏れ検査も見逃す。結果として委譲の隔離効果を過大に評価し、`writer_body_absent` に誤ったclean証拠を与え得る。`result.usage` 由来の親累積入出力トークン自体はこの欠陥の影響を受けない。
- 一次仕様の確認: 2026-09-13に閲覧した [Claude公式 Track cost and usage](https://code.claude.com/docs/en/agent-sdk/cost-tracking#track-per-step-usage) は、並列ツールで複数メッセージが同じIDと同一usageを共有すること、usageをIDで重複排除することを明記する。同じIDだから本文まで同一という仕様ではない。
- ローカル証拠: 同じ `msg_shared` IDの2イベント（短文 `I will delegate now.`、次に `Agent` の `prompt` に100行・2100バイトの本文）を `Transcript` に渡すと、実際のAgent引数は2100バイトなのに `parent_added_utf8_bytes` は20。本文をtargetとして既存 `leakcheck()` に渡すと `leakcheck: clean`、終了コード1（この関数ではclean）になった。コードから別IDに変えると本文を計上できるため、ID重複排除が原因と特定できる。
- 既存テストの穴: `evals/compare/test_quote_metrics.py` は同一イベントの丸ごとの再送を重複排除するテストを持つが、同一ID・異なるcontent blockのテストがない。
- 修正方針: usage用API応答IDと内容イベント/ブロックの同一性を区別する。内容はイベントUUID、tool-use ID、content blockの識別情報等で同じ内容の再送だけを排除し、同一応答からの別ブロックはすべて取り込む。
- 偽陽性になる条件: 対象CLIが常に1 API応答の全contentを最初のassistantイベントにまとめ、同一IDの後続イベントは完全な再送だけである環境では起きない。ただし公式は複数メッセージの同一ID共有をサポートし、runnerもCLI版固定をしていないため、この仮定は安全ではない。今回は課金する実機再現は行っていない。

再現の要点:

```python
body = ''.join('line-%03d secret body\n' % i for i in range(100))
def event(content):
    return {'type': 'assistant', 'parent_tool_use_id': None,
            'message': {'id': 'msg_shared', 'content': content}}
tr = judge.Transcript([
    event([{'type': 'text', 'text': 'I will delegate now.'}]),
    event([{'type': 'tool_use', 'id': 'agent1', 'name': 'Agent',
            'input': {'subagent_type': 'token-shunt:bulk-reader', 'prompt': body}}]),
])
assert len(body.encode()) == 2100
assert tr.metrics()['parent_added_utf8_bytes'] == 20
```

## 欠陥に数えなかった点

- `result.usage` を親ループ、`result.modelUsage` を親子合計、`total_cost_usd` を合計推定費用として分ける方向は、現行の公式説明と整合する。ただし複数resultを持つ実行の親usage集計は下記候補2の問題がある。親への新規本文量と累積input/outputを別に持つ判断自体は正しい。
- 子の再読取、起動プロンプト・ツール定義・要約の追加費用は存在するが、削減保証がなく、再利用をv0.2以降、48実行の費用回帰集計をPR3に分ける点は明示済みであり、それ自体を欠陥とは扱わない。
- 小仕事閾値、上限4回、1起動最大3パス、再試行を短い診断付き1回に抑える指示は不要委譲/再読取を減らす方向で整合する。読み取れない参照の失敗をworkerに報告させる例外はコスト上の改善候補だが、明示的な製品契約なので高確度バグ候補には含めない。


## [P2] 複数resultの最後のusageだけを採用し、先行する親ターン使用量を欠落させる

- 箇所: `evals/compare/judge.py:158-159`（最後のresult選択）および `evals/compare/judge.py:339-355`（そのusageを親累積として記録）。
- 条件: 1つの比較トランスクリプト内でasyncワーカーの完了通知等に応じて親が複数ターン動き、複数の親resultが出る。各resultのusageはそのターン分、modelUsage/total_cost_usdはcall全体の累積である。
- 影響: 最後の短い親返答のusageしか `parent_input_tokens` / `parent_output_tokens` に残らない。子起動、検証、修正、先行する親推論の使用量を落とし、direct/autoの親トークン比較が委譲側に有利に歪む。値が非nullなので必須観測チェックも成功する。modelUsageを単純加算すると逆に子込み合計を重複計上するため、usageと別処理が必要。
- 保存済み一次証拠: 親が追加確認対象として指定した `evals/compare/tmp/runs/run.5iqYfCeg/transcripts/auto-bulk-facts.auto.jsonl`。CLI 2.1.270、同じsession、異なるuuidで末尾88-90行に親resultが3つあり、63/85行にtask_notification、64/86行に追加initがある。result.usageは次の通り。

| result | uncached | cache read | cache creation | output |
|---|---:|---:|---:|---:|
| 1 | 8 | 114810 | 10275 | 1355 |
| 2 | 4 | 68994 | 2480 | 1113 |
| 3（現行judgeが採用） | 2 | 36492 | 947 | 97 |
| 合計 | 14 | 220296 | 13702 | 2565 |

- input3区分の合計は、同トランスクリプトの親assistantを7つのAPI message.idに重複排除した合計と完全一致した。つまり最終resultのusageが全実行累積ではないことを、独立した2通りの計算で検証できる。現在のjudgeにこのログを渡すと親input `{uncached: 2, cache_read: 36492, cache_creation: 947}`、output `97` を返す。
- 外部一次資料: [公式 Track costs in streaming input mode](https://code.claude.com/docs/en/agent-sdk/cost-tracking#track-costs-in-streaming-input-mode) はusageをターン単位、modelUsage/total_cost_usdをcallの累積と区別する。保存ログはsingle promptのCLI呼出でもasync完了後の追加親ターンが同じ性質を持つことを示す。CLI一般で常に複数resultになるとは主張しない。
- 修正方針: 親inputは親assistantのusageをAPI message.idで重複排除して合算するか、親resultのターン単位usageを一意のresultイベントで合算する。親outputは各ターンresultのusageを一度ずつ合算する。費用/modelUsageはcall累積として別に扱う。
- 偽陽性になる条件: 常に親resultが1件だけで終わる同期実行、または全resultのusage自体が累積である別形式には適用しない。指定の保存ログは現行HEAD以前の実行なので、現行スキルが必ず同じasync経路を再現するとは断定しない。ただし現行judgeが当該CLIの正規トランスクリプトを過少計測する点は再現済み。

### 候補1の実ログによる追加裏付け

同じ指定ログにはAPI message.idを共有する `thinking` → `tool_use`、`thinking` → `text` → `tool_use` が複数あり、後続contentは完全再送ではない。最初がthinkingのイベントでは現行parserのcontext_textが空になるため、ID重複排除は後続のテキスト・ツール引数をすべて捨てる。候補1は合成入力だけの懸念ではなく、対象CLI形式で既に観測されている。
