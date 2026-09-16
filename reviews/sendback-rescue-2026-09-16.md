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

## 6. 実装（2026-09-16、§5 の死角）

§3 の 15 回目 —— 送り戻しに全行で答えたあと、親が短い締めをもう一度出し、
最終結果からは行が消えた —— を塞いだ。

### 6.1 何を見るか（1 問だけ）

`stop_hook_active` の下で**回答を判定し直さない**。見るのは 1 問だけである:

> **その turn ですでに行を言い直したのに、締めの 1 通でまた落としたか。**

`sendback_retention.check_relapse(child_texts, recovered, final)`:

- `recovered` = セッション行にある**この turn の親のテキスト**。Stop 時点では
  turn を終える 1 通はまだセッションに入っていない（`sendback_session`
  `final_answer_from_rows` の注記）ので、これは「締めの前に言ったこと」である。
- `final` = Stop 入力の `last_assistant_message`（＝締めの 1 通）。
- `recovered` の line_retention が **ok**、かつ `final` が **violation** のときだけ
  violation。落ちた行を返す。
- `recovered` も violation なら **undetermined**。それは「直っていない修復」であって
  再発ではない。そこで block するのは `stop_hook_active` が止めている
  ループそのものなので、しない。

### 6.2 どう塞ぐか（1 セッション 1 回だけ）

`sendback_stop.decide_relapse()` が `stop_hook_active` の分岐を受け持つ。
block できるのは上の violation のときだけで、しかも**1 セッションにつき 1 回**。
予算は `$TMPDIR/token-shunt-sendback-$UID/<sha256(session_id)>.json` に持つ
（reader の state と同じ置き方・同じ権限確認）。

**state が使えなければ予算は無い＝ block しない。** session_id が無い、
一時ディレクトリが他人のもの、書けない —— いずれも抑止のままである。
無制限の再 block こそがこのフックが始めてはいけないループなので、
「分からなければ止めない」ではなく**「分からなければ塞がない」**を選んだ。

文面は「言い直したのに短い回答で終わった。**最後の 1 通が回答なので**、
その中に行を逐語で入れろ」。最初の block（`block_reason`）とは別の文言である。

### 6.3 仕様の変更点（明記）

`reviews/sendback-trial-spec-2026-09-15.md` §6 は
「`stop_hook_active` が真なら **transcript を読まずに**成功を返す」と書いていた。
**この 1 行を変えた。** 今は読む。読んだ結果として block しうるのも、
再発の 1 形だけである。

変わらないもの: 抑止を「CLI の上限到達」とは決して記録しない（§4.4）。
`reblock_suppressed` の記録は残り、理由文字列に relapse の判定結果が付く。

### 6.4 テスト

- `evals/compare/test_retention_checks.py` に `RelapseTests` 6 件
  （言い直して落とした / 最後まで残した / 修復が landing していない /
  比較材料が無い / ワーカー側が判定不能 / ファイルが消えた）。
- `evals/compare/test_sendback_hook.py` に `RelapseTests` 8 件
  （1 回だけ block する / block 記録が自分の checks を持つ〔S1 の数え方を壊さない〕/
  2 回目は抑止 / 行を残した締めは抑止 / 修復失敗は抑止 /
  `last_assistant_message` が無ければ抑止 / session_id が無ければ抑止 /
  スイッチ off は従来どおり）。
- 既存の `test_stop_hook_active_records_suppression_not_a_cap` は、
  「transcript を読まない」という主張を落として書き換えた。
  **意図して変えた挙動なので、テストも意図して変えたと記録する。**
  「上限とは記録しない」の主張はそのまま残してある。

オフライン: `unittest discover -s evals` 279 OK、`-s evals/compare` 475 OK、
`judge.py --selftest` 全項目 pass、`evals/run.sh` 240 pass / 0 fail。

### 6.5 未実施

実機では確認していない。再発は 30 run に 1 件の頻度なので、
**この修正が効くことを実機で見るのは安くない**（同じ枠で 1 件出すのに
$5 前後、複数件なら十数ドル）。
リマインダを外した腕（block が毎回出る構成）なら再発も作りやすいが、
それは「再発を高頻度で作る装置」を別に設計するということであり、
本記録では設計していない。課金測定は指示があるまで走らせない。

`token-shunt.zip` は再生成していない（指示があるときだけ）。
