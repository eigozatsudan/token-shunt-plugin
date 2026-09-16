# 固定 N の送り戻しプローブ 実行記録（2026-09-16、実測 $4.07）

事前登録は `reviews/sendback-fixed-n-probe-design-2026-09-16.md`。
本記録は設計をコミットした**後**に走らせた結果で、項目・N・判定基準は
すべて事前に決めたものである。

測定用チェックアウト: `/tmp/ts-sendback-probe`（`git worktree`、**`4c25a8d`** に固定）。
生成物以外の差分なし、そのチェックアウト内で `judge.py --selftest` 全項目 pass、
`unittest discover -s evals/compare` 432 OK。CLI **2.1.272**
（`9346d19` の A/B、`sendback-live-verification` と同じビルド）。

ラン: 1 周目 `run.DVxvf8AH`、2 周目 `run.fhiO8OrA`、3 周目 `run.6jyTJigm`。
条件は `SENDBACK=on`、`SLOTS` に §4 の 8 枠。`cases.json` は変更していない。

## 1. 事前登録項目の結果（N = 24 run）

| # | 項目 | 1 周 | 2 周 | 3 周 | 合計 |
|---|---|---|---|---|---|
| P1 | 親の修復 | 2/2 | 5/5 | 5/5 | **12 / 12** |
| P2 | worker の修復 | 0/0 | 2/2 | 0/0 | **2 / 2** |
| S1 | 誤 block | 0 | 0 | 0 | **0** |
| S2 | block 0 件での fail | 1 | 2 | 0 | 3 |
| S3 | `not_resumed` | 0 | 0 | 0 | **0**（`s3_unmeasured` 0） |
| S4 | 再 block 上限 | 0 | 0 | 0 | **0** |
| C1 | 費用 | $1.347 | $1.445 | $1.274 | **$4.066** |

Wilson 95% 下限: P1 12/12 で **0.76**。既存の親側 6/6（`sendback-remeasure`）と
子側 3/3（`sendback-worker-repair`）を合わせた 9/9 に積むと 21/21 で **0.85**。
S1・S4 は 0/24 なので、ルール・オブ・スリーの上限は **0.12**。
「誤 block は起きない」ではなく「24 run では起きなかった」である。

P1 は §3 のとおり**完了後のセッションの再判定**で数えた。差し戻しに答えたターンの
終わりは `stop_hook_active` で見送られ `checks` を残さないため、試行ログだけでは
読めない（§7.3）。分母は run、P2 の分母は worker。

## 2. block の内訳（12 件）

| 周 | ケース / モード | 欠落行 | worker block |
|---|---|---|---|
| 1 | compare-hook-deny-route / auto | 3 | 0 |
| 1 | reader-batch-ambiguous / auto | 1 | 0 |
| 2 | auto-routing-boundary-known-range-deny / auto | 3 | 1 |
| 2 | compare-edit-dense-lines / auto | 3 | 1 |
| 2 | compare-explicit-multifile / sonnet | 3 | 0 |
| 2 | compare-hook-deny-route / auto | 3 | 0 |
| 2 | reader-batch-ambiguous / auto | 3 | 0 |
| 3 | auto-bulk-facts / haiku | 1 | 0 |
| 3 | auto-routing-boundary-known-range-deny / auto | 2 | 0 |
| 3 | compare-edit-dense-lines / auto | 2 | 0 |
| 3 | compare-hook-deny-route / auto | 3 | 0 |
| 3 | reader-batch-ambiguous / auto | 2 | 0 |

`compare-hook-deny-route/auto` は 3 周とも block し、3 周とも回復した。
§4 が結果依存の選定であることは変わらないが、少なくともこの枠では
違反が毎周再現し、毎周直っている。

**保持の修復は他の契約違反を直さない。** `reader-batch-ambiguous/auto` は
1 周目に保持を回復したうえで `child_extra_read` のまま fail した。
P1 は回答の保持についてのみの量である。

## 3. S2（block 0 件の fail）の中身

フックが block を 1 件も出していない run の失敗は、機械的にフック起因ではない。
3 件の内訳:

| 周 | ケース / モード | 失敗 |
|---|---|---|
| 1 | reader-bounds / auto | `resume`（親が worker を resume）、`child_status` |
| 2 | auto-bulk-facts / haiku | `agent_type` / `agent_calls` / `child_reads_once` / `deny_bypass`（親が委譲せず自分で読んだ） |
| 2 | compare-hook-deny-route / auto | `requested_model` / `resolved_model` / `retry_policy` / `child_status` |

いずれもモデル挙動で、`reviews/a-suite-failures-9346d19-2026-09-16.md` の
§2・§3・§4 と同じ系統である。今回新しく出たものはない。

## 4. 事前登録どおりにならなかった点

**isolation は今回測れていない。** `SLOTS` で direct を外したため、
isolation を宣言しているケースは `direct=None` となり、集計側で
`auto-bulk-facts/haiku` と `compare-explicit-multifile/haiku,sonnet` が
毎周 isolation fail になる。isolation は集計時にモード間で計算される検査で、
direct を課金対象から外した時点で成立しない。

- 事前登録項目（P1・P2・S1〜S4）は試行ログと完了後セッション由来なので影響しない。
- S2 も per-run verdict を見ており、そこでは 3 件とも pass なので混入していない。
- 影響は**スイートの `fail` 件数が今回は読めない**という一点である
  （1 周 5 / 2 周 5 / 3 周 3 のうち、毎周 3 件はこの人工物）。

枠を途中で変えると固定 N が崩れるため、3 周とも同じ枠で走らせた。
次にこのプローブを回すなら、isolation 宣言のあるケースを枠から外すか、
direct を含めて費用を積むかを**事前に**決める。

## 5. 判定

§8 の事前基準に照らす。

- **S1 = 0、S4 = 0。** 出荷構成の欠陥として扱う条件には当たらない。
- **P1 = 12/12。** §4 の「12 run / 2 ケース」の限界は「24 run / 8 枠」に広がった。
  一般的な回復率ではない。§4 の選定は結果依存であり、
  P1 は「block が出た条件での修復率」としてのみ読める。
- **block は 12 件**で、判断保留の条件（3 件未満）には当たらない。
- **S3 = 0。** 破棄経路は今回も**未観測**である。発生率は依然として出ていない
  （`sendback-trial-spec-2026-09-15.md` §5 のとおり、`not_resumed` が
  出ていない以上そもそも原因の話にならない）。

登録判断 `reviews/sendback-registration-decision-2026-09-15.md` §7 が
「出荷構成がスイート単位で未測定」として残した穴は、**8 枠 24 run の範囲で埋まった**。
§4 の他の限界（1 マシン・1 CLI ビルド）は N では埋まらず、そのまま残る。

## 6. 費用

| | 実測 | 事前見積もり |
|---|---|---|
| 1 周目 | $1.347 | — |
| 2 周目 | $1.445 | — |
| 3 周目 | $1.274 | — |
| 合計 | **$4.066** | $4.1（上限 $6） |

見積もりとの差は 1% 未満だった。上限には触れていない。
