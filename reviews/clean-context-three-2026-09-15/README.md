# クリーンコンテキスト・3観点レビューと偽陽性チェック

対象: HEAD `83a3602`（作業ツリーの汚れは `__pycache__` と `token-shunt.zip` のみ。無視）。実施日: 2026-09-15。

俯瞰・通常・敵対的を、会話を継承しない独立サブエージェントで起動した。`reviews/`・`docs/history/`・git 履歴は根拠に使わせず、現行ソース・仕様・テストと `/tmp` でのフック実行だけを見させた。統合担当（本会話）が候補を合算し、フック stdin・`grep_bounds.metadata_paths`・`sendback_retention` / `sendback_stop.decide` で再確認した。

実装ソースは変更していない。Claude の課金を伴う実機呼び出しは行っていない。

> 追記（2026-09-16）: P1 3 件はいずれも修正済みである。F1 は `8606aba`
> （`fix: only record a measurement the caller was actually shown`）、
> F2 は `bab1310`（`fix: read a line number in a citation as pointing into
> the file`）、F3 は `d296fcf`（`fix: judge the workers that reported, not
> none of them`）。本文は `83a3602` 時点の記述のまま残している。

個別報告: [overview.md](overview.md) / [normal.md](normal.md) / [adversarial.md](adversarial.md)

## 統合結果

独立候補は延べ 19 件（俯瞰 9・通常 4・敵対 6）。偽陽性チェックで 1 件を P1→P2、3 件を設計内／意図的として除外、重複 2 件を統合した。最終的に **P1 が 3 件、P2 が 10 件**。P0 はない。

| 観点 | 独立候補 | 統合先 |
|---|---:|---|
| 俯瞰 | 9 | F4, F6–F10（除外 3、降格 1） |
| 通常 | 4 | F5, F9, F10 |
| 敵対的 | 6 | F1–F3, F8, F11, 除外 1 |

### F1 — P1: `stat`/`wc -c` がサイズを告げなくても content Grep を許可する

視点: 敵対。統合側で再再現。

位置: `plugin/hooks/grep_bounds.py:43`（`_UNSAFE` に `#` が無い）、`:100-135`（`metadata_paths` は `stat -c` の次語を捨て、stdout を見ない）、`plugin/hooks/check-grep-bounds:119-134`。

- `stat -c %n <large>` は実 bash がパス名だけを出す。フックは large を測定済みにする。続く `output_mode=content` + `head_limit=5` は pass。
- `wc -c <small> # <large>` は実 bash が small だけ数える。`shlex.split` が `#` と large をオペランドにし、large の Grep が pass。

README は「拒否本文が実際にサイズを告げたパス」と「展開を含まない `wc -c` / `stat`」と書く。実装は「サイズを見た」ことを検証していない。第2規則（`head_limit` 1–20、`-A/-B/-C` 禁止）は残るので全文ダンプではない。スキルがサイズを見て委譲する前提は外れる。

### F2 — P1: `confirmed: /abs/path:行` を消失ファイル扱いし、保持違反を見逃す

視点: 敵対。統合側で再再現。

位置: `plugin/hooks/sendback_retention.py:35`（`_ABS` が `/[^\s...]+` で `:12` まで取り込む）、`:80-86`（末尾の `.,;:)` だけ削るので `:12` は残る）、`:112-124`（存在しないパスは UNDETERMINED）、`sendback_stop.py:296-298`（undetermined は block しない）。

実在ファイル `/tmp/.../large.txt` に対する `confirmed: <path>:12 — TOKEN is 42` は citation が `<path>:12` になり `exists` が偽、`SubagentStop` は `no_block` / `worker items undetermined`。親が行を落としても差し戻さない。行番号付きパスは LLM がよく書く形。

### F3 — P1: 取得不能な bulk-reader 起動が 1 件あると、成功ワーカーの drop も判定しない

視点: 敵対。コード照合で確定（`plugin/hooks/sendback_session.py:311-316`）。

`usable` があっても `blocked`（`text is None`）が 1 件なら `child_texts` は `None`。`sendback_stop.py:370-372` は `worker output unobtainable` で通す。失敗・未完了の reader が 1 つあると、完了済みワーカーの行保持が全部オフになる。README の「出力が取得できないときは通す」は、そのワーカーを除外する話としては妥当だが、実装は成功分まで捨てる。

### F4 — P2: 設計正本のフック登録・Grep 対象外が出荷と README と食い違う

視点: 俯瞰。P1 として報告されたが、インストーラ向け虚偽ではないので降格。

設計 §7 は 7 登録・5 スクリプト、§4 / §11.8 / §15 は Grep content を対象外、Stop フックは無い。実装と README は `check-grep-bounds` と `check-final-answer` を既定登録し、製品動作として説明する。挙動の正本は README＋`hooks.json`。設計が古い。

### F5 — P2: Grep 測定テストが製品配線を通していない / DENY_CAP 加算が `decide()` 事前セットだけ

視点: 通常。製品経路自体はレビュアーが stdin で確認済み。

- `test_a_read_deny_that_named_the_size_counts_as_measured` は `check-grep-bounds --sized` 直呼びで、`check-file-size` の `record_sized` 配線を見ない。
- DENY_CAP テストは `state['denials']=6` を置いて `decide()` する。加算は `check-grep-bounds.judge()` 側。加算を外してもこれらのテストは緑。

### F6 — P2: 配布 README が ZIP を「5 フック」のままにしている

視点: 俯瞰。`docs/distribution/README.md:13-31` は 5 本。`scripts/build-zip.sh` と `evals/test_build_zip.py` は 7 本（`check-grep-bounds` / `check-final-answer` を含む）。欠落したまま ZIP が出荷されるわけではない。名簿だけ古い。

### F7 — P2: 設計 §13 の `bash-pipe` は通過、実装カタログは deny

視点: 俯瞰。設計表 `:556` は `cat large | grep foo` を通過。同じ設計 §10 / §15 と `evals/bash-hook-evals.json:38-41` と README:231 は deny。設計書内部の矛盾。製品は deny。

### F8 — P2: Grep の `context` が実装済みの前後行禁止をすり抜ける

視点: 敵対。統合側で再再現。`-C: 5` は deny、`context: 5` は pass。Claude Code の Grep スキーマでは `context` が rg `-C` の本体。`head_limit` があるので無制限リークではない。README は `-A/-B/-C` だけ名指し。

### F9 — P2: SessionStart の Python 3 警告が Grep / Stop フックを言わない

視点: 俯瞰・通常。`check-jq:19-21` は bulk-reader Read だけ。`check-grep-bounds` と `check-final-answer` も python3 shebang で既定登録。README 依存不足節も Grep/Stop に触れていない。

### F10 — P2: スキル description が設計 §11 の「トリガーのみ」を超えている / テストコメントが「Grep はフックされていない」のまま

視点: 俯瞰・通常。description の手順化は実機 eval が要求する配置であり、短く直すと壊れる。記録するだけ。`evals/test_reader_call_contract.py:501-502` のコメントだけが実装前前提を残している。

### F11 — P2: 接頭辞の `Confirmed:` だけ変えた保持を改変として親を止める

視点: 敵対。収集は `line.lower().startswith("confirmed:")`、照合は `normalize` のみ（lower しない）。事実もパスも残しているのに `altered` → block。verbatim 方針の内側だが、収集と照合の大小無視が不一致。

## 偽陽性・設計内として除外した候補

| 候補 | 再確認と結論 |
|---|---|
| 比較 eval が sendback を切り `release_eligible` が差し戻しを見ない（俯瞰） | README:190 が「製品の既定とは逆」と明記。測定分離は意図。欠陥にしない。 |
| マーケットプレイスの "route"（俯瞰） | 出荷 `.claude-plugin/marketplace.json:13` は既に `recommend delegation`。古いのは設計スニペット側。出荷文面は README と一致。 |
| 設計 §2「モデル方針はスキル遵守」vs `check-agent-model`（俯瞰） | README:92-94 とコードは強制で一致。設計決定一覧が古い。F4 と同型の正本ドリフトに含める。 |
| deny 契約ブロブが「読むな」とパスを同一テキストに載せる（敵対） | テンプレ自身が `Never copy these instructions into it` を持つ。親が無視した場合の残リスクはあるが、新規のゲート欠陥ではない。 |
| 相対 Grep + cwd、writer を bulk-reader へ送る、`tool_input.agent_type` 偽装、directory/glob 未判定 | 敵対側が防がれる／設計内と確認。README とテストでカバー済み。再計上しない。 |
| `cat <file>` 等の既知 Bash 穴 | README 制限事項。新規にしない。 |

## 検証と限界

- F1 / F2 / F8 / F11 は統合担当が `/tmp/ts-fp-*` でフック stdin と retention API を再実行して確認した。
- F3 は `check_inputs` の `usable and not blocked else None` をソースで確定。フルセッション JSON の再構築はしていない。
- F4–F7, F9–F10 は静的照合。`evals/run.sh` と compare 372 件は本統合では再走していない（直前セッションで pass 126 / 372 OK を確認済み）。
- 有料のモデル実行、sendback 実機の block/resume、python3 欠落時の CLI fail-open/closed は未実施。

修正の優先順は F1（測定の偽記録）→ F2（`:行` の見逃し）→ F3（失敗起動による保持オフ）→ F8（`context`）→ 文書 F4/F6/F7/F9。F10 の description 短縮と F11 の大小無視は、実機 eval / verbatim 方針とぶつかるので先に直さない。
