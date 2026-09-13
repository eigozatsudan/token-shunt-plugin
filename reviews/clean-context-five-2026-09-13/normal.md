# 通常コードレビュー・正確性（独立レビュー）

現行 README、plugin/hooks、plugin/skills、plugin/agents、および evals のソースを確認した。reviews/、docs/history/、git履歴は読んでいない。実装の変更なし。

## 候補1: EOF判定用の行数が最終改行なしファイルで1行不足する

- 重要度: P2（親での偽陽性再確認対象。メタデータ誤りは再現済み、実モデルによる回答誤りは未検証）
- 場所: `plugin/skills/bulk-reader/SKILL.md:48-53`（特に51行目）。利用側は同ファイルの step 4、`plugin/agents/bulk-reader.md` の継続・全範囲確認契約。
- トリガー: 最終行に改行がないテキストを委譲し、Readが最後の改行までで無通知に打ち切る場合。例えば、2000個の改行の後に2001行目のマーカーがあるファイルについて、親が `wc -lc` の2000をEOF行数として供給し、Readが最初の2000行を返した場合。
- 原因: `wc -l` は改行数を数え、最終未終端行を含む論理行数を返さない。スキルはその値をそのまま「line count」「supplied EOF」として使用する。実装済みフックと評価器は未終端行を1行として数えるため、同じファイルについて親から子へ渡すメタデータだけが異なる。
- 影響: 未読の最終行があるのに供給されたEOFへ到達したと判断し得る。最終行の定義やマーカーを見落とし、不存在確認等を誤って完了扱いする可能性がある。最終改行を必須とする仕様上の制限は確認した現行README・スキル・エージェントにない。
- 確認コマンド:

```bash
python3 - <<'PY'
import pathlib, subprocess
p = pathlib.Path('/tmp/token-shunt-unterminated-review.txt')
p.write_text('padding\n' * 2000 + 'FINAL_MARKER=present')
print(subprocess.run(['wc', '-lc', str(p)], capture_output=True, text=True).stdout.strip())
print('Logical lines:', len(p.read_text().splitlines()))
print('First 2000 lines contain marker:', 'FINAL_MARKER' in ''.join(p.read_text().splitlines(keepends=True)[:2000]))
PY
```

- 実測結果: `2000 16020 /tmp/token-shunt-unterminated-review.txt`、`Logical lines: 2001`、`First 2000 lines contain marker: False`。
- 対応案: バイト数とは別に、最後の未終端行も含む論理行数をメタデータとして計算する。または `wc -l` をEOFの確定根拠に使わず、未終端最終行の有無も子へ渡す。
- 限界: 上記は誤ったメタデータとその消費契約の再現。Readの実行やClaudeによる誤回答は今回実行していない。統合側で実際のReadの切り詰め契約との整合を確認してから最終指摘に採否を決める。

## 検証

- `python3 -B -m unittest discover -s evals -p 'test_*.py'`: 52 tests, OK。
- `python3 -B -m unittest discover -s evals/compare -p 'test_*.py'`: 152 tests, OK。

## 除外した候補

- `hooks.json` の未引用 `${CLAUDE_PLUGIN_ROOT}`: `bash -c` では空白パスで127になるが、親の公式仕様確認により現行の `args: []` はexec formである。再現の実行方法が現行製品契約に一致しないため除外。
- `head/tail -n 0` の大ファイル拒否: 実コマンドは出力0バイト、フックは拒否することを確認。しかし親が確認した現行設計で解釈可能な行数はN≥1と限定されているため仕様通りとして除外。
- 未対応シェル構文・展開、Grep等の非対象、フックの集計を跨ぐ小分け読みは既知の非対象として扱い、指摘していない。
