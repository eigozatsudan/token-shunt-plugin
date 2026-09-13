# 追加確認と偽陽性チェック

対象: 2026-09-13 の未コミット修正全体。実機呼び出しは行わず、保存コード・ログ・合成トランスクリプトで検証。

## 確認順序

1. reader の最新契約と routing_checks を比較。
2. 正当な再読と拒否された飛び読みの対照を作成。
3. 非同期完了と再試行の順序を全 judge 経由で検証。
4. verification の表形式と散文形式を比較。
5. 全テスト、skill frontmatter、配布 ZIP と plugin の一致を確認。

## 確認された問題と対応

### Read 判定の誤検出・見逃し

初回 bounded Read の token-cap 拒否後、同じ offset で limit を半減した正当な再読が
repeated Read と判定されていた。一方、全文拒否→成功1–100→拒否400–499→成功101–200
は拒否分岐が cursor 検査を飛ばすため通っていた。

サブエージェント fix_live_read が修正。拒否された呼び出しも順序検査し、bounded 拒否後の
正当な継続を認める。現在の半減契約と limit=1 拒否後停止も検査する。
半減の厳密検査は今回の契約に対する追加検査であり、過去の実行結果を遡及して成功扱いしない。

### 非同期 retry の順序違反

完了通知が完全に欠ける例は既存の child_result_evidence が捕捉しており、
それだけなら全体判定の新しい抜けとは言えない。
しかし Haiku の完了が Sonnet 再試行の後・親 final の前に届く例は全 judge が成功した。
これを真陽性と確定し、fix_live_async が対応する完了通知の位置を使うよう修正。
正当な再試行前通知は成功、再試行後通知は child_result_evidence を満たしても retry_policy が失敗する。

### 散文の複合 status

`verification: syntax; status: failed/error, partial` は先頭 failed だけを抽出し、
partial 禁止の control_trunc.json 判定を通過した。表形式だけの問題ではない。
verification の syntax/requirements 併記にも同じ抽出の問題があり、共通処理で対応。
fix_live_async が散文の複合状態も検出するよう修正。補足文章中の語との対照も追加。

## 継続する制約

Grep の親側回避と、Read のみ・6回上限で位置不明の4万行を探索する問題は未解決。
maxTurns 到達前に最終回答を返せるかも実機確認が必要。
今回のオフライン成功はこれらの実機制約の解消を意味しない。
生成済み pyc は以前からの変更を維持し、ソース修正のコミット対象から除外する。

## 最終検証

全体 unittest: 144件成功（39.049秒）。judge selftest: 全16項目成功。
両スキル quick_validate、run.sh の bash -n、git diff --check 成功。
ZIP 内9ファイルの内容が plugin と一致。実機再実行は未実施。
