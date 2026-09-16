# 送り戻しは短縮を直すか（2026-09-16、腕 A 18 run / 腕 B 12 run）

事前登録: `reviews/sendback-rescue-design-2026-09-16.md`（`3fb9cad`）。
実行環境: CLI 2.1.272、**`SENDBACK=on`**。
固定コミット — 腕 A `3fb9cad`（現 HEAD、リマインダ入り）/
腕 B `9d4671e`（枝 `exp/no-launch-reminder-2`。`3fb9cad` から
`check-worker-launch` の matcher だけを外したもの）。
どちらも専用ワークツリー（`/tmp/ts-sbA` / `/tmp/ts-sbB`）で生成物以外の差分なし、
各チェックアウト内で `judge.py --selftest` 通過。
枠は `auto-explicit-multifile/haiku`、腕を交互に実行。費用 **$5.105**（上限 $8 の 64%）。

**結論: 送り戻しは block した 13 件すべてで親に行を書き直させた（13/13）。
ただし腕 A の 1 件は、書き直したあとに親がさらに短い締めの回答を足したため、
run の最終結果としては短縮が残った。「直った」と言えるかは
どちらのテキストを最終回答と呼ぶかで変わる。**

## 1. 結果

| # | 項目 | 腕 A（リマインダ入り、18 run） | 腕 B（リマインダ抜き、12 run） |
|---|---|---|---|
| R1 | 修復率（P1、block が出た run のうち直った数） | **1 / 1** | **12 / 12** |
| R2 | 子側修復（P2） | 0 / 0（SubagentStop の block なし） | 0 / 0 |
| R3 | 残存短縮（最終結果の判定） | **1 / 18**（`SENDBACK=off` は 2/18） | **0 / 12**（off は 16/18） |
| R4 | 誤 block（S1） | **0** | **0** |
| R5 | 再 block 上限（S4） | **0** | **0** |
| R6 | 未測定 | 0（`p1_unmeasured` / `s3_unmeasured` とも 0） | 0 |
| R7 | 費用 | — | 合計 $5.105 |

block と無関係な fail（S2）は腕 A に 2 件（10 回目・18 回目）、腕 B に 0 件。
どちらもフックが 1 件も block していない run なので、フックのせいではない
（事前登録どおりこの分類は試行ログで機械的に判定した）。

## 2. 腕 B: 装置としては完全に働いた

リマインダ抜きの構成は `SENDBACK=off` で 16/18 = 0.89 短縮していた。
同じ構成に送り戻しを入れると、**12 run すべてで Stop が block し、
12 件すべてで親が書き直し、最終結果の短縮は 0/12** になった。
再 block（`stop_hook_active`）到達も誤 block も 0 である。

（事前登録に無い比較なので記述にとどめる: 0/12 対 16/18 の
Fisher 両側 p = 1.1e-6。腕 B と off の測定は別の実験の別の run であり、
事前に比較として登録していない。）

## 3. 腕 A: 1 件だけ block し、直り、そして戻った

18 run のうち block は 1 件（15 回目）。その run の試行ログはこう並ぶ。

```
Stop  early_stop          worker still running
SubagentStop no_block     child_items ok
Stop  blocked             line_retention violation (0 demoted, 1 altered, 0 dropped)
Stop  reblock_suppressed  stop_hook_active
Stop  no_block            worker output unobtainable
```

block のあと親は**5 行すべてを絶対パス付きで書き直した**。
`sendback_probe` の P1（製品自身の `sendback_session.final_answer_from_rows`
＝ その turn の assistant テキスト全部）で見れば `line_retention` は ok、
すなわち修復成功である。

**ところが親はそのあと、1 行だけの短い締めの回答をもう一度出した。**
CLI の最終 `result` はその 1 行で、`retention_probe`（最終 `result` を読む）は
これを短縮と判定する（`kept=1`、2 行 dropped）。

### 3.1 計器が食い違ったのではなく、定義が違う

- `sendback_session.final_answer_from_rows` は**中断以降の assistant テキストを
  全部つなぐ**。フックが Stop で判断するときの定義であり、
  「親がその turn で何を言ったか」である。
- `retention_probe` は CLI の最終 `result` 1 本を読む。
  **利用者が最後に受け取る回答**である。

15 回目はこの 2 つが割れる唯一の run だった。**どちらも正しく、
問われているものが違う。** 事前登録は R1 を前者、R3 を後者で定義していたので、
両方そのまま報告する。数字を後から片方に寄せない。

## 4. 「残り 2 件は救えたか」への答え

事前登録 §2 で決めたとおり、率では答えられない（1/18 対 2/18 の
Fisher 両側 p = 1.0。完全に救えても p = 0.49 にしかならない）。
3 の法則で上限のみ: 1/18 の 95% 上限は 0.28。

言えるのは次の 3 つである。

1. **送り戻しは、短縮した親を書き直させることに 13/13 で成功した**
   （腕 A 1 件 + 腕 B 12 件）。この機構は効く。
2. **誤 block は 0/30 run。** 固定 N プローブが測った S1 = 0 はここでも保たれた。
   送り戻しを入れる側のコストは、この枠では観測されなかった。
3. **それでも最終結果から短縮が消えるとは限らない。** 15 回目のように、
   書き直したあとに短い回答を足されると、`Stop` はもう `stop_hook_active` で
   見送るので二度目は掛からない。**書き直しの後ろに何を足すかは塞げていない。**

## 5. 残ること

- 3 の (3) は新しい死角である。`reblock_suppressed` は無限ループを止めるための
  設計（`sendback-unobserved-2026-09-15.md` §1）であり、これ自体は正しい。
  問題は「修復後の追加発話」を誰も見ていないことである。直すなら
  `stop_hook_active` の下でも**回復した行が最終結果に残っているか**だけを
  見る軽い検査が要る。設計も測定もしていない。本記録では提案にとどめる。
- 腕 B は装置であって、リマインダを外した構成を推奨する根拠ではない。
  リマインダ（16/18 → 2/18）と送り戻し（block したら 13/13 で修復）は
  別々の経路で同じ損失に効いており、今回はどちらが上かを比べていない。
- 枝 `exp/no-launch-reminder-2`（`9d4671e`）は実験専用。main には入れない。
