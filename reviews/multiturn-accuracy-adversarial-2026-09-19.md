# Spec 敵対的レビュー

対象: `/home/dev/projects/skills/token-shunt/docs/superpowers/specs/2026-09-19-multiturn-accuracy-design.md`
日付: 2026-09-19

読み取り確認: Spec の節 4 個 / 名指しされた既存ファイル・識別子 11 件
（うち確認済み 11）。アーカイブ transcript の実体を 3 本開いて照合した
（`run.2gXhO3lK` の direct t2 / auto t2 / auto t3）。

## Critical

なし。「記録のみ」は現行コード構造で守れる（verdict 確定後の追記で、
aggregate・`report_summary` は `.turns` を読まない）。verdict に逆流する
経路は spec の書き方からは生えない。

## Major

### A1. 契約違反込みの accuracy は、§6-1 の問いに対して結論を裏返しうる
- 場所: §1.1 表「経路契約 — 判定しない」/ §2.3「direct と auto の差。
  委譲した腕の後続ターンの答えが薄いかどうか」
- 暗黙の前提: turn の `final` に gold が並ぶとき、その内容は
  **製品の契約内で**届いた答えである。
- 失敗シナリオ: auto の worker が turn 2 で 4,000 字上限を超える返答
  （アーカイブ turn 1 で実測 5/14、最大 10,642 字）を返す。親はその
  長い返答から gold を拾って最終回答に載せ、`judge_turn` は
  `{missing: []}` を記録する。一方 direct が同じ問いに短い答えを返せば
  missing が出る。**観測されるのは「auto のほうが答えが厚い」で、
  その厚さは製品自身の契約違反でできている。**
  §6-1 の「片腕が薄い答えで安く済ませた可能性」に「薄くない」と
  答える数字が、薄くない理由を区別できない。
- 根拠: `judge_turn` の返りは `{turn, gold, missing}` だけ。
  worker 返答長・`child_msg_cap`・`child_no_body` 相当の文脈は
  `Transcript` に既に載っているのに記録しない設計になっている。
- 提案: 記録に worker 返答の文字数（または cap 超過フラグ）を足す。
  verdict に使わないので §1.1 の境界は壊れない。足さないなら
  「auto ≧ direct は『委譲が品質を保つ』と『worker が答えすぎる』を
  分けない」を §2.3 の「答えないこと」に書く。

### A2. 形として正しいが実在 turn に結びつかない gold が黙って腐る
- 場所: §2.1 の検証「キーが数字文字列、値が非空文字列の非空リスト」
- 暗黙の前提: 数字文字列のキーは実在する follow-up turn を指す。
- 失敗シナリオ: spec 作者が `"4"` と書くべきところを `"5"` や `"04"` と
  書く。形検証は通り、`judge()` と `aggregate()` の両方を素通りし、
  `.turns[]` の記録は turn 2〜5 全部揃った**完全に健康そうな形**で出る。
  宣言した gold はどこにも現れず、誰も欠けに気づかない。
  `spec_evidence_error` が生まれた理由はまさにこの種の
  「宣言したのに証拠にならない」で、形だけの検証はそれを防がない。
- 提案: キー ∈ {2..|prompt_turns|+1} を検証に足す。
  `prompt_turns` 非宣言 + `gold_turns` 宣言の組み合わせもエラーにする。

## Minor

### A3. `.turns[]` が verdict ファイルに乗るなら rejudge で黙って消える
- 場所: §1.2「`run.sh` が `.turns[]` として別フィールドに足す」
- 暗黙の前提: verdict JSON は run.sh が追記してよい安定した記録面である。
- 失敗シナリオ: verdict JSON は judge.py の成果物でもあり、手動 rejudge
  （`live-rerun-rejudge-2026-09-14.json` の系の作業）が transcript から
  verdict を再生成すると `.turns` だけが静かに失われる。verdict 側は
  再現できるが `.turns` は run.sh のコンテキストが要るので復元できない。
- 提案: 足し先を verdict JSON と明記し、「rejudge は `.turns` を
  再生成しない／落とす」を一文書くか、兄弟ファイル
  （`<id>.<mode>.turns.json`）に分けて aggregate 経由で運ばせる。

### A4. turn ファイル欠落は `error` でも `missing` でもなく、記録が生えない
- 場所: §1.3
- 失敗シナリオ: resume 失敗・`--resume` の sid 不整合で `.turnN.jsonl` が
  存在しない。走査がファイル起点ならその turn は記録に**存在せず**、
  「採点しなかった」と「採点できなかった」の区別を付ける設計のはずが
  第 4 の状態（存在しない）を黙って落とす。
  アーカイブは 140/140 完備なので現 data では不発。将来の run で効く。
- 提案: 走査元を `prompt_turns` の宣言件数にすれば
  「ファイル無し → `{turn, error:"missing transcript"}`」が一意に決まる。

### A5. 盲検の主張は半分しか機械的に検証できない
- 場所: §2.2「まだ 1 本の transcript も見ていない」/ §2.4
- 暗黙の前提: 行番号つき出典があれば「実行結果を見ずに決めた」が担保される。
- 検討: 出典の検証は**gold の由来がソースであること**を確かめるだけで、
  「回答を見てから gold を選んだ」可能性は排除しない —— 除外は
  自己申告である。さらに字義どおりには、同日の §4-2 訂正が
  アーカイブの turn transcript を `parent_turn_reads.py` に通しているので
  「1 本も見ていない」は強すぎる（secondary S1）。
- 提案: 主張を「turn の最終回答テキストを見ていない」に絞り、
  gold commit の SHA を `note` に残す。それで順序の主張は
  `git log` で第三者が確かめられる形になる。

### A6. `is_error` / 未完了の turn は「全 missing」として薄い答えと見分けがつかない
- 場所: §1.3 の `{turn, error}` / `{turn, gold, missing}` の 2 値
- 失敗シナリオ: turn が途中落ち（timeout・is_error）で `result` が無い、
  または `final_text()` が親の最終 assistant テキストへフォールバックして
  不完全な文を拾う。記録は `{missing: [全部]}` になり、
  「答えが薄かった」と「ターンが壊れていた」が同じ見た目になる。
  §1.3 が分けると決めた区別の第 3 状態である。
- 提案: 記録に `completed`/`is_error` を足す（turn completion は
  multiturn-context-design §2.3 で既に別計器があるので、足さない判断を
  取るならその一文を書く）。

### A7. アーカイブ適用の走査規約が無名のままだと turn 番号がずれうる
- 場所: §2.3（アーカイブ検証）/ §1.1（run.sh での turn ごと呼び出し）
- 失敗シナリオ: tarball を展開して turn ファイルを順に当てる際、
  独自の列挙（glob の辞書順など）を書くと `.turn10` 等で順序が壊れるか、
  turn 番号とファイル名の対応をファイル名由来以外で推測する。
  `parent_turn_reads.turn_files`（正規表現 `\.turn(\d+)\.jsonl`＋数値ソート）
  が既に規約を持っているのに、spec は再利用を名指していない。
- 提案: アーカイブ適用は `turn_files` 規約を使うと一行書く。

## 検討したが問題なしと判断した箇所

- **「新しい採点器を書かない」との衝突。** 規則の由来（judge と食い違う
  自作スキャナ、denied Read の突破計上）に対し、`judge_turn` は同じ
  `Transcript`/`load_events`/`final_text`/`g in final` を使うので
  同じ入力に違う判定を返す経路が生えない。spec §0 の切り分けは成立。
- **`final` への worker 本文混入。** `--forward-subagent-text` 付きでも
  `final_text()` は `parent_tool_use_id is None` の親テキストだけを返す
  （judge.py:408-410）。実アーカイブの auto turn 2/3 でも result 文に
  worker の生返答ではなく親の統合回答が入っていた。
- **`.turns` の verdict への逆流。** verdict は run.sh:772-780 で確定し、
  `aggregate()` は `.verdict`/`.reasons`/identity しか見ない。
  `spec_evidence_error` の gold_turns 検証が fail するのは spec 不正の
  場合だけで、記録の存在で合否が動く経路は無い。§1.2 は成立。
- **「turn 3〜4 で跨ぐ」。** CSV では turn 3 終了時点 23,392 B で跨ぎ、
  Lock B の構造（跨いだ読み取りは通る）上 deny が効くのは turn 4。
  「3〜4」は跨ぎと発火の両方を含む書き方で、誤りではない。
- **turn 5 不採点。** design:83 の「新しい path を出さず総合を要する」に
  対し、部分文字列一致が恣意的になるのは事実。`scored:false` の明示は
  緩い gold を作るより正直で、spec の言い分は筋が通る。
- **`spec_evidence_error` 拡張の副作用。** 既存の `gold_file`/`require_parent_tokens`
  検査と同じ入口なので、`gold_turns` 非宣言ケースは no-op。A/B 必須ケースに
  影響しない。
- **direct 腕にも `judge_turn` が掛かること。** `run_followups` は両腕で
  呼ばれる（run.sh:802-806）ので §2.3 の「direct と auto の差」は機構上
  取れる。direct の gold 一致率が天井に近いのは想定どおりで、
  差の解釈側の話であって機構の欠陥ではない。
- **`error` レコードの形。** `{turn, error}` / `{turn, gold, missing}` /
  `{turn:N, scored:false}` の 3 形混在は JSON 処理上は許容。
  揃えるなら `scored` フラグを全要素に持たせる設計もあるが、
  記録のみの用途では過剰。挙げない。
