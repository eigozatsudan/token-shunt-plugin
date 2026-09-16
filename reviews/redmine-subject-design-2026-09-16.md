# Redmine を被験体にする（2026-09-16・事前登録）

`https://github.com/redmine/redmine.git` を実コーパスとして効果測定に使う設計。
**本記録の時点では課金していない。** §2 は実施済み（無料）、§5 は未認可。

clone: `87fa3fc6f9d2ebee1fbdc504ca55f2d04d3fcb9f`（shallow, 2306 files）。

## 1. なぜ実コーパスが要るのか

これまでの測定は合成 fixture で行ってきた。読み対象の実質はこれ一つ:

| | bytes | 推定トークン |
|---|---|---|
| `fixtures/rails/app/models/user.rb`（合成） | 22,546 | 約 6.4k |
| Redmine `app/models/issue.rb` | 72,350 | **約 20.7k** |
| Redmine `app/helpers/application_helper.rb` | 70,137 | 約 20.0k |

**token-shunt の効能は「親に本文を入れない」ことそのものである。**
合成 fixture では親が飲み込む量が 6.4k しかなく、**効果が小さいほうに偏る。**
Redmine の現実的な読み対象は 20k 前後で、Read の 25,000 トークン上限の**すぐ下**
——1 回の Read で丸ごと親に入ってしまう最悪の帯——に乗っている。

（推定は 3.5 bytes/token による概算であって実測ではない。実測値は §5 の
`parent_input_tokens` で取る。）

## 2. すでにやった検証（無料・結果）

### 2.1 抽出器が実ファイル名で壊れないか

Redmine の全 2306 パスを `run.sh` が書く形（`<絶対パス> (N bytes)`）に整形して
`reader_scope` の切り出しに通した。**往復しなかったパスは 0 件。**

### 2.2 フック実行ファイルの端から端まで

`plugin/hooks/check-reader-contract` を実プロセスとして起動し、宣言集合を
`app/models/issue.rb` / `issue_status.rb` / `lib/redmine/access_control.rb` とした
launch prompt を実 transcript に置いて:

- 宣言内の 2 本 → 通過
- `app/models/project.rb`（宣言外） → **拒否**、文言に宣言 3 本が列挙される
- `SCOPE_TRIAL_LOG`（`d1eb261` で入れた計装）に `scope` 1 行 + `refused` 1 行

**1(b) の計装が実コーパスで意図どおり動くことを確認した。**

### 2.3 Redmine が足さないもの

`app/` + `lib/` 1016 ファイルのうち **Read 上限を超えるのは 1 本だけ**で、
それは vendored な `jquery-3.7.1-ui-1.13.3.js` である。
**切り詰め→半分再試行の経路は Redmine では自然に踏めない。**
`fixtures/gen/bounds/` の合成 fixture は**残す**。

## 3. ライセンス上の制約（設計を縛る）

Redmine は **GPL-2.0**（`LICENSE.txt`）。token-shunt には LICENSE ファイルが無い。

**したがって Redmine のソースを `evals/compare/fixtures/` に取り込まない。**
取り込めば `token-shunt.zip` に GPL コードが同梱され、配布条件の判断が要る。
これは私が勝手に決めてよいことではない。

**外部の固定 clone を環境変数で指す。** 無ければ suite ごと skip。
`gen_fixtures` は `$SOURCE_FIX` の外を `cp -a` しない現在の形を保ち、
Redmine 用の複写だけを別関数に分ける。

## 4. 測る量（ここが今までと違う）

これまでのスコープ測定の分子は**二値**（再読が起きたか）で、
発生率が低いため 40 run/腕でも p = 0.167 までしか行かなかった
（`reviews/scope-control-2026-09-16.md`）。

Redmine で測るのは二値ではない:

- **主要指標: `parent_input_tokens`**（`judge.py` が既に取っている）。
  off 腕は本文 20k を親に入れ、auto 腕は要約しか入れない。
  **run ごとにほぼ決定的で、分散が小さい。**
- 副次: run あたりコスト、`metrics.reader_attempts`、verdict。

**N は分散を見てから決める**（§5-2）。二値指標と同じ N は要らないはずだが、
「要らないはず」は予測であって結果ではない。

## 5. 課金する部分（未認可・実施しない）

### 5-1 事前に固定すること

1. case: `redmine-visible-scope`（suite X）。
   task は「`Issue#visible?` の可視判定が何に依存するか報告せよ」。
   fixtures は §3 の外部 clone を `87fa3fc` に固定。
2. modes: `auto` と `off` を**交互**に。
3. 主要指標・停止規則・N を**走らせる前に**別記録で確定する。
4. 費用の見積り: 現行 case は 1 run 約 $0.20–0.25（実測、`/tmp/ts-t` の直近 2 run）。
   Redmine の off 腕は親が約 3 倍の入力を飲むので **1 run $0.3–0.5 と見込む。**
   **見込みであって実測ではない。** 2 run の校正で確定させる（stage 0.5 と同じ手順）。

### 5-2 いま走らせない理由

**50 run の交互実験（`312beef` 土台）が $30 の枠を使っている最中**である
（本記録の時点で 24/50）。枠を二重に使わない。

また `reviews/` の先例どおり、**N と停止規則を書いてから買う。**

## 6. 確認

§2 の検証はすべて無料。製品コードは本記録では変更していない。
