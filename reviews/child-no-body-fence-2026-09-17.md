# worker のコードフェンス違反を送り返す（2026-09-17）

`reviews/redmine-dose-2026-09-17.md` §5 で実測された製品側の違反への対応。
**課金なし**（オフラインのテストのみ）。

## 1. 何が起きていたか

Redmine を相手にした 48 対のうち、`redmine-last-query` の auto 腕 12 run 中 **3 run**で、
bulk-reader worker が返信にコードフェンスを置き、要求された `def` 行を 1 行貼っていた:

```
def joins_for_order_statement(order_options)
```

`plugin/agents/bulk-reader.md` は**同じ禁止を 2 箇所で明示している**:

- 「No file bodies, no large quotations, **no code fences**.」
- 「Do not copy assignment lines, function bodies, or surrounding source,
  even when asked for an "exact definition" or "verbatim evidence".
  **No code fences, including around a single value.**」

**文言の不足ではない。** 書いてあるのに 25%（この case 内）で守られなかった。
3 run とも**答そのものは正しく**、`accuracy_any` は通っている。壊れたのは無本文の規則だけ。

## 2. 直し方の選択

**(a) 文言をさらに強める** — すでに 2 回明示してある。3 回目を足しても
**効いたことを示す手段が課金 run しかない**。採らない。

**(b) 機械的に送り返す** — worker の SubagentStop には既に送り返しの機構がある
（`sendback_stop.decide_worker`。パス無し項目と、宣言長より短い値の 2 件を落としている）。
**フェンスはそれらと同じ形の違反である**: worker 自身のテキストだけで判定でき、
worker が**言い直せば直る**。**(b) を採った。**

## 3. 足したもの

### 3.1 `sendback_retention.check_code_fence(text)`

行頭（インデント可）の ` ``` ` または `~~~` を探し、あれば VIOLATION。

- **インラインのバッククォートは対象外。** 契約が禁じているのはフェンスであり、
  `` `deliver_notification` `` は**適合した報告の書き方そのもの**である。
  ここを広げると、契約を守っている報告を送り返してしまう。
- 二重バッククォート（`` ``x`` ``）もインラインなので対象外。
- 開きと閉じの両方を `fences` に載せる。**worker には消す行がそのまま見える。**

### 3.2 `sendback_stop` への配線

`decide_worker` に `code_fence` チェックを追加し、**判定は最後**に置いた:

| 優先 | 違反 | 理由 |
|---|---|---|
| 1 | 使えるパスが無い | 事実そのものが親に渡らない |
| 2 | 宣言長より値が短い | 値が壊れている |
| 3 | **コードフェンス** | 事実は渡る。**余計なものが付いている** |

**送り返しは 1 回につき 1 つの修正だけを求める。** 上位 2 つは
「事実が使えない」であり、フェンスは「本来無いものが増えている」なので、後ろに置いた。

**「unconfirmed しか報告していない」経路でもフェンスは落とす。** あの分岐は
「`confirmed:` 行を捏造させない」ために在る。**フェンスを消すのは捏造ではない。**

ループにはならない: `stop_hook_active` が再ブロックを止めるので、
1 つの停止につき最大 1 回。

## 4. テスト（13 件。**実装より先に書いて RED を確認した**）

`test_retention_checks.CodeFenceTests`（8 件）:
適合報告は OK / **実測された 1 行フェンスは VIOLATION** / `~~~` も / インデントも /
**インラインのバッククォートは OK** / 二重バッククォートも OK / 空の報告は OK /
reason に開き行が出る。

`test_sendback_hook.WorkerTests`（5 件）:
**実測された形が BLOCKED になる**（reason に `code fence` と `prose`）/
フェンス無しは `checks['code_fence'] == 'ok'` で NO_BLOCK /
**パス欠落がフェンスより優先** / **宣言長違反がフェンスより優先** /
**unconfirmed だけの報告でもフェンスは落とす**。

## 5. 確認

`unittest discover -s evals` **288 OK**、`-s evals/compare` **581 OK**、
`judge.py --selftest` 全項目 pass（`child_no_body` の RED/GREEN 自己診断を含む）。
`token-shunt.zip` は再生成していない。

## 6. **この修正は §1 の 3/48 という数字を動かさない**

比較 eval は `TOKEN_SHUNT_SENDBACK=off` で走る
（`reviews/sendback-registration-decision-2026-09-15.md` §3.4。
baseline が送り返しではなくスキルを測るため）。
**したがって §1 の違反率は「文言だけで守られる率」であり、本修正の後も同じ値が出る。**

**本修正が効くのは製品の既定値（送り返し on）の側である。**
両者は別物なので、**eval の数字が下がったことをもって直ったとは言わない。**

## 7. 直していないこと

- **`plugin/agents/bulk-reader.md` の文言は変えていない**（§2(a)）。
- worker が送り返しを受けても `maxTurns: 7` を使い切っていれば言い直せない。
  その場合は従来どおり partial で終わる。**送り返しは保証ではなく一段の防御である。**
- 送り返しが実機で何割を直すかは**測っていない**。測るなら別に事前登録が要る。
