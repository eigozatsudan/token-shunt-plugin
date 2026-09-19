# Lock B 測定ブロックの実行手順（$0 で書いた、まだ実行していない）

事前登録: `docs/superpowers/specs/2026-09-19-cumulative-intake-design.md` §5。
**本書は手順だけである。判定基準・停止規則・外したときの書き方は spec が持ち、
ここでは複製しない**（二重管理で食い違うのが一番まずい）。

**この文書を書いた時点で予算は足りていない。** §5.7 の通り枠 $12〜13 に対し
残り約 $9.7。**走らせるのは予算が戻ってからで、その前に §0 を通す。**

## 0. 走る前に（$0、全部やってから 1 run 目を出す）

1. **専用チェックアウトを固定する。** 測定に使う worktree を 2 本、
   `~/wt/ts-intake-control` と `~/wt/ts-intake-treated`。**`/tmp` に置かない。**
   **両腕とも同じ commit** —— Lock B は既定無効なので、
   **腕の差はコードではなく環境変数 1 つだけである**（spec §5.6、§7.7）。
2. **各 worktree で `python3 evals/compare/judge.py --selftest` を通す。**
   通らないチェックアウトに 1 セントも入れない。
3. **`evals/compare` と `evals` の unittest を両腕で通す。**
4. **fixture の前提を確認する（実行不要・机上で決まる）。**
   後続 3 ファイルは 9,767 / 11,613 / 7,966 B、239 / 316 / 211 行。
   - turn 2+3 の累積 21,380 B > 16,384 → **treated 腕は turn 3 で掛かる。**
   - 各ファイルは 350 行・65,536 B 未満 → **既存のサイズゲートには掛からない。**
   **結果を見て決める前提を 1 つも残さない**（spec §5.6）。
5. **`DJANGO_ROOT` を 5.2.1 / `bc833e8` に向ける。**
   `external_ready` が見るのはこの環境変数で、無ければケースは planned に
   入らず、**run は「完走した空の測定」になる。**

## 1. 腕の作り方

| 腕 | 渡すもの |
|---|---|
| control | 何も渡さない（`SESSION_BUDGET_BYTES` 未設定 = Lock B 無効） |
| treated | `SESSION_BUDGET_BYTES=16384` |

`run.sh` はこれを `TOKEN_SHUNT_SESSION_BUDGET_BYTES` としてフックへ渡し、
**manifest と `summary.json` に `session_budget_bytes` として記録する**（§7.7）。
**腕の証拠はこの数字である。** 発火率は 1/14 なので、
**発火しなかった treated run は記録が無ければ control run と区別できない。**

数字でない値を渡すと run は止まる（打ち間違いが「control 腕として完走」
になるのを防ぐため）。

## 2. 1 run の出し方

```bash
cd ~/wt/ts-intake-treated            # control 腕は cd 先を替えるだけ
SESSION_BUDGET_BYTES=16384 \
SUITE=X SLOTS=django-multiturn-context/auto \
DJANGO_ROOT=~/src/django \
bash evals/compare/drive.sh --pairs 5 \
    --cases django-multiturn-context \
    --cap 6.00 --reserve 0.55 --max-barren 3
```

- **`--runs` を渡さない。** `drive.sh` は `--runs` を `spend.py` と
  完走数の数え先にだけ使い、**`run.sh` には転送しない**（`RUNNER=(bash run.sh)`
  を引数なしで呼ぶ）。run.sh は常に自分の `evals/compare/tmp/runs` へ書くので、
  **`--runs` を渡すと cap が空のディレクトリを見て、いくら使っても 0 と答える。**
  腕ごとの分離は worktree が既にしている（腕ごとに別の `tmp/runs`）。
- **`direct` は回さない。** direct モードはプラグインを読み込まないので
  Lock B の影響を受けず、§5.2 の比較対象（direct の最小 25,901 B）は
  アーカイブ済みの実測から取る。**同じ数字を買い直さない。**
- **1 回の `drive.sh` は 5 run で切る。** 5 本ずつ腕を交互に出す
  —— control 5 → treated 5 → control 5 → … と**1 run 目から交互**にする
  （cap-overflow は最初の 20 run が 10/10 で、時刻と腕が相関した）。

## 3. 枠と停止規則

実測（`reviews/data/multiturn-context-2026-09-18-turns.csv` の 5 ターン合計）:

| 腕 | 中央値 | 平均 | 最大 |
|---|---|---|---|
| direct | $0.2611 | $0.2554 | $0.2917 |
| auto | $0.3328 | **$0.3724** | **$0.5014** |

- 1 腕 14 本 ≈ **$5.21**、両腕で **≈ $10.43**。
- **`--reserve 0.55` は最大値 $0.5014 から取る。平均から取らない**
  ——安い方に寄せた reserve が $30 の枠を $36.55 にした。
- **腕ごとに `--cap 6.00`。** `drive.sh` が `spend.py` に見せるのは
  自分の run ディレクトリ 1 つだけなので、**両腕合計の cap は存在しない。**
  合計 $12 は「腕ごとの cap 2 本」で作る。
  **片腕が cap で止まったら、もう片腕もそこで止める** —— 腕ごとに n が
  違う測定を、後から揃ったふりをして書かない。
- `--max-barren 3`: 課金だけして完走しない run が 3 本続いたら止める。

## 4. 盲検

- **ブロック中に driver の FAIL 行を読まない。** cap-overflow の盲検は
  そこで失われた（§7.2.2）。`drive.sh` の stderr は流し見しない。
- **腕ごとの結果を途中で比べない。** 比較は全 run が出揃ってから。
- 例外は**機構の欠陥**だけ: treated 腕で **deny が 1 度も記録されない**まま
  10 run を超えたら、**発火条件が起きていないのか、機構が動いていないのか**を
  `TOKEN_SHUNT_HOOK_LOG` の有無だけで確認する（判定結果は見ない）。

## 5. 消える前に退避するもの

run ディレクトリは消える。**消える前に出す。**

1. **per-pair 行** → `reviews/data/cumulative-intake-<date>.csv`
   （`pairs.py`。88 対を 1 度失っている）。
2. **per-turn 行**（`parent_turn_reads.py`、`judge.py --turns`）→ 同じ場所。
   **`session_budget_bytes` を列として持たせる** —— 腕が行に乗っていない
   CSV は、後から腕を言えない。
3. **transcript** → `~/measurements/` に **sha256 つきで**。リポジトリに入れない。
   run ディレクトリ自体は各 worktree の `evals/compare/tmp/runs/` にあるので、
   **worktree を消す前に `~/measurements/` へ出す。**
4. `summary.json` / `manifest.json` も run ごとに残す（腕の記録がここにある）。

## 6. 主要・副次・外したときの書き方

**spec §5.2 / §5.3 / §5.8 に書いてある。ここでは繰り返さない。**
1 点だけ運用上の注意: **発火 0 回は「機構が効かない」ではない。**
率 1/14 なら n=14 で 0 回は普通に起こる（§5.8）。
**cap-overflow の `cap_reached` 0/39 と混同しない** ——
あちらは条件が 14 回成立していた。

## 7. この手順が答えていないこと

- **1 度も実行していない。** 本書は机上である。
- **昇格（既定を 16,384 にするか）はこのブロックの結果とセットで決める。**
  `auto-routing-boundary-16k-{minus,equal}` の expect 契約の扱いも同時
  （spec §7.6）。**先に契約だけ動かさない。**
- **n=14 でも率 1/14 は解像できない**（§5.1）。本ブロックは有意性を主張しない。
