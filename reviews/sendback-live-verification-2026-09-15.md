# 登録済みフックの実機動作確認（2026-09-15、実測 $0.8084 / 4実行）

`d7cc50b` で `plugin/hooks/hooks.json` に登録した Stop フックが、
**CLI 2.1.272・登録経由**で動くかを確認した記録。
`sendback-remeasure-2026-09-15.md` は 2.1.271・旧実装・手作業の登録差分だったため、
配線そのものは未観測のまま残っていた（`sendback-registration-decision` §6）。

**差し戻しは2回送られ、2回とも親が再開し、2回とも全行保持まで回復した。**
既定条件（フック無効）の1実行では、同じケースが保持違反のまま fail した。

## 1. 実行条件

| 項目 | 値 |
|---|---|
| チェックアウト | scratchpad 内の detached worktree（専用） |
| 固定コミット | `d7cc50b`（登録済み） |
| 事前確認 | `judge.py --selftest` 通過（runner 内でも再実行され通過） |
| CLI | **2.1.272**（フックの記録に残る `cli_version` で確認） |
| 登録 | `hooks.json` の Stop → `check-final-answer`。手作業の差分ではない |
| 条件 | `SENDBACK=on` 3実行 ＋ 既定（off）1実行 |
| 実測費用 | **$0.8084**（on 3実行＋プローブで $0.6232、off 1実行で $0.1852） |

ケースは再測定で両周とも block が出たセルに絞った。
費用を抑えるためチェックアウトの `cases.json` から他ケースと `direct` を外している
（§4 の測定経路外の差分）。

## 2. 観測結果（`SENDBACK=on`、3実行）

| ケース / モード | フックの記録 | 再開 | 送出後の保持 | `gold_confirmed` |
|---|---|---|---|---|
| compare-explicit-multifile / auto | `blocked`（3行欠落）→ `再ブロック抑止` | resumed（親応答 10→12） | ok | pass |
| compare-explicit-multifile / haiku | `no_block`（保持 ok） | — | ok | pass |
| auto-explicit-multifile / auto | `early_stop` → `blocked`（7行欠落）→ `再ブロック抑止` | resumed（親応答 6→9） | ok | pass |

- **再開の判定**は仕様 §4.1 のとおり、block 時点に記録した親の
  assistant 応答数・ツール呼び出し数との比較による。両件ともツール呼び出しは増えず、
  **応答だけが増えている**。`原因不明` は0件。
- **再ブロック上限**（既定8）への到達は0件。2件とも1回で回復した。
  block の次の Stop は `stop_hook_active` により **再ブロック抑止**で、
  CLI 側の上限到達とは別物である（直接確認していない）。
- **`early_stop` が実機で1件**出た。子の完了前に起動した Stop を保持違反に数えない経路が、
  合成ケースだけでなく実行でも働いている。
- プラグイン読み込み確認プローブの Stop では `no_block`（子出力なし）。
  bulk-reader を使わないセッションでも起動する、という §2 の受け入れ事項どおりの挙動である。

### 2.1 入力経路

block した2件はいずれも `final_source: last_assistant_message`。
`cli_version: 2.1.272`、`below_version_floor: false`。
前提3で決めた「Stop 入力由来の回答でしか block しない」経路が、実機で機能している。

## 3. 既定条件（フック無効、1実行）

`SENDBACK` 未設定で `compare-explicit-multifile/auto` を1実行。

- フックの記録は2件とも `disabled`（`TOKEN_SHUNT_SENDBACK is off`）。
  セッションは読んでいない。
- 判定は **fail**：`gold_confirmed: gold not in confirmed:`（Notifiable / after_create /
  WelcomeEmailJob の3行が落ちたまま）。

同じケース・同じモードが、フック有効では pass、無効では fail だった。
ただし**これは1対1の観測であって、対照実験ではない**。
実行ごとのばらつきを含むため、ここから回復率や効果量は出せない。
言えるのは、前提4のスイッチが実機で効いていること、
および無効時に差し戻しが起きないことである。

## 4. 測定経路外の差分

集計（`last-run.json`）は on の3実行とも `fail`、`release_eligible: false` である。
理由は `isolation: delegate=[…] direct=None` ── 比較対象の `direct` を
チェックアウトから外したためで、フックとは無関係である。
個々の judge 判定は3実行とも pass、`gold_confirmed` true。
過去2回の試験で出た `test_aggregate` の release-eligibility 失敗と同種の差分である。

**judge の外来フック検査は通った。** 登録した Stop フックを外来と見なした実行は0件で、
前提の登録差分（`TS_HOOK_NAMES` への `"Stop"` 追加と空応答）が意図どおり働いている。

## 5. 限界

- **4実行・2ケース・1台・単一 CLI ビルド**である。2/2 の回復は母数つきの観測であって、
  一般的な回復率ではない。`sendback-remeasure` の 6/6 と合わせても 8/8 にすぎない。
- 差し戻し1回あたりの費用と再ブロック上限の終了状態は、この記録の時点では未観測だった。
  どちらも `sendback-unobserved-2026-09-15.md` で実施した
  （費用は実機8件から直接算出、上限は専用プローブで実測）。
- 子側の欠落・子出力取得不能は今回の3実行では出ていない。出ないことの確認ではなく、
  単に当たらなかっただけである。
