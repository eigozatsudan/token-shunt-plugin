# 事前登録: 差し戻しをアーカイブのケースに当てる（2026-09-20、未実行）

**まだ 1 セントも使っていない。走る前に承認を得る。**

## 1. 問い

`reviews/retention-after-reminder-2026-09-20.md` §1 で、リマインダ（`7f5fb43`）が
届いた 213 ターンのうち **108 で親が worker の `confirmed:` 行を落とした**
（うち 98 は全滅）ことが分かった。**これは差し戻しを外した基準線である**
（`run.sh:396` の `SENDBACK:-off`、登録判断 §3.4 の意図された設計）。

差し戻し自体の実効性は測られている —— `sendback-remeasure-2026-09-15` §2.3 で
**6/6 で欠けていた行が逐語で戻った。** ただしそれは**別のコーパス・別の世代**である。

> **問い: アーカイブで違反が多いケースに、現行コードで差し戻しを載せたとき、
> block を受けた親は行を戻すか。**

**再生では埋まらない。** 差し戻し後の親の応答は transcript に存在しない。

## 2. 主要指標は同一実行内の前後である（世代差を避けるため）

**アーカイブとの差は取らない。** 理由:

- アーカイブの対照（`django-subthreshold-bare` 90 ターン、違反 50）は
  **2026-09-18 14:24** に走った。
- **`77ef7b1`（reader の返答に legal move を足す）は 2026-09-18 19:38** で、
  **対照より後**である。ほかに Lock B 実装 3 本と coverage フック 3 本が入った。
- Lock B は既定 0 で不活性（`0c7a721`）、coverage フックは記録専用で deny しない。
  **しかし `77ef7b1` は reader の返答形に触る。**

**単腕で走らせてアーカイブと引き算すると、差し戻しの効果と `77ef7b1` の効果が
混ざる。** よって:

| | 内容 |
|---|---|
| **主要** | block を送ったターンのうち、**再開後に欠けていた行が逐語で戻ったターンの割合**。`sendback_retention.check_line_retention` の `dropped` が block 時に非空で、再開後に空になること |
| 副次 1 | `再ブロック抑止`（`stop_hook_active`）が block ごとに 1 回出ること |
| 副次 2 | **上限到達 0 件**（CLI 既定 8 回）。1 回の差し戻しで足りること |
| 副次 3 | `relapse`（戻した後に短い答えで終わる）の件数 |

**すべて 1 実行の内部で完結する。** アーカイブの 50/90 は
**「発火が見込める」根拠としてだけ使い、成果の比較対象にしない。**

## 3. 腕

**単腕。** `SENDBACK=on` のみ。`off` 腕は買わない ——
§2 のとおり比較しないので、対照に払う理由が無い。

```bash
cd ~/wt/ts-sendback            # 専用 worktree。/tmp に置かない
SENDBACK=on \
SUITE=X SLOTS=django-subthreshold-bare/auto \
DJANGO_ROOT=~/src/django \
bash evals/compare/drive.sh --pairs 5 \
    --cases django-subthreshold-bare \
    --cap 2.50 --reserve 0.30 --max-barren 3
```

- **`--runs` を渡さない**（`drive.sh` は `run.sh` へ転送せず、cap が空の
  ディレクトリを見る）。
- **`direct` は回さない。** direct はプラグインを読み込まないので Stop フックが
  載らない。
- **専用 worktree を作る。** cap は run ディレクトリ単位の累積なので、
  既存の worktree を使うと他のブロックの spend と混ざる。

## 4. n・予算・停止規則

実測（`reviews/data/subthreshold-routing-2026-09-18.csv`、auto 腕 n=23）:
中央値 **$0.1708**、平均 **$0.1779**、**最大 $0.2989**。

| | 値 | 根拠 |
|---|---|---|
| n | **10 run** | アーカイブの違反率 50/90 = 55.6% なら期待 block **5.6 件** |
| 期待費用 | **≈ $1.78** | 平均 × 10 |
| `--cap` | **$2.50** | 最大値で 10 run 回すと $2.99 になるので、**cap が先に効く**。それでよい |
| `--reserve` | **$0.30** | **最大値 $0.2989 から取る。平均から取らない** |
| `--max-barren` | 3 | 課金だけして完走しない run が 3 本続いたら止める |

**cap で n=10 に届かなかったら、届いた本数でそのまま書く。**
後から n を揃えたふりをしない。

**残予算約 $8.0 に対して $2.50。** 走る前にこの cap を超える追加は出さない。

## 5. 外したとき（先に書く）

- **block が 0 件だった場合。** 「差し戻しが効かない」ではない。
  発火条件（`line_retention` 違反）が起きなかっただけである。
  **アーカイブの 55.6% は別世代の別ブロックの率であり、保証ではない。**
  この場合は「10 run で発火 0」とだけ書き、率を主張しない。
- **戻ったのが一部だった場合。** 割合をそのまま書く。
  **6/6 という既存の数字に寄せた丸め方をしない。**
- **上限到達が出た場合。** 1 回の差し戻しで足りないという所見であり、
  `sendback-remeasure` §2.4 の「上限到達 0 件」を覆す。隠さず書く。

## 6. 盲検

- **ブロック中に driver の FAIL 行を読まない。**
- **主要指標は全 run が出揃ってから集計する。**
- 例外は機構の欠陥だけ: **10 run で Stop フックの起動記録が 1 件も無い**場合、
  `TOKEN_SHUNT_SENDBACK` が届いているかだけを確認する（判定結果は見ない）。

## 7. 消える前に退避する

run ディレクトリは消える。

1. **per-pair 行** → `reviews/data/sendback-archive-cases-2026-09-20.csv`
2. **transcript** → `~/measurements/sendback-2026-09-20/` に **sha256 つきで**。
   リポジトリに入れない。
3. `summary.json` / `manifest.json` も run ごとに残す。
4. **`<transcript>.sendback.jsonl`**（§8.1 で追加）。
   **これが腕の記録である** —— 無い run は `SENDBACK` が届いていない。
   フック 1 回につき 1 レコードなので、block 0 件の run でも
   「判定に至ったが block しなかった」と「そもそも呼ばれていない」を分けられる。

## 8. 走る前に（$0、全部やってから 1 run 目）

1. `~/wt/ts-sendback` を作る（`/tmp` に置かない）。
2. そこで `python3 evals/compare/judge.py --selftest` を通す。
3. `evals/compare` と `evals` の unittest を通す。
4. `DJANGO_ROOT` が 5.2.1 / `bc833e8` を指していることを確認する。
5. **`SENDBACK=on` が届くことを、1 run 目の前に $0 で確認する** ——
   `run.sh:396` は `${SENDBACK:-off}` なので、渡し忘れると
   **「完走した基準線の測定」**になり、block 0 件と区別がつかない。

## 8.1 事前チェックの結果（2026-09-20、$0、実施済み）

**5 項目すべて通った。まだ 1 セントも使っていない。**

| # | 項目 | 結果 |
|---|---|---|
| 1 | `~/wt/ts-sendback` | 作成。**detached HEAD（`98e2dbb`）** —— 下記の逸脱を参照 |
| 2 | `judge.py --selftest` | `selftest: all checks passed` |
| 3 | unittest 2 スイート | `evals/compare` 815 OK / `evals` 398 OK（skipped 3） |
| 4 | `DJANGO_ROOT` | `~/src/django` が `bc833e8`、`git describe --tags` = `5.2.1` |
| 5 | `SENDBACK=on` の到達 | 2 段に分けて確認、下記 |

**逸脱（再開前に記録する）。** §3 は `~/wt/ts-sendback` を作るとだけ書いたが、
`git worktree add ~/wt/ts-sendback main` は
`fatal: 'main' is already used by worktree at '/home/dev/projects/skills/token-shunt'`
で失敗した。**`--detach` で `98e2dbb` に固定した。**
このブロックは worktree 内で commit しないので、腕の同一性（どの commit を
測ったか）は detached の方がむしろ明示的である。**測定内容は変わらない。**

**到達確認（項目 5）。** `run.sh:396` の既定 off は、渡し忘れが
「完走した基準線」に化ける経路なので、**実機を使わずに 2 段で確かめた。**

- **(a) `drive.sh` → runner。** `TS_RUNNER` を差し替えた double で
  `SENDBACK=on bash evals/compare/drive.sh` を回すと、runner 側で
  `SENDBACK=on` が 2 回とも見えた。`drive.sh` は `SENDBACK` に触れず、
  env も洗っていない（`grep` で確認）。
- **(b) `run.sh` → `claude` プロセス。** `run.sh` を source し、
  `claude` を環境変数を印字するだけの double に置き換えて
  `run_claude` を 2 回呼んだ:

  | 渡したもの | `TOKEN_SHUNT_SENDBACK` | `SENDBACK_TRIAL_LOG` |
  |---|---|---|
  | `SENDBACK=on` | `on` | `<transcript>.sendback.jsonl` |
  | `SENDBACK=off` | `off` | 未設定 |

**副産物: 事後に腕を証明できる。** `SENDBACK=on` のときだけ
`run.sh:409` が transcript の隣に `*.sendback.jsonl` を置く。
**このファイルの有無が、run ごとの腕の記録である** ——
Lock B の `session_budget_bytes` 列と同じ役割を果たす。
block が 0 件だったときに「渡し忘れ」と区別できる。§7 の退避対象に加える。

## 9. これが答えないこと

1. **n=10、1 ケース、単腕である。** 率の推定ではない。
2. **アーカイブとの比較をしない**（§2）。世代が違う。
3. **worker 側の欠落（`child_items`）は対象外。** 別機構（SubagentStop）が扱い、
   保存コーパス 563 起動で既に分類されている（`sendback-worker-side-2026-09-15` §1）。
4. **親コンテキストの汚染量を測らない。** 本ブロックが見るのは保持だけである。
