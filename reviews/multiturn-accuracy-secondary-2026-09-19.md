# Spec レビュー（二次 — コード・コーパス・アーカイブとの照合）

対象: `/home/dev/projects/skills/token-shunt/docs/superpowers/specs/2026-09-19-multiturn-accuracy-design.md`
日付: 2026-09-19
役割: 2次（spec が名指しした実体・数値・引用が実在するかを検算）

開いたパス・確認した実体:
- `evals/compare/judge.py` / `evals/compare/run.sh` / `evals/compare/cases.json` /
  `evals/compare/parent_turn_reads.py` / `evals/compare/routing_checks.py`
- `~/measurements/token-shunt/multiturn-context-2026-09-18-transcripts.tar.gz`
- `~/corpora/django`（`bc833e8883db4a333a6485d91637b78c85e2b13b`、
  `django/__init__.py: VERSION = (5, 2, 1, "final", 0)`）
- `reviews/data/multiturn-context-2026-09-18-turns.csv`
- `reviews/multiturn-context-2026-09-18.md` / `reviews/multiturn-context-design-2026-09-18.md`
- `reviews/cap-overflow-2026-09-19.md` / `reviews/cap-overflow-design-2026-09-18.md`
- `docs/2026-09-12-token-shunt-design.md`（§26.5）
- `docs/superpowers/specs/2026-09-19-cumulative-intake-design.md`

## 検証できた（spec の記述どおり）

- **アーカイブの存在と同一性。** tarball の sha256 は
  `44ff1aea…370135` で spec §2.3 とレビュー §7 の記録に一致。
  `django-multiturn-context` の transcript は 140 本（28 会話 × 5 ファイル、
  turn 2〜5 の `.turnN.jsonl` を含む。残り 28 本は `_probe_iso`/`_probe_load`）。
- **gold の出典が全部実在する。** `migration.py:158` が
  `if not operation.reversible:`、`:159` が `raise IrreversibleError(`。
  `writer.py:298` `MIGRATION_HEADER_TEMPLATE`、`:304` `MIGRATION_TEMPLATE`、
  `:129` `def as_string`。`special.py:97-98` が
  `def reversible → return self.reverse_sql is not None`、`:138` `class RunPython`、
  `:144` `reduces_to_sql = False`。コミット `bc833e8`、VERSION = 5.2.1。
- **判定の再利用先が実在する。** `Transcript`（judge.py:237）、
  `load_events`（:115）、`final_text`（:404）。gold 判定は
  `[g for g in gold if g not in final]`（:1289）で、文字どおり部分文字列一致。
- **`run.sh` の挿入位置が実在する。** spec は `$SPD/<id>.<mode>.json` に
  L748 で書かれ、judge は L772 で turn 1 transcript だけを採点し、
  `run_followups` は L803/805（コメント L800-801 が「judge.py reads one
  transcript per case (design 5.1)」を裏付ける）。呼び出しは両腕にある
  （direct は `--plugin-dir` なし）ので direct/auto 比較は機構上可能。
- **「合否判定コードを一切通らない」が構造で保てる。** verdict は
  `judge()` が書き切った後に `run_followups` が走る。`aggregate()` は
  verdict を `c["modes"][mode] = v` で丸ごと summary に運ぶ（:2307）ので
  `.turns` は邪魔にならず `last-run.json` に届く。`report_summary`
  （run.sh:38-49）は `.verdict`/`.reasons` しか読まない。
  `spec_evidence_error` は :56 に実在し judge と aggregate の両方で呼ばれる。
- **§1.2 の母集団記述が正しい。** `prompt_turns` を持つのは
  `reader-followup-scope`（suite X、2 turn）と `django-multiturn-context`
  （suite X、4 turn）だけで、`EXPERIMENT_SUITE="X"` は `mandatory` から
  除外される（judge.py:2265-2266）。「A / B の必須スイートに入っていない」通り。
- **閾値の跨ぎ方が CSV と一致する。** `run.2gXhO3lK`（auto）だけが
  累積 32,098 B で、turn 3 終了時点 23,392 B で 16,384 を跨ぐ。
  Lock B は跨いだ読み取り自体を通す設計なので deny が効くのは turn 4 の
  8,706 B。「跨ぐのは turn 3〜4」は許容範囲の書き方。
- **cap-overflow の引用が正しい。** 「両腕 39/39 pass、失敗 0。`gold` 3 語は
  毎回揃っている」（cap-overflow-2026-09-19.md:106）、§6-1 の仮説
  「上限を守らせたら答えが痩せた」（同 design:122）、§6.5
  「指標は、表を見た後に選んだ」（同:240）。
- **§26.5 の引用が正しい。** 「ゴールド正答や安い費用で経路違反を相殺しない」
  （design:985）、「必須親トークン測定」（design:754-755, 1004）。
- **resume transcript の形が利用前提を満たす。** multiturn-context-design:102
  「`--resume` の transcript にはその turn の event しか入らない」通り、
  実アーカイブの `.turn2.jsonl` は init+result を持ち `is_error: false`。
  `final_text()` がその turn の回答を返す。`--forward-subagent-text` の
  子テキストは `parent_tool_use_id` で除かれるので `final` に混入しない。
- **`unsupported` はこのケースで不発。** `unreadable_line_partial` は
  `expect.allow_unreadable_line_partial` を要求するが本ケースの `expect` に
  無いので、`g in final` が accuracy 経路の全部である。「同じ判定」は
  このケースでは正確に成り立つ。

## Major

### S1. 「まだ 1 本の transcript も見ていない」はリポジトリ自身の記録で反証できる
- 場所: §2.2 手順 1 の直前
- 問題: この文は盲検の核心なのに、字義どおりには成立しない。2026-09-19 の
  §4-2 訂正は `parent_turn_reads.py` を**アーカイブの turn transcript に
  掛けて**出た数字であり、同日に turn ファイルは計器に読まれている。
  「turn の回答文を見ていない」は成り立ちうるが
  「1 本の transcript も見ていない」は読み方次第で偽になる。
- 根拠: `reviews/multiturn-context-2026-09-18.md` §4-2 の訂正の訂正は
  「`parent_turn_reads.py`（成功した Read だけ数える）」を計器と明記し、
  §7 は transcript アーカイブを sha256 つきで残したと書く。
- 提案: 「gold を決めるまで turn の**最終回答テキスト**を見ていない」に
  絞る。Read イベントの集計は gold 調整の経路にならないので実質の主張は
  保たれ、敵対的な読み手が字義で崩せる文が消える。gold commit の SHA を
  §2.4 の `note` に残せば順序主張も機械的に確かめられる。

## Minor

- §2.1「既存の `gold` / `gold_any` と同じ判定にかけるだけ」は本ケースでは
  正確だが、judge() の accuracy は厳密には `missing` に加えて
  `unsupported` 抑止と `gold_confirmed` を含む（judge.py:1286-1314）。
  `judge_turn` が `g in final` だけを再利用するなら、
  「unsupported 抑止を持たない素の missing 判定」と明記したほうが、
  将来 `allow_unreadable_line_partial` を持つケースに `gold_turns` が
  乗ったときの静かな意味ずれを防げる。
- spec が引く「設計 §5.1」は `docs/2026-09-12-token-shunt-design.md` §5
  （:918「`judge.py` は 1 ケース 1 transcript しか」）で、`run.sh:801` と
  `parent_turn_reads.py` docstring の「design 5.1」と同じ略称。正しいが、
  §5.4 の引用元（cumulative-intake spec）と「設計」の指す文書が同じ節番号で
  2 文書にまたがるので、初読ではどちらか紛らわしい。
- `judge.py` の CLI（L2419-2434: `--selftest`/`--leakcheck`/`--aggregate`/
  単発判定）は `--turn` 相当の入口を足す自然な場所がある。spec が
  `judge_turn(transcript_path, spec, turn)` とシグネチャまで書いているので
  入口形だけ一行あると実装者の選択肢が減る。

## 確認したが spec 側に非が無い点

- 「turn 5 は採点しない」は multiturn-context-design:83（「turn 5 だけは
  新しい path を出さず、turn 1 と turn 4 の内容を要する」）と整合し、
  総合問題を部分文字列で採点しない判断は妥当。
- 「Lock B の影響は測れない。アーカイブは Lock B 以前の実行」は
  cumulative-intake spec が実装前であることと整合（同書 §6-1, §6-2）。
- 「これは Lock B を測る器具ではない」（§3-4）と §2.3 の
  「ベースラインであって比較ではない」は内部で矛盾しない。
