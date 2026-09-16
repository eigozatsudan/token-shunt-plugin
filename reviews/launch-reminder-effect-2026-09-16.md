# `check-worker-launch` 効果確認の結果（2026-09-16）

事前登録: `reviews/launch-reminder-effect-design-2026-09-16.md`（`7f5fb43`）。
実行環境: CLI 2.1.272、`SENDBACK` 既定 off。
固定コミット — treatment `7f5fb43` / control `1ed1522`。どちらも専用チェックアウト
（`/tmp/ts-treat` / `/tmp/ts-ctrl`）で生成物以外の差分なし、`judge.py --selftest`
を各チェックアウト内で通してから実行。

**結論を先に。配送は確認できた。短縮の減少は、この N では測れなかった。**

## 1. E2（配送）: 確認できた

| 項目 | treatment | control |
|---|---|---|
| E2a フックが payload を返した | **6 / 6** | 0 / 6 |
| E2c 文言が親の文脈に入った | **6 / 6** | 0 / 6 |

`PostToolUse:Agent` の `hook_response` が全 6 run にあり、CLI セッション
（`~/.claude/projects/…/*.jsonl`）に
`attachment: hook_additional_context` として同じ文言が入っていた。
§10.1 が CLI の文字列から読んだ「PostToolUse の `additionalContext` は
配送される」は、実機で成立する。

### 1.1 事前登録からの逸脱（E2b は計器の誤り）

事前登録の E2b は「文言がフック応答**以外**のイベントに現れた run 数」で、
値は **0 / 6** だった。基準 §5-1 はこれが 0 なら止めろと言っている。

**止めなかった。E2b が読んでいたファイルが違うからである。**
評価用トランスクリプトは `--output-format stream-json` の標準出力で、
attachment を含まない。配送は CLI セッションファイルにしか現れない。
S3 が記録の `transcript_path` ではなく評価用トランスクリプトを見ていた
（`sendback-fixed-n-probe-design` §7.2）のと同じ種類の誤りで、
0 は「配送されなかった」ではなく「そのファイルでは測れない」である。

逸脱として明記する。**E2c は事前登録に無い項目**であり、
実行中に足した。`retention_probe.py` は実験中は変更していない。

## 2. E1（短縮）: 基準率が低く、測れない

run 単位。分母は測定可能だった run（ワーカーの実在絶対パス付き
`confirmed:` 行があった run）。

| 腕 | 短縮 / 測定可能 |
|---|---|
| control (`1ed1522`) | **2 / 6** |
| treatment (`7f5fb43`) | **1 / 6** |

事前登録 §5-3 に従い、**control が 3/6 以下なので「この N では基準率が低すぎて
測れない」**と記録する。効果ありともなしとも書かない。
2/6 対 1/6 の Fisher 両側 p = 1.0。

枠ごとに見ると偏りがはっきりしている。

| 枠 | control | treatment |
|---|---|---|
| `compare-explicit-multifile/haiku` | 0 / 2 | 0 / 2 |
| `compare-explicit-multifile/auto` | 0 / 2 | 0 / 2 |
| `auto-explicit-multifile/haiku` | **2 / 2** | **1 / 2** |

- **§1 の失敗（`compare-explicit-multifile/haiku` で親が basename に短縮）は
  両腕とも 1 度も再現しなかった**（0/4）。§1 の観測は 1 run であり、
  再現率の推定にはなっていなかった。
- 短縮はすべて `auto-explicit-multifile/haiku`（スイート B、スキル名指しの無い
  委譲）に出た。control 2 run は 6 行・3 行を落とし、treatment の 1 run は
  3 行を落とした。
- **treatment のその 1 件は、文言が配送されていても起きた。** 予防は十分条件では
  ない。

## 3. E3（合否）・E4（費用）

verdict は両腕とも 3 枠すべて `isolation: direct=None` で fail する。
枠に direct を入れていないので isolation は測れない
（`sendback-fixed-n-probe-2026-09-16.md` §4 と同じ既知の制約。今回も
事前に承知の上で除いた）。isolation を除けば
`compare-explicit-multifile` の 2 枠は両腕とも全 run pass、
`auto-explicit-multifile/haiku` は control 2 run・treatment 1 run が
`gold_confirmed` で fail。

費用は 4 起動で **$1.360**（treatment $0.709 / control $0.651）。上限 $5 の 27%。

## 4. 延長しなかった理由

事前登録 §5-5 は「方向が一致し p > 0.05 なら 1 周だけ延長してよい」と
しているが、§5-3 が先に成立している。加えて 1 周足しても届かない。
基準率 1/3 で完全分離を仮定しても、9 対 9 で Fisher 両側 p = 0.21、
18 対 18 でようやく p = 0.019。**この効果をこの基準率で検出するには
1 腕あたり 18 run、合計で約 $8 かかる。** 今回の $1.4 の延長では判定できない。

## 5. 計器の欠陥（記録のみ、実験中は直さない）

`retention_probe.score_dir` は `_probe_iso` / `_probe_load` の
トランスクリプトも run として数える（`runs: 5`、`undetermined: 2`）。
枠ごとの集計には混ざらないので E1 には影響しないが、`runs` と
`undetermined` の総数はそのぶん多い。上の表は枠ごとの値から数えている。

## 6. 残ること

- `check-worker-launch` は**配送されることが確認できた予防経路**である。
  短縮を減らすかどうかは未判定。
- 判定したいなら 1 腕 18 run（約 $8）。それを払うかは別の判断。
- 短縮が出るのは `auto-explicit-multifile/haiku` に集中している。次に測るなら
  枠をそこに寄せたほうが同じ費用で基準率を稼げる（1 腕 6 run 全部をこの枠に
  すれば、今回と同じ $1.4 で 6 対 6 の比較になる）。
