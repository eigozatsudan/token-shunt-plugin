# 実機再実行2回目の照合と修正

対象: `evals/compare/tmp/runs/run.5iqYfCeg/`。ユーザーの元レポートは変更していない。

## 集計の訂正

保存された19件の verdict の全 checks を集計すると **10 pass / 9 fail**。
13 + 9 は19実行と一致しない。新しい実機実行や再採点ではない。
`compare-explicit-multifile/haiku` は gold_confirmed に成功したが、
child_reads_once に失敗しており、実行全体は fail。

## 追加の証拠

- `transcripts/compare-explicit-multifile.haiku.jsonl:52,58`:
  offset=284, limit=100 の後に offset=480。384–479 を飛ばしている。
- `transcripts/retry-policy.auto.jsonl:9,14`: model=auto の後に model 省略。
  保存判定は requested_model / resolved_model / retry_policy も失敗。
  同ファイル33行の拒否リクエストは offset=350, limit=169。
  元レポートの351という記載とは異なり、拒否前から1行重複する指定。
- `transcripts/reader-batch-ambiguous.auto.jsonl:68,76`:
  beta.py は親で Read、Agent は残る3ファイルの1回のみ。
  保存判定は必要な第2バッチと子の beta.py 証拠が不足と判定。
  この配置の妥当性はバッチ契約と合わせて別途評価が必要で、
  飛び読みだけを直せば全項目が通るとは言えない。

## 今回の変更

- bulk-reader agent: パスごとの next_line、inclusive offset、結果の最終行+1、
  拒否時にカーソルを固定して limit を半減する手順を明記。
  limit=1 拒否・末尾不明・6回消費で partial。不存在の推論には範囲全体の証拠が必要。
- bulk-reader skill: 子プロンプトへ上記手順を渡す。
  親の confirmed は箇条書き先頭と絶対パスを確認。
  model は haiku/sonnet に解決し、auto を直接渡さない。
- code-writer skill: 検証失敗は artifact 単位で failed に確定。
  partial と併記しない。TOML の既存フォールバックも python3 に統一。
- ZIP を再生成。判定器・評価期待値は変更していない。

## 残る制約

Grep の親側回避は現行フックの未対応範囲。指示更新だけで強制できたとはしない。
4万行の位置不明探索は Read のみ・6回上限では保証できない。
今回は上限やツール権限を拡張せず、正直な partial と accuracy fail を維持する。
探索能力の拡張には子の検索手段・出力予算・フック・判定器を揃えた設計変更が必要。

## 検証

両 SKILL の quick_validate 成功、ZIP ビルド成功、git diff --check 成功。
今回の変更は指示のみ。既存134テストの再実行と実機再実行は行っていない。
指示遵守の改善は次の実機実行で確認する必要がある。未コミット。
