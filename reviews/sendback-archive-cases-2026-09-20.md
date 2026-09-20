# 差し戻しをアーカイブのケースに当てた（実機 9 run、$2.2285、2026-09-20）

事前登録: `reviews/sendback-archive-cases-design-2026-09-20.md`
（`98e2dbb`、事前チェック `82387fc`、逸脱記録 `6415a8b`）。
**登録後に判定基準を書き換えていない。** 逸脱は走る前・再開前に記録した。

行データ: `reviews/data/sendback-archive-cases-2026-09-20.csv`
（9 行、sha256 `9028a10549096dd760eb6f9a6f89867bfc07bf41d8f73e458fdbc1c18af8eb92`）。
transcript・セッション・試行ログ: `~/measurements/sendback-2026-09-20/`
（`sha256sums.txt` 99 ファイル、`sha256sums-sessions.txt` 18 ファイル）。
**新しい採点器を書いていない。** 判定は出荷中の
`plugin/hooks/sendback_retention.run_all` と `sendback_session.check_inputs`、
費用は `spend.py`、行は `pairs.py` が返す。

## 0. 実行

| | |
|---|---|
| 腕 | **単腕 `SENDBACK=on`**（§3 のまま。対照は取らない、§2 の世代差のため） |
| ケース | `django-subthreshold-bare` / auto |
| 完走 | **9 run**（n=10 には届かず） |
| 支出 | **$2.2285**（1 run $0.2476） |
| 停止 | driver 自身: `stop: $2.2285 plus the $0.3000 reserved for the next run reaches the $2.5000 cap` |
| commit | `98e2dbb`（detached worktree `~/wt/ts-sendback`） |

**n=10 に届かなかったのは 1 run の実費が §4 の見積もり（平均 $0.1779）より
高かったためである。** §4 の「届いた本数でそのまま書く」に従い、
**n を揃えるための追加支出はしていない。**

## 1. 主要指標: block を受けた親は行を戻したか

**発火は 9 セッション中 1 本（`run.hFXszq8W` / `ab97f638`）、block は 2 ターン。**

試行ログ（`*.sendback.jsonl`）の系列:

| # | event | outcome | reason | 親の到達点 |
|---|---|---|---|---|
| 0 | SubagentStop | no_block | worker items ok | — |
| 1 | Stop | **blocked** | 0 demoted, 0 altered, **7 dropped** | 応答 5・行 34 |
| 2 | Stop | reblock_suppressed | stop_hook_active | — |
| 3 | Stop | **blocked** | 0 demoted, 0 altered, **7 dropped** | 応答 **7**・行 **44** |
| 4 | Stop | reblock_suppressed | stop_hook_active | — |

セッション全体を出荷中のチェッカに掛けた最終状態:

```
line_retention: status=ok  kept=7  demoted=0  altered=0  dropped=0  unjudged=0
```

**軌跡は 7 → 7 → 0 である。**

> **block を送った 2 ターンのうち、行が戻ったのは 1 ターン（2 回目）。
> 1 回目の block では戻らなかった。**

**介入が届いたことの証拠を、結果とは別に持っている。** #1 と #3 の間で
親の到達点が **応答 5→7・行 34→44** へ動いている —— 親は 1 回目の block を
受けて**再開し、応答を 2 つ足した上で、同じ 7 行をまた落とした。**
「無視された」ではなく「**1 回では足りなかった**」である。
（`verify-the-intervention-arrived`: 届いた証明は出力の分岐で取る。）

最終回答には `confirmed:` 行が 7 本そのまま載っている（逐語、`kept=7`）。

## 2. 副次

| | 事前登録 | 実測 |
|---|---|---|
| 副次 1 | 再ブロック抑止が block ごとに 1 回 | **2 block に 2 件**。過不足なし |
| 副次 2 | 上限到達 0 件（CLI 既定 8 回） | **0 件**。当該セッションの Stop は 4 回で、上限の半分 |
| 副次 3 | relapse の件数 | **0 件**。抑止 2 件はいずれも `relapse undetermined` |

**§5 の「上限到達が出たら `sendback-remeasure` §2.4 を覆す」は発生しなかった。**
ただし**2 回の block を要した**ので、「1 回の差し戻しで足りる」という読み方は
本ブロックでは支持されない —— 上限に触れなかったことと、
1 回で足りたことは別である。

## 3. 発火率: 9 セッション中 1 本

Stop 時点の判定内訳（ケースのセッションのみ。`_probe_load` の 9 件は
worker を起動しないので `worker output unobtainable` になる。除外する）:

| | 件数 |
|---|---|
| `retention ok`（違反なし） | **8 セッション** |
| `blocked`（違反あり） | **1 セッション** |

**アーカイブの 55.6%（50/90 ターン）とは比較しない。** §2 が
比較しないと決めた理由がそのまま効いている: 母集団の単位が
**ターン対セッション**で違い、世代も `77ef7b1` を挟んで違う。
**ここで言えるのは「9 セッション中 1 本で発火した」までである。**

## 4. 正確性と合否（副産物）

| | 値 |
|---|---|
| `auto_accuracy` | **9/9** |
| `auto_pass` | **5/9** |

落ちた 4 本の内訳は差し戻しと無関係である:

- **`child_msg_cap` 3 本**（`3wusqHhT` 4108 / `fj3nHRRm` 5150 / `yregs32O` 4922 文字 > 4000）。
- **`G1Xd4PM1` 1 本は委譲そのものが起きなかった** ——
  `token-shunt:bulk-reader` の Agent 呼び出しが 0 で、
  **親が corpus を 25,901 B 直接読んだ。** 主要指標の側から見ると
  これが 9 本中で最も汚染の大きい run である。
  親の読み取りバイトは他 8 本が 0・376・735 B で、**この 1 本だけ桁が違う。**

**block した `hFXszq8W` は `pass=1` である。** 差し戻しが合否を壊していない。

## 5. 答えていないこと

1. **n=9、発火 1 セッション、block 2 ターン。** 率を主張できる規模ではない。
   「戻った 1/2」は**2 回という分母の上の話**である。
2. **ケースが 1 種類しかない。** `django-subthreshold-bare` だけで、
   ケース間の分散は測っていない。
3. **対照を取っていない**（§2 の設計どおり）。**「差し戻しの有無で比べた」とは
   言えない。** 言えるのは同一実行内の前後だけである。
4. **1 回目の block で戻らなかった原因は分けていない。** 親が指示を読み落としたのか、
   読んで別の形で答えたのかは、本ブロックの記録では区別できない。
5. **既定は動かさない。** `run.sh:396` のハーネス既定 `SENDBACK=off` は
   意図された設計であり（登録判断 §3.4）、**本ブロックはそれを変える根拠ではない。**
   プラグイン側の出荷既定（フック登録）も本ブロックでは触っていない。
