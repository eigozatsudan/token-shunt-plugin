# Stop 入力経路の調査とオフライン検証（2026-09-15、課金なし）

`reviews/sendback-trial-2026-09-15.md` は、Stop 起動時点で親の最終回答が
セッション transcript に無く、差し戻しが6実行中0件だったことを記録した。
本稿はその入力経路を調べ、修正をオフラインで検証する。モデルは1回も起動していない。

## 1. CLI が Stop フックに渡すもの

CLI 2.1.271 のバイナリから、Stop／SubagentStop 入力スキーマとその生成箇所を確認した。

| フィールド | 内容 |
|---|---|
| `last_assistant_message` | **「停止直前の最後の assistant メッセージの本文。transcript を読んで解析する必要をなくす」**（スキーマの説明文そのまま）。optional |
| `background_tasks` | 「このセッションに登録された進行中の作業（running/pending + backgrounded）。『セッションが終わった』のか『待ちで止まっている』のかをフックが区別できる」。要素は `id` / `type`（`shell`・`subagent`・`monitor` 等）/ `status` / `description` / `agent_type` |
| `session_crons` | 予定されている起床 |
| `stop_hook_active` | 既出 |
| `transcript_path` | 既出 |

生成箇所では `last_assistant_message` が**メモリ上のメッセージ列の最後の
assistant メッセージ**のテキストから作られている。transcript への書き込みを
経由しない。これが §1 の欠落に直接対応する取得経路である。

SubagentStop も同じ2フィールドを持ち、加えて `agent_id`・`agent_type`・
`agent_transcript_path` を持つ。

あわせて、再ブロック上限の既定値が **8**（`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` で変更可）で、
到達時に CLI が
「A hook blocked the turn from ending N consecutive times — overriding and ending turn.」
を出すことも確認した。`上限到達` を直接示す証跡はこれである
（`再ブロック抑止` との区別は `sendback-trial-spec` §4.4 のとおり）。

## 2. 取り込みの設計

`evals/compare/sendback_hook.py` を次のように変えた。

### 2.1 停止しようとしている親の回答であることの確認

- `hook_event_name` が `Stop` でない、または `agent_id` を持つ入力は
  **判定しない**（`not a parent Stop`）。SubagentStop は子の結論であり、
  親の契約を当てる対象ではない。
- `last_assistant_message` を採るのは、その本文が**今回のターンのもの**である場合に限る。
  同じ本文が transcript の最後の割り込みより前にも現れている場合は、
  過去ターンの説明文を渡されたとみなして採用せず、`判定不能` にする。
  CLI が渡すのは「最後の assistant メッセージ」であり、ターンが道具結果で
  終わった場合それはターンを終わらせたメッセージとは限らないためである。
- `last_assistant_message` が無ければ従来どおり transcript から特定する
  （記録に `final_source` としてどちらを使ったかを残す）。

### 2.2 子の完了前に起動する Stop の分離

`background_tasks` に `type: "subagent"` かつ未完了（`running` / `pending` /
`in_progress` / `queued` / `backgrounded`）の項目があれば、
**判定せず `early_stop` として記録する**。実機検証では6実行中3実行で
子の報告前にも Stop が起動していた。まだ届いていない報告を
親の保持違反に数えないための分離であり、`no_block`（親は問題なし）とも
区別して記録する。

### 2.3 transcript の反映待ちは採らない

反映待ちは実装していない。`last_assistant_message` があるため不要であり、
かつ**反映がフック終了に依存しないことを未確認**だからである。
依存していれば待つほど固まるため、確認できるまでこの方式は採らない。

## 3. オフライン検証

### 3.1 実機検証の6実行を再生

実機検証で得た7セッション（プローブ1 + ケース6）に、
CLI と同じ形で回答を渡して `decide()` を再生した。

| 結果 | 件数 | 内訳 |
|---|---|---|
| `blocked` | **2** | いずれも 4行欠落 |
| `no_block` | 5 | 保持 ok 1／子側の欠落 3／子出力取得不能 1（プローブ） |

7件すべてで `final_source` が `last_assistant_message` になり、
実機で `final answer not identified` だった6件が判定可能になった。
実行終了後の transcript に対する再生結果（`sendback-trial` §2.2 の2件）と一致する。

### 3.2 保存コーパス

同じ入力経路で保存済み実セッションを再生し、`blocked` 317 / `no_block` 157。
母数が 456 から 474 に増えているのは、**実機検証の18実行自身が
セッションを18件追加した**ためで、内訳の増分（308→317）もそこに対応する。
判定不能・子側の欠落に block を出した実行は0件のままである。

### 3.3 テスト

`evals/compare/test_sendback_hook.py` を14件から21件に増やした。追加分は
入力経路（イベントの回答を使う／保持済みなら送らない／過去ターンの本文は拒否する／
イベントが無ければ transcript に戻る）、早期停止の分離（子が走っている間は判定しない／
完了した子は妨げない／shell 等は子ではない）、SubagentStop を親として判定しないこと。

検証状態: `evals/compare` 335 tests OK、`./evals/run.sh` 125 pass / 0 fail。
フックは依然として `plugin/hooks/hooks.json` に登録していない。

## 4. 残件

| 項目 | 状態 |
|---|---|
| 小規模な再測定 | 本稿の結果を見て判断。実施するなら `sendback-trial-spec` の観測項目のまま |
| 差し戻しの回復能力 | **未評価**。block が送られた実行がまだ無い |
| transcript 反映のフック終了依存 | 未確認。採らない方針なので測定の前提ではない |
| Stop／SubagentStop の製品実装 | 保留 |
