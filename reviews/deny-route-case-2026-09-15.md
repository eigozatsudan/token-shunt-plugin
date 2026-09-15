# compare-hook-deny-route が落ちる理由と、両側の直し方

日付: 2026-09-15。対象: `compare-hook-deny-route`（suite A）。実機再現 2/2（$0.256）。

## 症状

判定は `deny_route` で落ちる。理由文は「target Read lacks matching
token-shunt deny and failed result before reader Agent」。親の振る舞い自体
は正しい。委譲先も本文を持ち出していない。落ちているのは証拠の形だけ。

転写に残るのは次の 3 手である。

1. 親が `wc -c <fixture>` を実行する（65,669 B）
2. 親が Read を 1 度も出さずに `token-shunt:bulk-reader` を起動する
3. 子が要約を返し、親が答える

`deny_route` は「Read が出て、token-shunt の deny 文言つきで失敗し、その
後に reader Agent が来る」ことを求める。1 と 2 の経路には deny が無い。
無いものを要求しているので、正しい実行が落ちる。

## 原因

ケースは metadata-first ルール（SKILL.md §1）より前に書かれた。当時の親
は素直に Read を撃ち、`check-file-size` の deny を受けてから委譲した。
現在の SKILL.md は最初の Read の前に `stat` / `wc -c` でサイズを判断し、
16384 B を超えていれば Read を出さずに委譲しろと書く。つまり製品が改善
した結果、ケースの期待する往復が消えた。ケースと製品ルールの衝突であり、
フックの欠陥でも親の逸脱でもない。

## 直した 2 点

**(2) 固定物を、deny が実際に起きる大きさに戻す。** `evals/compare/run.sh`
が `gen/deny_lines.py` を生成する。380 行・13,982 B — 350 行の全文 Read
閾値は超えるが 16,384 B の小タスク予算には収まる。この大きさなら
metadata-first は委譲を指示しない（予算内なので）。親は正当に全文 Read を
試み、行数閾値だけが deny する。これが本ケースが測りたかった deny →
委譲の往復である。生成側に「>350 行かつ <16384 B」の自己検査を置いた。
崩れたら生成時に `SystemExit` する。金額を払ってから気づく形にはしない。

**(1) 判定器に、もう一方の適合経路を認めさせる。** `judge.py` の
`deny_route` は、deny が見つからない場合に限って次を受け入れる。

- reader Agent より前に、親自身が `wc -c` / `stat` でその固定物のサイズを
  測っている（`measures_path()`）
- かつ、その固定物への **成功した** Read が親に 1 件も無い

本文が親に入っていないことは引き続き必須にした。deny を省いたことに対す
る免除であって、本文を持ち込んだことへの免除ではない。

`measures_path()` は `grep_bounds.metadata_paths` を呼ばない。同じ狭い読み
（シェルが展開しうる文字を含まない `wc -c` / `stat` のオペランドだけ）を
判定器側に書き直してある。製品のパーサで製品を採点すると、パーサが緩んだ
ときに判定も一緒に緩む。

## 残したもの

- 元の deny 経路の判定は消していない。deny があればそちらで通る。
- `compare-hook-deny-route` の `note` に、固定物が予算未満なのは意図で
  あることと、その理由を書いた。次に誰かが「小さすぎる」と見て大きくする
  のを防ぐため。
- 新しい証拠テストは `evals/compare/test_deny_route_evidence.py`（7 件追加）。

## 限界

実機での再走はしていない（比較評価の再走は今回の作業範囲外）。固定物の
入れ替えが実際に deny を発生させることは、閾値の算術と `check-file-size`
のテストからの推論であって、転写での確認ではない。次に suite A を回した
ときに確認する。
