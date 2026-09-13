# five-perspective-2026-09-13g.md の精査

実施日: 2026-09-13。対象は [g統合報告](five-perspective-2026-09-13g.md) と、その原票・再検証票・対応する作業ツリーの修正。

以下は記載したハッシュ時点の精査結果。後続の修正・検証は [修正完了記録](five-perspective-2026-09-13g-fixes.md) を参照。

**G1〜G5の元の指摘は妥当。ただしG1・G2・G4の修正方針／現在の修正には、再現できる不足が残る。** G3とG5は今回確認した条件で解消している。前回のCodex F3は確定P2から仕様判断待ちへ訂正するが、g報告の「偽陽性確定」という理由付けにも補足が必要。

今回は既存候補と後続修正の精査であり、新たな独立5観点レビューとは数えない。元の報告・実装は書き換えず、精査結果と再現用スクリプトを別ファイルに保存した。

## 対象の固定と検証

HEADは `cb1ab7c94952df128aa9d171217177390b4a151e`。ただし後続の未コミット修正があるため、HEADだけでは今回の検証対象を識別できない。一時コピー `/tmp/ts-g-audit-hs6qcqpo` を取得し、そのコードで以下を実施した。

| ファイル | 検証した内容のSHA-256 |
|---|---|
| `reviews/five-perspective-2026-09-13g.md` | `9d486c095bf7b293d27a3858955e063bd6b93b0341a4b3d90e8e1d3642393cb6` |
| `evals/compare/judge.py` | `21496030f06275ad25c30b215d772bc96fb881d9069124a0fb9273d4237c26b6` |
| `evals/run.sh` | `cad35b67d6fded03626b9e005afd883ebd894ed9a5ff962611a18035e80a122a` |
| `plugin/skills/bulk-reader/SKILL.md` | `52845f037042c68b582ae32eef625d572be5765fa1f746ea734e5b74b74bccde` |

- `evals/run.sh`: **110項目成功、0失敗**。内部の4回帰群は合計52テスト。
- 比較判定器のunittest: **160テスト成功**。
- 以下の不足3件は、通常テストとは別に合成入力と対照入力で再現した。
- 保存済み実ログのG2を現在の判定器で再計算した。新規のモデル呼び出し・費用計測・インストール変更はしていない。

## 採否と現在の状態

| ID | 元の指摘 | 現在の修正の確認結果 |
|---|---|---|
| G1 | 真陽性 | thinking先行・異なる本文の後続イベントは取り込めるようになった。ただし同じ引数の別tool-useを重複イベントと誤認する。A3参照。 |
| G2 | 真陽性 | 保存実ログの親入力234,012・親出力2,565を正しく合算した。ただし欠測値を0へ変えてしまう。A2参照。 |
| G3 | 真陽性 | 両カタログについて、不正JSON・空配列・オブジェクト・ファイル欠落の計8条件で終了1を確認。元の96ケース脱落の問題は解消。 |
| G4 | 真陽性 | 全fixture欠落ならfail。ただし複数fixtureの一部だけが欠けると検証不能をpassにする。A1参照。 |
| G5 | 真陽性 | `awk 'END{print NR}'` は、未終端最終行あり2,001行／改行終端2,001行／1行／空ファイルをそれぞれ2,001／2,001／1／0と計数。メタデータ指示の不整合は解消。モデルの実回答品質は未測定。 |

## 修正方針に残る不足

### A1 — P2: G4の「1件も読めなければfail」では検証範囲が不足する

報告位置: [g.md:57](/home/dev/projects/skills/token-shunt/reviews/five-perspective-2026-09-13g.md:57)。実装位置: [judge.py:1177](/home/dev/projects/skills/token-shunt/evals/compare/judge.py:1177)。

`bodies_ok = any(...)` なので、必須fixture Aだけが読めてBが欠けていると検証可能と扱われる。`quote_leak` はBの本文を読めず、Aを代わりに比較してもB由来の内容の有無は確認できない。

| 対照条件 | 子返答 | 現在の結果 |
|---|---|---|
| Bのみ指定、B欠落 | 3,000バイト1行 | fail / unreadable fixture body |
| AとB指定、Aは短い別内容、B欠落 | 同じ3,000バイト1行 | **pass / child_no_body=true** |
| AとB指定、Bを子返答と同じ内容で復元 | 同じ3,000バイト1行 | fail / >2KiB contiguous quote |

問題は「欠落したBからの引用を証明できた」ことではなく、**Bについて検証できないのに全文引用なしと判定したこと**。単一fixtureに限定されないbulk-reader契約に対して、全欠落だけを塞ぐ方針では不十分。

修正案: `fixtures` と `fixtures_abs` の同一ファイルを指す別名を解決したうえで、検査に必要な各ファイルの本文を取得できたことを確認する。一部欠測も未検証としてfailにする。無関係な別fixtureの本文で欠けた証拠を代用しない。単純な文字列リストへの `all()` では別名の扱いで偽陽性になり得るため、先にファイル対応を確定する。

### A2 — P2: G2の合算で、欠測usageが実測0トークンへ変わる

報告位置: [g.md:55](/home/dev/projects/skills/token-shunt/reviews/five-perspective-2026-09-13g.md:55)。実装位置: [judge.py:342](/home/dev/projects/skills/token-shunt/evals/compare/judge.py:342)、同350行以降。

複数resultの場合に `u.get(...) or 0` を足しているため、測定値が無いことと実測0が区別できない。`require_parent_tokens` を有効にした対照で確認した。

| usage入力 | 計測結果 | 必須トークン判定 |
|---|---|---|
| result 1件、`usage={}` | input/outputともnull | fail |
| result 2件、両方`usage={}` | 全区分0・output 0 | **pass** |
| result 2件、input/outputのみ存在 | cache区分を0で補完 | **pass** |

G2の目的は必須の累積観測を正しく残すこと。取得していない値を0で埋めれば、その必須観測のゲートが失われる。数値が揃う正常ケースの合算テストだけでは検出できない。

修正案: 合算前に各対象resultの必須区分を検証する。欠測があればその集計を未検証として保持し、必須計測をfailにする。親resultと親子累積の `modelUsage` を分ける方向は正しい。[公式のターン別usageとcall累積の区別](https://code.claude.com/docs/en/agent-sdk/cost-tracking#track-costs-in-streaming-input-mode)

### A3 — P2: G1で、本文一致をイベントの同一性として使っている

報告位置: [g.md:54](/home/dev/projects/skills/token-shunt/reviews/five-perspective-2026-09-13g.md:54)。実装位置: [judge.py:311](/home/dev/projects/skills/token-shunt/evals/compare/judge.py:311)。

現在のキーは `("a", message.id, context_text)`。同じAPI応答で、同じ引数を持つ別のツール呼び出しが出ると、異なる `tool_use.id` を持っていても1件へ潰す。

再現は同一message ID、tool-use IDが `a1` と `a2`、それぞれの `Agent.input={"prompt":"same task"}`。`Transcript.tool_uses` には2件存在するが、親本文量には `{"prompt":same task}` が1件しか残らない。これは同じイベントの再送を2回数える要求ではない。

同じAPI応答から複数メッセージが出ることとusageのID重複排除は[公式仕様](https://code.claude.com/docs/en/agent-sdk/cost-tracking#track-per-step-usage)に沿うが、内容ブロックには別の同一性がある。G1の元の問題に比べ発生条件は狭くなったものの、本文量の過少計上は残る。

修正案: event UUIDやtool-use IDなどを保持し、同じ内容の別イベントと同じイベントの再送を区別する。テキストブロックにもイベント・ブロック単位の識別を用い、本文の一致だけで再送とはみなさない。

## F3の分類についての訂正と留保

前回の私のレポートは「CLI終了17でも成功本文があればpass」を確定P2として数えた。非空ストリームを判定し、そのケースの品質・経路・隔離で合否を決める意図がコードに明示されるため、**確定した仕様違反としてのP2は撤回し、仕様判断待ちの運用リスクへ変更する**。

一方、[g.md:31](/home/dev/projects/skills/token-shunt/reviews/five-perspective-2026-09-13g.md:31)の「ケースプロセスrc=0は出荷条件ではない」という断定も、設計全体から一意には導けない。[設計§13の起動判定:572](/home/dev/projects/skills/token-shunt/docs/2026-09-12-token-shunt-design.md:572)は「次を順に実行し、どれかが非0なら比較evalはfail」と書き、その列挙には「必須ケースを実行」が含まれる。

ここでいう非0が、モデルCLIの終了コードか、本文判定まで含むケース評価の終了コードかが明確でない。実装が現在そう動くことだけを根拠に、仕様上も完全に意図された動作だとは断定しない。

報告書の分類は「非空本文をjudgeする現行実装とは一致。CLI非0をケースの独立失敗条件にするかは仕様を明文化」にすると正確。本文を解析することと、終了コードを診断用に記録することは両立する。仕様が決まる前にゲート条件を変更することは今回求めない。

## その他の採否・文書精度

- **未引用の末尾LFは偽陽性という判定に同意。** 実Bashでも未引用LFはファイル名に含まれない。短い `normal` と大きい `normal\n` を用い、未引用は6バイト・引用ありは70,000バイトを出力する対照を再現した。元の敵対的原票はこの実Bash対照が欠けていた。
- **`<`・ANSI-C引用の限定対応を実装バグから外すことに同意。** ただし追記された `cat <large>` / `head -c 70000 <large>` は、そのままでは末尾 `>` の出力先が無くBash終了2・本文0バイトとなる。正しい実例は `cat <large.txt` / `head -c 70000 <large.txt`。これは [g.md:32](/home/dev/projects/skills/token-shunt/reviews/five-perspective-2026-09-13g.md:32)、再検証票、[README.md:168](/home/dev/projects/skills/token-shunt/README.md:168)、設計§15へ引き継がれたP3の例示誤り。プレースホルダーとリダイレクトを混ぜず、実ファイル名で書くとよい。
- **Grepは仕様の隙間という分類に同意するが、解決済みではない。** 「契約とevalで担保」と検出対象の列挙の不一致は残る。編集用の短いGrepと分析用の本文取得を区別する仕様・受け入れ条件を未決事項として残すべき。「コード変更しない」ことを「目的上の問題が無い」へ読み替えない。
- **doctorのソース診断という文書補足は妥当。** ソース固定のプローブと、導入済みキャッシュの検査は別物。`--plugin-dir` の優先関係と明示versionの更新挙動も[公式のローカルテスト](https://code.claude.com/docs/en/plugins#test-your-plugins-locally)・[version管理](https://code.claude.com/docs/en/plugins-reference#version-management)と整合する。ただし「キャッシュ検査を足すと必ず隔離が壊れる」は強すぎる。隔離プローブを維持した別の読み取り専用診断も設計できるため、「現行の必須診断範囲ではない」で十分。
- **doctor stdin例とWrite許可を直ちに必須修正にしない結論は許容。** stdin例の説明不足は残るが、READMEの注意書きと一時デバッグフックの代替案がある。判定ヘルパーのパスが見えることと、モデルがそのパスへ書けて判定を改変できることは別の証拠を要する。初回原票の提示だけでは後者を確定できない。
- **文書のみの未完了事項は分けて残す。** 配布README:77の費用比較の位置付け、設計の古いunittest例はコード欠陥ではないが、初回俯瞰票の課題は消えていない。特に費用比較の扱いは現行の配布READMEにも同じ文言が残る。今回の修正対象外と、偽陽性を区別する。
- **P2という優先度は妥当だが、理由は直すとよい。** ホスト権限の破壊はP1の必要条件ではない。発生条件・影響範囲・評価結果の誤りに基づいて優先度を説明する。G1の実ログで隔離判定が反転すること自体は修正を優先する根拠になる。

## 再現成果物と残すべき受け入れ条件

追加対照は [five-perspective-2026-09-13g-audit-repro.py](five-perspective-2026-09-13g-audit-repro.py) に保存した。`python3 -B reviews/five-perspective-2026-09-13g-audit-repro.py` で現在のコードを観測でき、第1引数にスナップショットのルートを渡すこともできる。スクリプトは比較結果を出力するもので、テストスイートの合格を返す判定器ではない。

1. 必須fixtureの一部欠測を `child_no_body` 成功としない。対応する別名から本文を得られる場合は過剰に失敗させない。
2. 複数resultでも必須usageの欠測を0に変換せず、観測不足として残す。
3. 同一API応答内の同じ引数を持つ別tool-useを両方計上し、同じイベントの再送だけを重複排除する。
4. 非0のCLI終了と本文判定の優先関係を仕様に明記し、F3をその契約に沿って最終分類する。

この3件の修正不足と仕様上の未決事項を残したまま、G1〜G5の全面解消とは報告しない。なお、元のg報告自体は修正方針を述べた文書であり、全修正・全検証の完了を宣言したものではない。
