# 2026-09-14 実機レビューの判定器修正

対象: [実機レビュー](live-rerun-2026-09-14.md)の「次の一手」1〜3。

## 変更

- 委譲時の隔離許可リストに `PostToolUse:Read` / `PostToolUseFailure:Read` を追加。
  direct 時や非 token-shunt の出力は引き続き拒否する。Post フックの応答は
  PreToolUse deny の証拠にはしない。設計 §13 の許可リストも更新した。
- reader の既知のフック deny は、対応する失敗 tool_result の呼出 ID・子起動 ID・
  時系列を検証してから読取実行と分離する。遮断された飛び越し・誤半減・指定外
  Read はカーソルを動かさず、成功した読取の根拠にもならない。
- 予算は既存フックどおり、deny を含む最初の6試行。6試行後に遮断された要求は
  実行済みと数えず、その後に通過した Read は失敗とする。フック自体は変更していない。
- `metrics.reader_attempts` に試行数、消費予算、遮断した呼出 ID と理由を保存する。
  遮断成功と、モデルが試行時から契約を守ったことは区別する。
- 単一行 unreadable の例外では空の `confirmed:`、`confirmed: none`、観測された
  `confirmed: none — unable to retrieve payload_sha value.` 型を許容する。
  任意の説明や後続行の事実主張は許容しない。親子両方の終了報告とネイティブ
  `limit=1` 拒否証拠は引き続き必須。

## 保存証跡の再判定

元アーカイブ: `~/token-shunt-evidence/live-rerun-2026-09-14/run.mnVnW1FU.tar.gz`。
アーカイブ内の transcript/spec を直接読み、ディスク上の fixture 33ファイルが
アーカイブと SHA-256 で一致することを確認して、75実行を再判定した。
元の transcript/spec/verdict は書き換えていない。

| judge の結果 | 修正前 | 修正後 |
|---|---:|---:|
| pass | 15 | 48 |
| fail | 60 | 27 |

修正前 pass 15 は75個の保存済み judge verdict の件数。実機ログの pass 18 は
プローブ等を含むランナーカウンタであり、同じ集計ではない。

- `foreign_hooks` の49実行は解消。元の pass から fail への退行は0件。
- `reader-bounds/auto`: 読取判定は合格。`child_status` の失敗は保持。
- `compare-one-line/sonnet` と `/auto`: 合格。`/haiku` は指定外パスの Read と
  accuracy の失敗を保持。deny 分離で実際の指定外 Read を免除していない。
- 残る27実行には利用上限による未測定8件を含む。accuracy、編集証跡、終了報告、
  writer の返答上限・参照順序などの失敗は保持。

詳細: [再判定結果](live-rerun-rejudge-2026-09-14.json)。
これは judge のオフライン再判定であり、disk 検証・live aggregate・トークン測定を
更新した結果ではない。`repeat.sh 1` は今回実行しておらず、リリース可能とは判定しない。

## 検証

- `PYTHONDONTWRITEBYTECODE=1 bash evals/run.sh`: pass 116 / fail 0。
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s evals -p 'test*.py'`: 71 tests OK。
- 比較判定器の全単体テスト: 219 tests OK。`judge.py --selftest` も全項目合格。
- 新規回帰テストは、隔離、Post 応答の deny 誤認、拒否後のカーソル・半減、予算、
  tool_result の帰属、成功結果の偽装、否定形 confirmed と後続事実の区別を検証する。
