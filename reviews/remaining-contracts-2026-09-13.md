# 残る実機失敗の確認と契約修正

対象: `evals/compare/tmp/runs/run.xv9H1gDW/`。実機再実行はしていない。

- bulk-reader子の出力を、事実ごとの `confirmed: <path> — <symbol>: <fact/value>` と不足・終了状態に具体化。値もコードフェンスに入れず、定義や呼出関係は説明で返す。親は全委譲にこの短い出力契約を添え、最終回答にも各事実の根拠ラベルとパスを残す。既存の領域単位読取契約を維持し、境界確認の古い「パス各1回」表記も揃えた。
- retry-policyのtranscript L44には実際には診断文がある。ただし「関数名から計算処理かもしれない」「逐語引用がない」という理由で正しい要約を疑い、引用を要求している。診断欠落だけの問題ではない。パス付き事実・値が根拠になること、逐語引用の欠如と関数名だけの疑念では昇格しないこと、許可理由と具体的不足を `retry_reason:` で渡すことを明記した。
- bulk-factsの質問を「report_token()が返す文字列・供給元関数名・defの開始行」に統一。存在しないMAGIC_TOKEN変数を問う表現を除き、goldの20をreturn行21と区別した。値・関数名・goldは変更していない。
- 正本設計書に出力・再試行・質問文の変更を反映した。

## dense-linesは子の本文返却を確認できない

`compare-edit-dense-lines.auto.jsonl:38` のAgent返答は補助情報込み645文字。マーク2件の値と行ヒントを返しており、fixtureの21行引用はない。L25/L32の長い本文は子のRead結果であって、Agent最終返答ではない。

`judge.py` の `quote_leak` はfixtureの各行について `l in agent_result_text` を独立に判定している。同じ `a` 行が続くfixtureでは、回答内の1文字の `a` を21回数えてしまう。既存関数で以下の最小再現を確認した。

```python
quote_leak('a', ['fixture'], {'fixture': 'a\n' * 21})
# (True, '>20 consecutive fixture lines from fixture')
```

この1件を子契約違反と断定する前提は訂正が必要。判定器は今回は変更していない。連続引用を回答内の実際の連続した範囲として判定する修正と、短い要約を通し実際の21行引用を落とす回帰テストが別途必要。

## 検証

- `bash evals/run.sh`: 110 pass / 0 fail（配布ZIPも更新）
- `python3 -m unittest discover -s evals/compare -p 'test_*.py'`: 78 pass
- skill-creatorの `quick_validate.py`: bulk-readerスキルはvalid
- 実機でコードフェンス・confirmed・再試行が改善するかは未検証。上記の判定器誤検出も未修正であり、リリース合格とは扱わない。

## 追記: `quote_leak` の誤検出を修正（2026-09-13）

上記の最小再現どおり、`judge.py` の `quote_leak` は fixture の各行を独立に
`in agent_result_text` 判定していたため、連続した `a` 行の fixture では回答中の
1文字 `a` を 21 行の引用として数えていた。連続する行の**実際の連続ブロック**が
回答に含まれるときだけ leak と判定するよう修正した（回答側の CRLF は正規化）。

- `evals/compare/judge.py`: 行ごとの run カウントを、連続 run の結合ブロックの
  部分文字列判定に変更。
- `evals/compare/test_judge_integration.py`: `QuoteLeakContiguityTests` 5件
  （1文字回答／dense fixture 上の短い要約／実際の連続ブロックは依然 leak／
  離散的に散らばった行は非 leak／CRLF 回答）。
- 実機 transcript で確認: `compare-edit-dense-lines.auto` の 645 文字の Agent
  返答は `(False, '')` になり、既存の 21 行引用検出は維持されている。

オフライン `evals/run.sh` 110 pass / 0 fail、`evals/compare` unit 83 pass。
