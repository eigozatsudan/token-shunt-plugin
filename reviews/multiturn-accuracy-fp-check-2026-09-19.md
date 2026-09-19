# 偽陽性チェック — multiturn-accuracy spec 3 レビュー

対象: `reviews/multiturn-accuracy-{primary,secondary,adversarial}-2026-09-19.md`
日付: 2026-09-19
方法: 各所見を、根拠としたコード・データ・文書に対して再現確認する。
「真」= そのまま残す。「条件つき」= 事実だが範囲・強度を限定して残す。

## 所見の再検証

### 一次 M1 — turn 2 の gold 対が包含で潰れる → **真（潜在）**
- 再現: `python3 -c "print('reversible' in 'IrreversibleError')"` → **True**。
  judge.py:1289 の判定が `[g for g in gold if g not in final]` の素の
  部分文字列一致であることも確認済み。
- 限定: 実アーカイブ `run.2gXhO3lK` auto turn 2 の回答は `reversible` を
  独立語でも含む（「whose **`reversible`** attribute is falsy」）ので、
  本 data では記録値は変わらない。**計器が属性欠落を検出できない**
  という構造的欠陥であり、今回の数字への実害はない。Major のまま残す。
- 修正案の検算: `operation.reversible` は `migration.py:158` の原文で、
  実回答にも verbatim で出る。ただし「the `reversible` attribute」とだけ
  書く正答を落とすので、厳しさとのトレードオフ。代替「実効 gold 1 個と
  明記」も併記した。

### 一次 M2 / 敵対 A2 — gold_turns のキー範囲が未検証 → **真**
- 再現: spec の検証文は「キーが数字文字列、値が非空文字列の非空リスト」。
  `isdigit` でも `^\d+$` でも `"1"`・`"6"`・`"02"` は通る。
  `run.sh` が呼べるのは実在する `.turnN.jsonl`（N≥2、`prompt_turns`
  由来）だけなので、これらのキーは採点経路を持たない。
  `spec_evidence_error` は judge.py:1195・2288 で両方走るが、
  範囲外キーは両方を素通りする —— 確認済み。
- 限定: `"+2"`・`"2.0"`・空白混入は数字文字列判定で弾かれる。
  残るのは「範囲外だが数字」系だけ。所見はその範囲に限定済み。

### 一次 M3 / 敵対 A4 — 走査契約とファイル欠落が未規定 → **真**
- 再現: spec 本文で走査元を指定する文は無い。
  `{turn:5, scored:false}` が書かれるのは `prompt_turns` 宣言数または
  実在ファイルを回る実装だけ。`run.sh:432-436` は `prompt_turns` の
  JSON 配列を index で回している（既存の走査規約は宣言件数）。
  §1.3 の記述は「turn ファイルがあるのに Transcript が作れない場合」のみ。

### 敵対 A1 — 契約違反込み accuracy の交絡 → **真（解釈側の欠陥）**
- 再現: `judge_turn` の返りは spec 上 `{turn, gold, missing}` のみ。
  follow-up turn の worker 返答長・cap 超過を記録する機構は
  現行コード・spec 双方に無い。契約違反の実在は
  `reviews/multiturn-context-2026-09-18.md` §4-2（5/14、最大 10,642 字
  vs 上限 4,000 字）で確認済み —— ただし同記録は **turn 1** の verdict
  であり、follow-up で cap 超過が実際に起きたかは未検証。
  スポットチェックした `run.2gXhO3lK` の auto turn 2/3 では親レベルの
  Agent 呼び出し自体が無く（親が自読した会話）、交絡は経路依存。
- 限定: 「数字が間違う」ではなく「同じ数字が 2 説を分けない」。
  spec の目的文（§6-1 の穴に数字を入れる）に対する適合性の指摘で、
  機構の誤動作ではない。Major 維持、表現は「分離不能」に限定。

### 二次 S1 / 敵対 A5 — 「1 本の transcript も見ていない」は強すぎ → **真（文言）**
- 再現: `reviews/multiturn-context-2026-09-18.md` §4-2 の訂正の訂正は
  `parent_turn_reads.py` を計器と明記し、その対象はアーカイブの
  turn transcript（§7 の tarball）。2026-09-19 時点で turn ファイルは
  計器に読まれている。ただし読まれたのは Read イベントであって
  最終回答テキストではない。
- 判定: 「回答文を見ていない」は恐らく真、「transcript を見ていない」は
  字義で偽。盲検の実質（gold が実行結果由来でないこと）は
  §2.4 の出典で担保されており、文言の問題として残す。Major から
  文言の指摘としては妥当（盲検節の中心文が反証可能なのは重大）。

### 敵対 A3 — verdict ファイルへの追記は rejudge で消える → **真（条件つき）**
- 再現: verdict JSON は judge.py が全体を書き換える成果物
  （run.sh:772-780）。rejudge の実例 `live-rerun-rejudge-2026-09-14.json`
  が reviews に存在する。
- 条件: `.turns` が verdict JSON に乗る場合に限り発生。spec が足し先を
  決めていないので現時点では潜在的。Minor 妥当。

### 敵対 A6 — 未完了 turn が全 missing に見える → **真（条件つき）**
- 再現: `final_text()`（judge.py:404-410）は `result.result` が無ければ
  親の最終 assistant テキストへ落ちる。`result` 行自体が無い turn は
  Transcript 構築には成功しうるが `final` は不完全になりうる。
- 条件: アーカイブは 140/140 完了で不発。turn completion は
  multiturn-context-design §2.3 の別計器が既に見ている。
  Minor 妥当。

### 敵対 A7 — アーカイブ適用の走査規約が無名 → **真（軽微）**
- 再現: `parent_turn_reads.turn_files`（L32-51）が
  `<case>.<mode>.jsonl[.turn<N>.jsonl]` の命名規約と数値ソートを
  実装済み。spec は再利用を名指していない。Minor 妥当。

### 二次 Minor — `unsupported`/`gold_confirmed` の省略 → **真（潜在）**
- 再現: 本ケースの `expect` に `allow_unreadable_line_partial` と
  `gold_confirmed` は無く、judge.py:1286-1314 で両者は不発。
  「同じ判定」は**このケースでは**正確。`prompt_turns` 保持の 2 ケース
  とも該当フィールド無し（cases.json 全件確認）。将来ケースのみで
  意味がずれる。Minor 妥当。

### 一次 Minor 群 → **真**
- `.turns` 足し先未指定 / `judge_turn` の置き場所未明記 /
  §1.1 表の turn 1「—」セル（`parent_turn_reads` は turn 1 を計測済み、
  docstring が「0 parent corpus Reads at turn 1」と証言）/
  アンカー 799-806（呼び出し本体は 803/805）— すべて確認済み。

## 棄却した候補（偽陽性）

- **「run.sh:799-806 は誤り」→ 棄却。** 呼び出し本体は 803/805 だが
  spec は「`run_followups` の後…の位置に呼ぶ」であって範囲指定ではない。
  位置特定として機能する。Minor の書き方（「厳密には 800-806」）に留めた。
- **「turn 3〜4 で跨ぐは誤り」→ 棄却。** CSV で turn 3 末 23,392 B で跨ぎ、
  Lock B の構造上 deny が効くのは turn 4。「3〜4」は両時点を含む表現。
- **「judge_turn は新しい採点器で規則違反」→ 棄却。** 規則の由来は
  judge と食い違う別判定。同じ `Transcript`/`g in final` を使うので
  同一入力に異判定は生えない。§0 の切り分けどおり。
- **「`.turns` が verdict に逆流する」→ 棄却。** aggregate は
  `.verdict`/`.reasons`/identity のみ、report_summary も同じ。
  `spec_evidence_error` の gold_turns 検証が効くのは spec 不正時のみ。
- **「`--forward-subagent-text` が worker 本文を `final` に混ぜる」→ 棄却。**
  `final_text()` は `parent_tool_use_id is None` で除外（judge.py:408-410）。
  実アーカイブの auto turn でも result は親の統合文。
- **「gold 出典の行番号がずれている」→ 棄却。** 7 か所すべて実測で一致
  （writer.py:129/298/304、migration.py:158-159、special.py:97-98/138/144）。
- **「アーカイブが無い・数が合わない」→ 棄却。** sha256 一致、
  multiturn-context の transcript は 140 本ちょうど。
- **「suite X は必須スイートに混入する」→ 棄却。** `EXPERIMENT_SUITE`
  は `mandatory` から除外（judge.py:2265-2266）。必須表にも不入。
- **「`unsupported` で本ケースの判定が変わる」→ 棄却。** 本ケースでは
  常に False（`allow_unreadable_line_partial` 非宣言）。

## 残った所見のまとめ

- **Major 4 件:** 一次 M1（gold 包含潰れ・潜在）、M2=A2（キー範囲未検証）、
  敵対 A1（契約違反との分離不能）、二次 S1=A5（盲検の文言）。
- **Major 相当 1 件:** 一次 M3=A4（走査契約・ファイル欠落・非宣言ケースの
  扱いが未規定）。
- **Minor:** `.turns` 足し先と rejudge、`judge_turn` の置き場所、
  未完了 turn の見た目、走査規約の無名、§1.1 表の「—」セル、
  「設計 §5.1」の 2 文書またぎ、`unsupported`/`gold_confirmed` 省略、
  アンカー 799-806、`gold_any` 相当の欠如。

## 承認前に直すべき最小限

1. turn 2 の `reversible` を包含されない gold に換えるか、
   「実効 gold 1 個」と §2.3 に明記。
2. `gold_turns` 検証にキー範囲（{2..|prompt_turns|+1}）と
   `prompt_turns` 必須を足す。
3. 走査元（`prompt_turns` 宣言数推奨）・ファイル欠落時の記録・
   非宣言ケースでの呼び出し可否を一文ずつ。
4. §2.2 の盲検文を「turn の最終回答テキストを見ていない」に絞る。
5. `.turns[]` の足し先と rejudge 時の扱いを一文。
6. （A1）worker 返答長または cap 超過フラグを記録に足すか、
   分離不能であることを §2.3「答えないこと」に書く。
