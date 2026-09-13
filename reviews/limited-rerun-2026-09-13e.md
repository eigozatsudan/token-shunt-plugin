# 実機再実行3回目（指示修正後）

対象: `run.4P4u89Wp`（2026-09-13 22:23 完了）。ケース選択は
[limited-rerun-2026-09-13.md](limited-rerun-2026-09-13.md) と同じ10ケース19実行。
コードは 81de6d3 のまま（作業ツリーは pyc のみ）。

## 集計

実行単位で **9 pass / 10 fail**（前回 run.5iqYfCeg は 10 pass / 9 fail）。
`run.sh` の `done: pass=12` には実行以外に probe-load / probe-isolation /
plugin-validate の3件が含まれる（`evals/compare/run.sh:411,451,454`）。
前回レポートで 13 pass としたのはこの3件を実行数に含めた誤りで、
[c-fixes](limited-rerun-2026-09-13c-fixes.md) の 10 pass / 9 fail が正しい。

オフライン事前検証: `evals/run.sh` 110 pass / 0 fail、compare 単体 160 tests 全通過、
judge selftest 16件成功。

## 解消した項目

- `compare-explicit-multifile/haiku`、`auto-bulk-facts/haiku` の飛び読みが消えた。
  next_line / inclusive offset / 拒否時カーソル固定の明文化が効いている。
- `auto-bulk-facts` は direct / haiku / sonnet の3モードとも通過。
- `compare-edit-dense-lines/auto` は accuracy が通過（前回は取りこぼし）。

## 残る逸脱（子の読み取り）

auto モードのみで再発。haiku 単独・sonnet 単独では出ていない。

| 実行 | 判定 |
|---|---|
| retry-policy/auto | 101行から継続すべきところ (300, 399) |
| auto-bulk-facts/auto | 351→(400,518)、拒否後の半減 84 に対し 119、(515,524) が重複 |

## 新規に失敗した項目

### 単一行ファイルの契約デッドロック（auto-one-line sonnet / auto）

`oneline.json` は 68KB の単一行。`limit=1` でも Read が拒否されるため、
新契約「limit=1 拒否で partial 停止」に従うと子は本文を一切取得できない。

- sonnet: limit=1 拒否 → Grep で値を取得。accuracy は通過するが
  `child_reads_once` が「successful carrier Read なし」で fail。
- auto: limit=1 拒否を2回。accuracy も fail（sha 値を出せず）。

契約・ケース期待値・子のツール権限のいずれかを変えないと同時に満たせない。
`compare-edit-dense-lines` の4万行問題と同じ構造で、
[c-fixes の「残る制約」](limited-rerun-2026-09-13c-fixes.md) の範囲。

### 判定器の偽陽性: verification_execution 7件

`writer-verification-levels/auto` の親は7本の検証コマンドを
1回の Bash（`cd` + 改行区切り + `echo` ラベル）で実行し、JSON 証跡も出している。
しかし `flow_checks.py:151` が `$` を含むコマンド文字列をバッチ丸ごと証拠から除外するため、
`echo "exit: $?"` 一行の存在だけで7件すべてが「検証コマンドなし」と判定された。
親の動作は契約どおり。判定器側で `echo` 引数内の `$` を許容するか、
スキルで `$?` を書かないよう指示するかの選択。

### 親の契約不遵守 2件

- `reader-batch-ambiguous/auto`: Agent 2回とも `model` を省略（requested_model None）。
  スキルは「auto を渡さず haiku/sonnet に解決して渡す」と明記しているが、
  解決結果を渡さず省略した。batch_evidence も fail。
- `compare-explicit-multifile/sonnet`: 親が子の回答を
  「**Worker's answer:**」として丸ごと転記し、自分の
  `confirmed: <絶対パス> — <事実>` 箇条書きを作らなかった → gold_confirmed fail。
  内容自体は正答。

## 環境由来の失敗 1件

`compare-edit-dense-lines/auto`: `foreign_hooks: SessionStart:compact`。
評価サブプロセスがユーザーのグローバルプラグイン
（`~/.claude/plugins/cache/claude-plugins-official/` の security-guidance、superpowers）を
継承しており、実行が長くコンパクトが起きた時だけ SessionStart フックが発火する。
`probe-isolation` はコンパクトしないので検出できない。
token-shunt の欠陥ではなく評価ハーネスの隔離漏れ。
