# 実際の違反報告が直るところまでの観測（2026-09-15、実測 $0.9864）

`sendback-worker-side-2026-09-15.md` §5 が残した最後の未観測
──「製品フックが**実際の違反報告**を送り返して直った」──の測定。

**観測できた。** 4実行のうち直近3実行すべてで、子が契約外の報告を出し、
SubagentStop がそれを送り返し、子が絶対パスで書き直し、その行が親まで残った。
あわせて、この測定で**除外条件の誤り1件**が実データから見つかり、直した（§2）。

## 1. 測定の組み立て

違反は確率的にしか起きないので、まず保存コーパス 566 起動を
「どの case・どのワーカーモデルが違反したか」で割り直した。

| 日付 | case | worker | block/起動 |
|---|---|---|---|
| 2026-09-15 | `compare-explicit-multifile` | **sonnet** | **8/14** |
| 2026-09-15 | `compare-edit-dense-lines` | haiku | 3/17 |
| 2026-09-14 | `reader-batch-ambiguous` | haiku | 4/14 |
| 2026-09-15 | `compare-explicit-multifile` | haiku | 1/32 |

`compare-explicit-multifile` を `--worker-model sonnet` で回したときの違反率が
群を抜いて高い（約6割）。失敗の形も一定で、**パスを `/tmp/.../` と省略する**。
これを測定対象に選んだ。

| 項目 | 値 |
|---|---|
| チェックアウト | scratchpad の detached worktree。1回目 `8303f2c`、2〜4回目 `6f8fd30` |
| 事前確認 | 各チェックアウトで `judge.py --selftest` 通過（課金前手順） |
| 測定用の差分 | `cases.json` の当該 case を `modes: ["sonnet"]` に限定（測定時のみ、未コミット） |
| 実行 | `SENDBACK=on` で `run.sh compare-explicit-multifile` を4回 |
| 実測費用 | **$0.9864**（claude 起動12回。うち case 本体は4回で $0.7732） |

## 2. 1回目で見つかった除外条件の誤り

1回目（`8303f2c`）の子の報告は次の形だった。

- `confirmed: /tmp/.../user.rb — …` が3行（いずれもパス省略＝違反）
- `unconfirmed: UserMailer は渡された3ファイルに含まれないので未確認`（正しい報告）

このとき製品フックは **`no_block`（worker reported only unconfirmed items）** を出した。
`unconfirmed:` があり使える項目が無ければ送り返さない、という
`sendback-worker-side-2026-09-15.md` §1.1 の除外が、
**事実を持っているのに形が違う報告まで**覆っていた。親はそのまま省略パスを写し、
judge は `gold_confirmed` で fail した。

直した内容（コミット `6f8fd30`）。除外を「**何も主張していない報告**」に限定する。

```python
# sendback_retention.py
def vacuous_item(line):   # `confirmed:` / `confirmed: none` / `confirmed: (none)`
# sendback_stop.py
claims = [l for l in check['items'] if not rc.vacuous_item(l)]
if demoted and not check['usable'] and not claims:
```

保存コーパスでの再実行：block **41 + 32**（従来 41 + 30）。
`unconfirmed:` と空見出しを組にした 35 件はこれまで通り送り返さない。
契約どおり 412・判定不能 39 への block は引き続き0件。親側の再実行も 1609 セッションで
block 301 と変わらない。テストは `evals/compare` 364件 OK、`evals/run.sh` pass 125 / fail 0。

## 3. 観測結果（2〜4回目、`6f8fd30`）

3実行すべてが同じ経路をたどった。

| 段階 | 記録 |
|---|---|
| 子が違反 | `SubagentStop blocked`（items 4/3/3、claims 同数、`no worker item carries a usable absolute path`） |
| 子が書き直す | 子の transcript に `Stop hook feedback:` が user 行で届き、次の報告は**フルパス**（`/tmp/claude-1000/.../work/fixtures/rails/app/models/user.rb`） |
| 2度目は見送り | `SubagentStop reblock_suppressed`（`stop_hook_active`） |
| 親が落とす | `Stop blocked`（`0 demoted, 0 altered, 4/3/3 dropped`） |
| 親が書き直す | `Stop reblock_suppressed` のあと、最終回答に逐語の `confirmed:` 行 |
| 結果 | 3実行とも `pass=4 fail=0`。オフライン再判定でも `child_items ok` / `line_retention ok` |

つまり**子側と親側の差し戻しが直列に働き、両方が直った**状態で終わっている。
子の書き直しが親に届くことはプローブで既に見ていたが、
**製品フックが実違反を選別して送り返し、最終回答まで直る**のは今回が初めての観測である。

## 4. 費用

| 断面 | 値 |
|---|---|
| case 本体 4実行 | $0.1670 / $0.2071 / $0.1915 / $0.2076 |
| 差し戻しあり（2〜4回目）の平均 | $0.2021 |
| 差し戻し無しで完走した1回目 | $0.1670 |

差分 $0.035 には**子の再生成と親の再生成の両方**が入っている。
既報の「1回の差し戻し」実測（中央値 $0.0202、`sendback-unobserved-2026-09-15.md`）と
同じ桁で、2回分としてつじつまが合う。n=4 の参考値である。

## 5. 言えること・言えないこと

- **言える**：`compare-explicit-multifile`／sonnet ワーカーという条件で、
  製品フックは実際の違反報告を選別し、子は書き直し、親まで直った（3/3）。
  契約どおりの報告を送り返した実行は今回も0件。
- **言えない**：3実行はいずれも同一 case・同一の失敗形（パス省略）である。
  `confirmed:` 行を1行も書かない形（コーパスで41件）の回復は、まだ実機で見ていない。
- 回復率の母数は今回も無い。選んだのが**違反率の高い条件**だからで、
  この 3/3 を全体の回復率として読んではならない。
- `run.nbAf4suf` の transcript には同一内容の `result` イベントが2件あった。
  費用は重複を除いて数えている。原因は追っていない。
