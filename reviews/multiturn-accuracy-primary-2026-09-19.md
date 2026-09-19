# Spec レビュー（一次 — 内部整合性・実装可能性）

対象: `/home/dev/projects/skills/token-shunt/docs/superpowers/specs/2026-09-19-multiturn-accuracy-design.md`
日付: 2026-09-19

読み取り確認: Spec の節 4 個（0〜3）/ 名指しされた既存ファイル・識別子 11 件（うち確認済み 11）

開いたパス:
- `evals/compare/judge.py`（`Transcript` L237, `load_events` L115, `final_text` L404, gold 判定 L1284-1298, `spec_evidence_error` L56, `judge()` L1193, `aggregate()` L2219）
- `evals/compare/run.sh`（spec 書き出し L748、judge 呼び出し L772、`run_followups` L420-437・呼び出し L800-806、aggregate L813）
- `evals/compare/cases.json`（`prompt_turns` 保持ケース 2 件）
- `evals/compare/parent_turn_reads.py`（`turn_files` L35）
- `evals/compare/routing_checks.py`（`unreadable_line_partial` L478）
- `docs/superpowers/specs/2026-09-19-cumulative-intake-design.md`（§5.4）
- `reviews/multiturn-context-2026-09-18.md`（§4-2, §6-1, §7）
- `reviews/multiturn-context-design-2026-09-18.md`（§2.3）
- `reviews/cap-overflow-2026-09-19.md` / `reviews/cap-overflow-design-2026-09-18.md`

## Critical

なし。機構の骨格（`judge()` 不変・`judge_turn` は accuracy のみ・verdict 非接触）は
実装可能で、§1.2 の「合否判定コードを一切通らない」は現行コード構造上成立する
（verdict は `run.sh:772` で確定済み、aggregate は `.turns` を読まない）。

## Major

### M1. turn 2 の gold 対が部分文字列包含で潰れ、`missing` が属性半分を検出できない
- 場所: §2.1 `gold_turns` 例 / §2.4 gold 表 turn 2 / §2.3「偽陽性側に緩い」
- 問題: `gold` 判定は `g in final` の部分文字列一致（judge.py:1289）。宣言された
  `"reversible"` は `"IrreversibleError"` の部分文字列である
  （`"reversible" in "IrreversibleError"` → True、実評価済み）。
  例外名だけを答えて検査属性に触れなかった回答も `missing=[]` で通る ——
  **turn 2 の設問は 2 項を聞いているのに、採点できるのは実質 1 項である。**
- 根拠: §2.3 は「`reversible` は散文にも現れうるので、偽陽性側に緩い」と
  散文での出現だけを織り込んでおり、**他方の gold に包含される消滅**は
  カバーしていない。緩いのではなく冗長である。
- 提案: 包含されない gold に換える。`operation.reversible` は
  `migration.py:158` の原文そのまま（出典性は保たれる）で、実アーカイブの
  turn 2 回答にも verbatim で出た。緩さを残すなら、turn 2 は
  実効 gold 1 個であることを §2.3 に明記する。

### M2. `gold_turns` の形検証がキーの範囲を見ず、宣言された gold が黙って採点されない経路がある
- 場所: §2.1「`spec_evidence_error` に形の検証を足す（キーが数字文字列、
  値が非空文字列の非空リスト）」
- 問題: 宣言どおりの検証は `"1"`（turn 1 の `gold` と意味衝突）、
  `"6"`（`prompt_turns` が 4 件なら実在しない turn）、`"02"` や `"+2"`
  をすべて通す。`run.sh` は実在する follow-up transcript（`.turnN.jsonl`、
  N≥2）にしか `judge_turn` を呼べないので、これらのキーの gold は
  **形は正しいが永遠に採点されず、記録にも欠落が現れない**。
  `spec_evidence_error` が防ぐべき「宣言したのに証拠にならない」
  そのものである。
- 根拠: `spec_evidence_error` は `judge()`（L1195）と `aggregate()`
  （L2288）の両方で走る。形の違反は fail になるが、範囲外キーは
  両方を素通りする。
- 提案: 検証にキー ∈ {2..|prompt_turns|+1} と `prompt_turns` 非空を足す。
  `gold_turns` を持つケースに `prompt_turns` が無い組み合わせも同時に塞ぐ。

### M3. 記録を生む走査の契約が無く、§1.4 の `{turn:5, scored:false}` が実装依存で消えうる
- 場所: §1.1「`run.sh` が `run_followups` の後に turn ごとに呼ぶ」/ §1.4
- 問題: turn 5 に `{turn:5, scored:false}` が残るのは、走査が
  **宣言された `prompt_turns`（または実在する turn ファイル）**を回る場合だけ。
  `gold_turns` のキーを回す実装だと §2.1「キーが無い＝採点しない」と整合するが
  §1.4 の記録は一切書かれない —— 本文中のどちらの読み方も実装できる。
  さらに未規定が 2 点: **turn ファイル自体が無い場合**（resume 失敗。
  §1.3 は「ファイルがあるのに作れない」だけを扱う）、および
  **`prompt_turns` はあるが `gold_turns` が無いケース**
  （`reader-followup-scope`）で `judge_turn` を呼ぶかどうか。
- 根拠: `parent_turn_reads.turn_files`（L35-51）は turn ファイル走査の
  既存規約（turn 1 基準、番号ソート）を持つ。`run.sh` は
  `prompt_turns` の件数を `run_followups` で既に回している（L432-436）。
- 提案: 走査元を一文で固定する（推奨: `prompt_turns` の宣言件数。
  turn ファイル欠落は `{turn:N, error:"missing transcript"}`）。
  `gold_turns` 非宣言ケースでの呼び出し可否も書く ——
  「採点していないことを明示的に記録する」なら `scored:false` が
  そこにも要るかどうかを決める。

## Minor

- `.turns[]` の足し先が「別フィールド」とだけある。verdict JSON（`$VRD/<id>.<mode>.json`）
  なら aggregate が `v` を丸ごと summary へ運ぶ（judge.py:2307）ので
  last-run.json に届くが、judge.py が verdict を再生成する手動 rejudge
  （`live-rerun-rejudge-2026-09-14.json` の系）では黙って消える。
  置き場所と再採点時の扱いを一文書く。
- `judge_turn` の置き場所が書かれていない。「判定ロジックを 1 本に保つ」は
  `judge.py` 内の関数（`Transcript`/`load_events`/`final_text` を import せず
  同居）を意味するはずで、別ファイルに置くとその約束が構造で保てない。
- `{turn, gold, missing}` に turn の完了情報が無い。`result.is_error` や
  `result` 行欠落の turn は「全 gold missing」になり、「答えられなかった」
  と「採点できなかった」を分けるという §1.3 の区別の第 3 状態が潜る。
  （multiturn-context-design §2.3 が turn completion を別途数えているので
  実害は限定的。）
- §1.1 の表で turn 1 の「親の corpus Read」が「—」。`parent_turn_reads.py` は
  turn 1 も測る（実測 0 件を出したのは同計器）。「測れる（同計器）」か
  「`parent_no_read` が判定済み」が正しい。
- アンカー「run.sh:799-806」: `run_followups` 呼び出しは 803/805、
  ブロックは 800-806。799 は直前 `fi`。位置特定としては機能するが
  厳密には 800-806。
- `gold_any` 相当（いずれか 1 語で足りる turn）は形に無い。現 3 ターンは
  AND で足りるので問題ではない。将来用に一言あってもよい。

## Spec カバレッジ

| Spec の要件 | 実装する機構 | 状態 |
|---|---|---|
| `judge()` を変えない（§1.1） | `judge_turn` 新規関数 | 可能 |
| accuracy のみ、経路契約は判定しない（§1.1） | `g in final` のみ再利用 | 可能（M1 の実効 gold に注意） |
| verdict 非接触・記録のみ（§1.2） | `run.sh` が `.turns[]` 追記 | 可能。置き場所未固定（Minor） |
| 欠測と誤答を分ける（§1.3） | `{turn,error}` vs `{turn,gold,missing}` | ファイル欠落が未規定（M3） |
| turn 5 は採点しない、記録は残す（§1.4） | `scored:false` | 走査元未定（M3） |
| `gold_turns` 形検証（§2.1） | `spec_evidence_error` 拡張 | 範囲検証なし（M2） |
| gold → TDD → アーカイブの順（§2.2） | 手続き | 可能（順序遵守は運用） |
| アーカイブ検証 $0（§2.3） | tarball 上の `judge_turn` | 走査ドライバ未記名（Minor） |
| gold 出典を `note` に（§2.4） | `cases.json` の `note` | 可能 |
