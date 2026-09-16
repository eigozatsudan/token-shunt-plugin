# judge が「試みた」と「読み切った」を区別できなかった（2026-09-16）

`reviews/scope-control-2026-09-16.md` §5 で見つかった評価側の欠陥。**課金なし。**

## 1. 何が起きていたか

`routing_checks.reader_contract_denial` は、Read 契約のフックが出す拒否文言を
列挙して照合している。**宣言パス外の拒否だけが列に無かった。**

その結果、`check_reader_reads` は
`reads = [c for c in attempts if not reader_contract_denial(tr, c)]` で
拒否された Read を除くつもりが、**スコープ拒否された Read を「実行された Read」として数え**、
`child_extra_read` で run を落としていた。

**フックが仕事をした run が、フックが無い run と同じ理由で fail していた。**
実測では treatment 腕 12 run のうち 3 run がこれである。

## 2. なぜ問題なのか

- **評価がフックの効果を表現できない。** 「範囲外に手を伸ばしたが止められた」は
  成功であって失敗ではない。verdict でそれが言えないので、
  `scope-oneArm` §5 と `scope-control` §5 では**合否を比較対象から外すしかなかった。**
- 効果を測る手段が実機 run の直接採点だけになり、**測定単価が上がっていた。**

## 3. 直したこと

拒否文言の列に 1 本足した:

```
Read only the paths this invocation was given: <paths>. This path came from
another invocation; report partial and let the caller ask for it in a new one.
```

**文言は `plugin/hooks/reader_scope.scope_reason` の実物から取った。**
他のフックの拒否と同じく `re.fullmatch` で、前後に何か付いていれば一致しない
（`token-shunt:` 接頭辞と厳密一致、結果の識別・順序の条件も従来どおり）。

**試みが消えるわけではない。** `reader_attempt_metrics` の `blocked_attempts` に
理由つきで残り、`judge.py` の `metrics.reader_attempts` に出る。
**これは今後のスコープ測定の分子そのものなので、テストで固定した。**

## 4. テスト（5 件、`test_live_rerun_regressions.py`）

- スコープ拒否が契約拒否として認識される
- 拒否された範囲外パスは `child_extra_read` にならない
- **拒否された試みは `blocked_attempts` に理由つきで残る**
- **内容を返した範囲外 Read は依然として fail**（control 腕の実測がこれ。緩めていない）
- 途中で切れた似た文言は一致しない

## 5. 適用範囲の注意

- **走行中の 50 run（`312beef` 土台）はこの修正より前**である。
  あの実験の verdict は従来どおり「試み」で落ちる。
  もっとも事前登録 §5-2 で**合否は比較しないと決めてある**ので、結論には影響しない。
- 既走の treatment 12 run は run ディレクトリを削除済みで**再判定できない**。
  影響（3 run の fail 理由）は `scope-oneArm` §5 に記録が残っている。

## 6. 確認

`unittest discover -s evals` 279 OK、`-s evals/compare` **532 OK**（+7）、
`judge.py --selftest` 全項目 pass、`evals/run.sh` 240 pass / 0 fail。
`token-shunt.zip` は `run.sh` が触るので戻した（`plugin/` は無変更）。
