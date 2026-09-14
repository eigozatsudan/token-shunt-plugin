# Eval 契約と判定の整合

## 修正

- `judge.py`: 正確な `awk 'END{print NR}'` に複数のファイル引数がある場合も行数集計として扱う。追加プログラム指定・変数代入・後続の本文出力は例外に含めない。
- `flow_checks.py`: 先頭の literal `cd DIR && python3 ... --verify ...` を認識する。結果 JSON のパス・検証レベル・成否との照合は維持し、任意の条件式や展開は認めない。
- `routing_checks.py`: `confirmed: <path> — No TOKEN definitions, references, or imports found` という独立した不在報告を関係主張と区別する。肯定的な関係を同じ行に追加した場合は引き続き不合格。
- `judge.py`: 末尾の status と stop_reason の間の空行を許容する。欠落、重複、介在する本文、末尾の余分な本文の扱いは維持する。
- `compare-one-line` / `auto-one-line`: 既知の1行入力では最初の Read を offset=1, limit=1 とすることを両プロンプトに明記し、委譲時も子へ渡す。フックの半減規則・予算・免責に必要な実際の1行拒否は変更しない。
- `user.rb`: 532行を保ち、コメントパディングを短縮して22,546 bytesにする。350行超・総 I/O 16KiB超という委譲条件と末尾の参照関係は保つ。6回予算内の成功は実機で確認が必要。

## 分類の補足

小仕事ルールは質問に必要な総 I/O の判定であり、関係を問う複数ファイルは同一子に渡す契約が既に存在する。したがって、関連ファイルの一部が小さいことだけでは `auto-explicit-multifile` の3パス1起動要件と仕様矛盾しない。期待値と自動経路選択用プロンプトは維持する。

1行入力で任意に大きい初回 limit を選ぶと6回で1に到達できない点は、今回 eval が与える既知メタデータで対処する。一般入力のフック挙動を解決したとは扱わない。

## 測定の扱い

過去のトランスクリプト、判定結果、last-run は更新しない。入力やプロンプトを変えたケースの成否・費用・隔離は、新しい実機実行で判定する。今回の変更だけではリリース不可を解除しない。

検証: 比較用 unittest 234件合格、`evals/run.sh` pass 119 / fail 0、`bash -n evals/compare/run.sh` 合格。1行ケースの4プロンプトに初回範囲指示が一度ずつあること、Rails fixture の実行コードが変更前と同一であることも確認した。実機再実行は未実施。

## 独立検証後の追補

初回のA2・A3修正は実入力全体を再現しておらず、未解消だった。A2は末尾の `; echo "EXIT:$?"` も認識し、JSONの成否を実際のEXIT値と照合する。echoがBashの終了状態を成功に変えるため、期待どおり失敗した検証には `ok:false` と `EXIT:1` が必要。ネイティブBash結果のstdoutがある場合はそれを用い、stderr由来の `Shell cwd was reset ...` を終了コードと混同しない。任意のセミコロン連結や固定EXIT値は認めない。

A3は不在報告に付く `(entire 7-line file read)` と `no TOKEN reference present in this file` を認識する。補足を任意の文章として除外せず、肯定的な参照主張を付加した行は引き続き拒否する。

保存済み `tmp/runs/run.XS49lAFe` の元specとトランスクリプトをそのまま使って再判定し、writer-verification-levels/auto の7コマンドすべてが認識され、同runとreader-batch-ambiguous/autoの両方が全体passになることを確認した。保存済み結果・last-runは上書きしていない。これは過去証拠の再判定であり、新しい実機測定ではない。

C-2によるfixture縮小は `delegate_lt_direct_and_fixture` の絶対バイト上限も下げる。旧測定の18,133 / 19,840 / 30,468 bytesは新入力での測定値ではない。再実行でisolationが落ちた場合は、委譲側の親入力増加、directとの差、新fixture上限との差を分けて記録し、fixture縮小の影響を切り分ける。隔離判定は緩めない。

追補後の検証: 比較用 unittest 237件合格、変更対象の `git diff --check` 合格。
