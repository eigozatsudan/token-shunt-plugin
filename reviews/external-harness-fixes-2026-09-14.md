# 別ハーネス指摘の修正・検証

Outcome: **fixed**（精査で確定した、保証範囲内の欠陥と文書・配布・評価の不整合）。既存の未コミット変更を維持して修正した。実機A+B再測定とリリース判定更新は未実施。

## 分担と独立確認

別コンテキストの境界調査担当でBash・モデルフック・判定器の経路と互換性を確認後、Bash、ZIP、文書を各サブエージェントに分担した。親はハーネス・モデルフック・deny_route判定と統合検証を担当。実装後に別コンテキストの読取専用レビューを1回実施した。

レビューが追加で発見した「複数JSON値を連結するとモデル判定がfalse扱いになる」経路を親が再現し、単一JSON入力の検証と回帰ケースを追加した。レビューからそれ以外の具体的な範囲内の迂回・回帰指摘はなかった。追加修正後にも最終全回帰を実行した。

## 変更

| 対象 | 修正と不変条件 |
|---|---|
| `plugin/hooks/check-bash-read`、`evals/test_cd_hooks.py` | literal cdの検出・未解決状態の記録をTRACK_CD早期returnより前に移動。cwd追跡ができなくても後続readerを元cwdとして許可しない。到達不能なSEPSのpipe分岐を削除。通常のcd連鎖・cd失敗時・小容量読取は維持。 |
| `scripts/build-zip.sh`、`evals/test_build_zip.py` | zip/Python両ビルド経路で `__pycache__`、`.pyc`、`.pyo` を除外。Python/zipinfo両検証器も混入を拒否。manifest位置・重複・実行ビット検証は維持。 |
| `.gitignore`、`evals/test_reader_contract.py` | Pythonキャッシュの新規追跡を防ぎ、拡張子なしhookの直接テスト読込が配布ツリーへpycを書かないようsourceをcompile/exec。既存キャッシュの削除に依存しないZIP対策と併用。 |
| `plugin/hooks/check-agent-model`、`evals/compare/test_unreadable_and_model.py` | stdinを単一JSON objectに限定し、明示されたtool_inputが非objectならexit 2。空入力・連結JSON・不正な入れ子を拒否。通常の両workerのhaiku/sonnet、対象外Agent、空の非操作objectは維持。 |
| `evals/compare/judge.py`、`evals/compare/test_deny_route_evidence.py` | 対象親ReadのIDに対応する失敗tool_resultに、同じtoken-shunt拒否理由があることを要求。Read → 親PreToolUse Read hook → 同一Readの失敗結果 → bulk-reader Agentの順序を確認。異なる明示hook ID、子/Bash/Postイベント、成功・未存在エラーだけの結果では通さない。 |
| `evals/run.sh`、`evals/bash-hook-evals.json`、`evals/test_harness_inputs.py` | 帰属付き非ルーティングdeny用の `deny_safety` を追加し、process substitutionと未解決cdの2ケースをcatalog化。既存 `deny` / `deny_budget` のbulk-readerへの案内条件は維持。big-scanの追跡状態に関するコメントを訂正。 |
| 設計書、`scripts/doctor.sh` の手動確認表示、JSON examples | hooks全文7登録・5スクリプト、依存関係、構成一覧、非bare runner方針を現実装へ統一。readerの入力・結果メタデータと保守的停止を文書化。集計例とskip例を分ける。doctorの実行フローは変更していない。 |
| `token-shunt.zip` | 全hook変更後に再生成。5フックが現ソースとbyte一致し実行ビットを保持、Pythonキャッシュなし。 |

補足: この修正開始時点の `evals/run.sh` は既に `-B` を使っていた。前回精査報告の「run.shが-Bなし」という記述は古い指摘を引き継いだ誤り。今回のsource直接compile/execはテストファイルを単体起動する場合もキャッシュを残さない対処であり、ZIP側の除外を主対策とする。

## 検証結果

1. 構文・形式: 対象Bashスクリプトの `bash -n`、変更Pythonの構文、JSON例とcatalog、対象diffの空白検査が合格。設計書のmanifest/hooks JSON全文が実ファイルと一致。
2. 元の問題と近接条件: cdの7構文×元cwdのファイル不在/小容量の14条件がdeny。人工82KBファイルを実Bashで読む対照付き。旧早期return順の一時コピーでは新規回帰が14条件すべて失敗し、検出能力を確認。元のJSON形状不正と追加発見の連結JSONはexit 2。正しい単一object/モデル指定は維持。
3. 配布: 汚れたツリーからzip/Python両経路でビルド成功しキャッシュなし。両verifierで混入archiveを拒否。最終root ZIPのキャッシュ不在・ソース一致・実行ビットを確認。
4. 評価証拠: 無関係denyの元反例と、誤ID・欠落/成功結果・子イベント・順序逆転・同一message内の未完了証拠を拒否。Agent/Task、hookのoutput/stdout、明示hook ID、パス別表記、許可されたtargeted Readの対照を維持。保存済み `run.XS49lAFe` / `run.mnVnW1FU` / `run.NckO7koy` の `compare-hook-deny-route/auto` は元specで全体passを維持。既存測定結果は上書きしていない。
5. 最終回帰: `python3 -B -m unittest discover -s evals/compare` **241 tests OK**。`bash evals/run.sh` **pass 121 / fail 0**（安全denyのcatalog追加2件を含む）。追加JSON-stream修正と最終ZIP再生成の後に両方実施。

## 変更しない意図的な制約

- 括弧グループ・wrapper等の一般シェル解析は従来の保証範囲外。`(cd sub && cat f)` を今回修正済みとは扱わない。不確定なcdを含む操作は別Bash呼出し＋絶対パスを案内する。
- 拒否Readによる予算/パス枠消費、破損した同一session/agent状態でのfail-closed、readerの独立した8MiB上限は維持し文書化。予算を回復させる自動リセットは追加しない。
- フックが防いだAgent起動とモデルの事前遵守は別であり、拒否済み起動を実行済みAgentへ数え直さない。
- CLIが必要なhookメタデータを実際に供給すること、実機の全品質・隔離・経路ゲートが通ることは、今回のオフライン修正検証とは別。新規実機呼出し・出荷は行っていない。
