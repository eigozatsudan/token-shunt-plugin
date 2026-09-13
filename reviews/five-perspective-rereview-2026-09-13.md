# 5視点の再レビューと偽陽性チェック

## 結論・実施範囲

合算・反証確認後の真陽性は **4件（P2: 3件、P3: 1件）**。いずれも比較評価器の正しさの問題で、新規のセキュリティ脆弱性として報告するものではない。コード修正・コミットはしていない。

**独立レビューは4視点が完了、敵対的視点は途中停止した。完全な5視点レビューが完了したとは扱わない。** 敵対的担当の実行が自動判定で `This content was flagged for possible cybersecurity risk.` として停止した。その後は追加調査を依頼せず、既に確認した範囲と候補の記録だけを回収した。親は既報の一般的な評価器候補を、通常のオフライン品質検査として確認した。

各担当は `fork_turns: none` の新規コンテキストで開始した。過去会話・レビュー結果は渡さず、現行ワーキングツリー（未コミット変更も含む）を対象にした。過去レビュー・ログ・Git履歴は根拠から除外した。俯瞰・敵対的担当では現行設計書の検索・読取時に同ファイル内の過去記録も一部表示されたため、リポジトリ内の履歴文字列まで完全に未閲覧だったとは主張しない。

開始時に97ファイルのハッシュを保存し、報告追加前まで変更がないことを確認した。既存の変更、Pythonキャッシュ、配布ZIPを維持した。ライブClaude/API・ネットワークを使う試験は実施していない。

| 視点 | 結果 |
|---|---|
| 俯瞰 | 完了。確定0件。空白入り配置先などの候補は反証確認へ |
| 通常 | 完了。writer参照確認の2候補を提出、親も再現し採用 |
| 敵対的 | 自動判定で中断。既報のwriter境界候補1件は親の追加確認で採用。それ以外の残りは未完了 |
| 運用 | 完了。確定0件。ローカルCLI実装により配置先・進捗イベントの候補を棄却 |
| セキュリティ | Standard scan完了。精読範囲で検証済み脆弱性0件。全ファイル網羅ではなくcoverageはpartial |
| 親による合算・反証 | 上記候補の再現・反証と、BOM付きPythonの誤拒否1件を追加確認 |

## F1 — P2: 正しい絶対パスの参照Readをwriter判定が認識しない

根拠: [judge.py](../evals/compare/judge.py) 1122–1132行、`use_targets_path` の完全一致判定。実ケース `compare-code-writer-ok` は `fixtures: ["codegen/greeter.py"]` を持つ一方、プロンプトの参照先は `{FIX}/codegen/greeter.py`。runnerはプレースホルダを置換するが、`fixtures` の相対文字列は絶対化しない。

子がプロンプト通りの**絶対パスRead → 成功結果 → Write → 成功結果**を行う正常なtraceを、現行の実ケース・実judgeへ投入した。短いAgent返答と親unittest成功の証跡もあり、唯一の失敗理由は次だった。

```text
child_ref_before_write: Write of target before successful Read of greeter.py
```

Readの文字列表記をspecと一致させる対照ではこの失敗が消える。`resolve_fixture_path` は存在するが、この比較には使われない。ディスク検証が成功してもjudgeの失敗は取り消されないため、正常なwriterを比較・出荷判定で誤拒否する。

対象には同形式の `auto-large-writer` も含まれる。修正時は実行ごとのfixtureルートを保持してパスを解決し、単なるbasename一致で別ファイルを認めないこと。

再現証跡: [/tmp/ts-r6-normal/ordered_absolute_read.jsonl](/tmp/ts-r6-normal/ordered_absolute_read.jsonl)、[実spec](/tmp/ts-r6-normal/writer-spec.json)。親もコピーではなく現在の `evals/compare/judge.py` で再実行し、同じ理由だけでfailになることを確認した。

## F2 — P2: 参照Readの結果が返る前のWriteを合格にする

根拠: [judge.py](../evals/compare/judge.py) 1127–1138行。子のtool_use一覧でReadがWriteより前に並ぶことしか調べず、Read成功結果のイベント位置をWrite開始位置と比較していない。

F1の表記不一致を除いた独立対照で、次の順を実judgeに渡すと `child_ref_before_write=true`、全体passだった。

```text
子assistant: 同一メッセージに Read, Write の2呼出し
子tool_result: Write成功
子tool_result: Read成功
```

結果を受け取る前にWriteを発行しているため、参照を読んでから生成する契約を満たさない。判定器は全イベントを読み終わってからRead成功結果を見つけ、それが先に利用可能だったかの確認を省いている。

最も強い反証は、F1が通常の絶対パスtraceを先に落とすこと、およびディスク側にもunittest/mutation検査があること。ただしパス表記を揃えた独立対照では現行の順序判定が通り、生成物の品質検査は生成**前**のRead結果受領を証明しない。この時系列の不備はF1と別原因なので、別件として維持した。ライブでの発生頻度や全runner経路の成功までは主張しない。

修正時は同じ子に属するRead呼出し・成功結果・Write呼出しの位置を比較し、結果がWriteより前であることを要求する。

再現証跡: [/tmp/ts-r6-normal/simultaneous_relative_read.jsonl](/tmp/ts-r6-normal/simultaneous_relative_read.jsonl)。親も現行judgeでpassを確認した。

## F3 — P2: greetをテストしない50行unittestを境界ケースが受け入れる

根拠: [flow_checks.py](../evals/compare/flow_checks.py) 210–222行。`greet()` 呼出しをAST全体から探す検査と、TestCase/testメソッドの存在検査が別々で、両者が結び付いていない。

親が既報候補を検証した。次の本文にコメントを足して50行にすると、実ケース `auto-routing-boundary-50-lines-writer` のdirect経路で、実judge・実disk_check・実py_compileがすべて成功した。

```python
import unittest
from greeter import greet

if False:
    greet("world")

class OtherTest(unittest.TestCase):
    def test_unrelated(self):
        self.assertTrue(True)
```

実際のunittestも1件成功し、参照側greetを常に例外を送出する実装へ変えた対照でも成功した。つまり要求された「greetをカバーするテスト」を生成していない。

`py_compile` は構文検査だけである、という反証自体は正しい。しかしケースのプロンプトはgreetをカバーするunittestを要求しており、構文成功だけでその生成要求が満たされたとは扱えない。実行可能な準備コードとしてテスト外に呼出しがあるだけの正常例を誤拒否しないよう、修正は単なる呼出位置の文字列制限ではなく、必要なテストの実行・有効性を確認できる方法を選ぶ。

親の実測: [checkerとunittestの対照](/tmp/ts-r6-unittest-result.json)、[実caseのjudge/disk結果](/tmp/ts-r6-unrelated-full-result.json)。敵対的担当が候補を提出した時点では未検証であり、その担当が再現まで完了したとは数えていない。

## F4 — P3: Pythonとして有効なUTF-8 BOM付き成果物を拒否する

根拠: [flow_checks.py](../evals/compare/flow_checks.py) 189–192行。Pythonソースを固定の `encoding='utf-8'` で文字列化してからAST解析するため、先頭BOMが文字列に残る。

正常な49行のgreet/helperモジュールの先頭にUTF-8 BOMを付けた対照を作った。

| 入力 | 実py_compile | 実disk_check |
|---|---:|---:|
| BOMなし、49行 | 終了0 | 成功 |
| 同じ本文にUTF-8 BOM、49行 | 終了0 | 失敗 |

失敗は `invalid non-printable character U+FEFF`。Python自身はこのBOMを扱え、ケースはBOMなしに限定していない。フックの制限や生成物の構文不正ではなく、評価器のデコード方法による誤拒否である。通常の生成でBOMを出す頻度は不明なためP3とした。

修正時はPythonソースのエンコーディング規則に沿った読取・解析を使う。実測: [/tmp/ts-r6-bom-result.json](/tmp/ts-r6-bom-result.json)。

## 偽陽性・未採用の整理

- **空白入りplugin配置先:** hooks.jsonは全コマンドに `args: []` を付けている。ローカルCLI 2.1.270の埋込JS `bwe` はこの場合に変数を文字列置換し、単一実行パスと引数配列を直接spawnする。親も実装を確認した。未引用のshell実行だけを再現する検査は実ホストと不一致なので棄却。
- **Read最大6をmaxTurnsと混同した評価器の誤拒否:** 設計§26.3（798行）と§26.5（826行）に起動あたり最大6 Readが独立に明記されているため撤回。agent/SKILLへのその明記不足は文書・指示の整合上の観察として残すが、今回の確定不具合には数えない。
- **runnerが全成功でも終了1:** 末尾の `exit $agg` が読取範囲から漏れたために出た候補。末尾全体を確認して撤回。
- **doctorの `--forward-subagent-text` 不在:** ローカルCLIはこのflagなしでも子tool_use/tool_resultを進捗イベントへ載せる実装だった。単独では診断失敗を示さないため棄却。
- **小仕事のbulk-reader機構強制例外の文言省略:** 評価側の明示的な委譲指示があるため、既定手順の文言差だけで経路失敗とは断定せず未採用。
- **未対応コマンド・前置リダイレクト・累積Read・走査後タイムアウト・プロンプトによる書込先制約:** 明示仕様とホスト権限を区別した。仕様上の限界だけを新規バグやセキュリティ脆弱性として数えない。

## 検証とセキュリティ記録

現行ソースの `/tmp` コピーで、比較評価unittest **112件成功**、フック評価 **110項目成功・0失敗**。フック評価の内部Python回帰は52件で、110項目と単純加算しない。Bash構文確認も成功。ZIP内9ファイルと現行pluginの本文が一致し、3フックの実行権限を保持していた。テスト成功が上記4件の不存在を意味しないことを、追加の対照で確認した。

新規Standard security scan `1901c52c-3d64-4d31-bcee-bebd00099b7f` は完了済み。23ファイルを精読し、検証済みセキュリティ指摘0件。全比較テスト・JSONカタログ・fixture・ZIPを個別に静的監査したわけではなく、canonical coverageはpartial。ホスト側の権限処理などは未実機確認。利用トークン数はツール側で取得不能（`scan_thread_unavailable`）だった。

[生成されたセキュリティレポート](/tmp/codex-security-scans-egJjbw/token-shunt/ec33f912b415679faf9837e5cd62c90ede571840_20260913T073852Z_gw2m0gb9/report.md)。[独立俯瞰](/tmp/ts-r6-overview.md)、[通常](/tmp/ts-r6-normal.md)、[敵対的・中断記録](/tmp/ts-r6-adversarial.md)、[運用](/tmp/ts-r6-operations.md)、[セキュリティ要約](/tmp/ts-r6-security-summary.md)。

## 修正追記（2026-09-13）

上記は修正前のレビュー記録。確定したF1–F4を2名のサブエージェントで分担して修正した。

- **F1:** runnerがfixture rootとtool cwdをspecへ保存し、参照Readと対象Writeを正規化して照合する。絶対パス・相対パス・`/./`表記の正常例を受け入れ、別ディレクトリの同名ファイルを拒否する。
- **F2:** 同じ子エージェントの成功Read結果が各対象Writeより前に届いていることを要求する。同時発行、遅延結果、失敗結果、他エージェントの結果を拒否する。
- **F3:** 50行ケースで実unittestを別プロセスで実行し、指定参照のgreetがテスト中に呼ばれることと、greetの戻り値・空名例外を壊した対照でテストが失敗することを確認する。helper・setUp・alias・絶対パスimportの正常例を維持し、無関係なテストや早期終了を拒否する。完了証跡は専用一時ファイルで確認し、atexitの標準出力に影響されない。
- **F4:** `tokenize.open`でPythonのソースエンコーディング規則に従って読み取る。UTF-8 BOM、encoding宣言の正常例を受け入れ、構文不正は拒否する。

統合検証: 比較評価unittest **120件成功**、judge selftest全件成功、runnerのBash構文確認と`git diff --check`成功。実disk_checkを通す正常・異常対照を含む。既存plugin・ZIP・追跡済みpycは修正開始時のハッシュと一致する。

ライブClaude比較は未実行。50行の検査は生成Pythonを実行し、各プロセスに15秒の上限を設けるが、セキュリティ隔離を提供するものではない。今回の変更は未コミット。
