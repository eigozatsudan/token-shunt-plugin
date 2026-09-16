# 俯瞰・設計整合性レビュー（クリーンコンテキスト）

実施日: 2026-09-15。会話非継承。reviews/・git履歴は根拠にしない。ソース変更なし。

対象は README、`docs/2026-09-12-token-shunt-design.md`、マニフェスト、`plugin/hooks/hooks.json`、フックスクリプト、両 SKILL.md、両 agent md、`scripts/doctor.sh`、`scripts/build-zip.sh`、`evals/run.sh`、`evals/compare/{run.sh,cases.json,judge.py,routing_checks.py}`。既知の README / 設計 §15 限界（`cat <file>`、sed、ディレクトリ Grep、自動起動なし等）は、文書よりコードが悪い場合と、文書同士の矛盾がある場合に限って扱う。

## 指摘事項

### P1 — 設計正本のフック登録・Grep 対象外が、出荷実装と README と食い違う

- 証拠: 設計 §7 の `hooks.json` 全文（`docs/2026-09-12-token-shunt-design.md:181-267`）は SessionStart / PreToolUse(Read,Bash,Agent|Task) / PostToolUse(Read) / PostToolUseFailure(Read) のみ。「計 7 登録・5 スクリプト」と明記する。設計 §4:76 は Grep 本文取得の封鎖をやらないこととし、§11.8:448 は「Grep の `output_mode=content` … はフック対象外」、§15:809 は「Grep `output_mode=content` … は対象外」と繰り返す。実装の `plugin/hooks/hooks.json` はこれに加え PreToolUse Grep（`check-grep-bounds`、:56-64）、PostToolUse Bash（同スクリプト、:79-88）、Stop / SubagentStop（`check-final-answer`、:91-114）を既定登録している。README:137-190 は両フックを製品動作として説明する。比較判定器も設計 §13:626 の許可マッチャ（Read/Bash/Agent/Post Read/Failure/startup）を超え、`PreToolUse:Grep` / `PostToolUse:Bash` / `Stop` / `SubagentStop` を自前フックとして列挙する（`evals/compare/judge.py:24-36`）。
- 影響: 強制範囲の正本が割れている。README と `hooks.json` を見れば Grep 境界と最終回答の差し戻しは**強制**、設計を見れば Grep は対象外・Stop フックは存在しない。導入者が設計だけを読むと、既定で毎ターン末にセッションを読むフックと、単一ファイル content Grep の拒否が「仕様外」に見える。挙動自体は README とコードが一致しており、インストーラ向けの虚偽表示ではない。
- 再現: 静的のみ（`hooks.json` の登録と設計 §7 全文・§4/§11.8/§15 の文面を照合）。

### P2 — 配布 README が ZIP を「5 フック」のままにしており、既定 ON の 2 本が名簿から落ちている

- 証拠: `docs/distribution/README.md:13` は「スクリプトは5つのフックに実行権限を付け」、:17-29 の構成一覧は `check-file-size` / `check-bash-read` / `check-jq` / `check-agent-model` / `check-reader-contract` まで。:31 も「5つのフックに Unix の実行権限」。一方 `scripts/build-zip.sh:10` は `check-final-answer` と `check-grep-bounds` を含む 7 本に `chmod +x` し、検証も 7 本を要求する（:51-53）。`evals/test_build_zip.py:12-13` も 7 本。設計 §6:129-135・§13:591 の ZIP 実行ビット一覧も 5 本のまま。
- 影響: 展開物を目視確認する運用者が「ZIP が設計より多い」と判断するか、逆に配布手順だけ見て Stop / Grep フックが成果物に無いと誤解する。ビルド検証自体は 7 本で失敗するため、欠落したまま ZIP が出荷されるわけではない。
- 再現: 静的のみ。

### P2 — スキル description が設計 §11 の「トリガーのみ」を超え、手順をフロントマターに置いている

- 証拠: 設計 §11:430 は「両スキルとも `description` はトリガーと禁止トリガーだけ。手順は本文」。提示文面は bulk-reader が短い起動条件（:434-436）、code-writer が用途と小仕事方針（:452-454）。実装の `plugin/skills/bulk-reader/SKILL.md:2-3` はメタデータ判定、16384 バイト、Grep `head_limit` 1-20、`confirmed:` の逐語コピー、`auto` を haiku に解決する、といった**手順**を description に含む。`plugin/skills/code-writer/SKILL.md:2-3` も「Decide before Write/Edit; delegate at 50 expected lines」「reference I/O is at most 16384 bytes」を description に置く。本文側の手順（bulk-reader の §26.2 / バッチ / 編集契約、code-writer の検証段階）は設計 §11 と概ね一致する。
- 影響: Claude Code のスキル起動は description をトリガに使うため、この膨張は意図的である可能性が高い。設計の「トリガー vs 手順」分離は崩れている。比較 eval の B 群ルーティングは description に依存し得るので、設計どおり短く直せばテストが壊れる恐れがある。書き換えは要求しない。
- 再現: 静的のみ。

### P2 — 設計 §13 必須ケース `bash-pipe` は通過、実装・README・フックカタログは deny

- 証拠: 設計 §13:556 は `cat large | grep foo` を「通過」。同じ設計の §10:398 と §15:810 は同形を deny とする。実装カタログ `evals/bash-hook-evals.json:38-41` は `"expect": "deny"`。README:231 は未対応末尾でも対応 reader の各段を検査すると書く。
- 影響: 設計書内部でも必須ケース表とアルゴリズムが矛盾する。製品説明とフック eval は deny で揃っており、インストーラ向け README を欺くものではない。§13 表を正本にするとフック回帰が「失敗」になる。
- 再現: 静的のみ。

### P2 — マーケットプレイス文面が設計スニペットの「route」と出荷 JSON の「recommend」で割れている

- 証拠: 設計 §7:157 は `"Hooks block oversized Read/Bash and route to bulk-reader / code-writer subagents."`。出荷の `.claude-plugin/marketplace.json:13` は `"recommend delegation to bulk-reader / code-writer subagents."`。README:5 とユーザー向け要約は「フックが自動でサブエージェントを起動するわけではありません」。`plugin/.claude-plugin/plugin.json:5` は目的（delegating）であり自動起動とは書いていない。
- 影響: 出荷 marketplace は README の「案内であり自動起動ではない」と一致する。設計スニペットの "route to" だけが自動ルーティングに読める。導入コマンドが読むのは出荷 JSON なので虚偽インストールにはならない。
- 再現: 静的のみ。

### P2 — 比較 eval は製品既定 ON の `check-final-answer` を切り、リリースゲートが差し戻しを観測しない

- 証拠: README:169-173 は Stop / SubagentStop の差し戻しを「既定で有効」とし、`TOKEN_SHUNT_SENDBACK` の off/0/false/no でのみ無効。`plugin/hooks/sendback_stop.py:158-167` も未設定なら判定する。`evals/compare/run.sh:256-258` は ambient の `TOKEN_SHUNT_*` を消したあと `TOKEN_SHUNT_SENDBACK=${SENDBACK:-off}` を必ず立てる。`judge.py:2186-2190` の `release_eligible` は全カタログ case×mode の失敗数と計画一致だけを見、sendback の block/resume は見ない。README:190 自身が「製品の既定とは逆」と書いている。オフラインの `evals/compare/test_sendback_hook.py` は合成セッション用で、`evals/run.sh` の計上スイート（:217 の `grep_bounds` 等）には入っていない。
- 影響: `release_eligible: true` はスキル経路・隔離・親トークン必須観測を意味し、出荷時に既定 ON の保持フックが実機で動いたことの証明ではない。意図的な測定分離であり、README に開示がある。ゲート欠落としては残る。
- 再現: 静的のみ。

### P2 — 設計 §2 はモデル方針をスキル遵守とするが、実装は `check-agent-model` で強制する

- 証拠: 設計 §2:44 は「モデル方針・小仕事判定・作業量制限はスキル遵守（ベストエフォート）」。一方 §7:225-234 と実装 `plugin/hooks/hooks.json:45-53` は Agent|Task に `check-agent-model` を登録する。`plugin/hooks/check-agent-model:12-18` は `token-shunt:bulk-reader` / `token-shunt:code-writer` に対し `model` が `haiku`/`sonnet` 以外（省略・`auto` を含む）なら deny。README:92-94 はこの強制を製品動作として書く。小仕事判定と起動回数上限はフック化されておらず、スキル／eval 側のまま（設計 §26.2:890、`routing_checks.py` の起動数検査）。
- 影響: 「何が強制で何が契約か」のうちモデル明示だけが設計決定一覧と実装で食い違う。README とコードは一致。`worker-model-invalid` はフック拒否による実行防止であり、親がスキル段階で止めたことの証明ではない（設計 §7:314 はこの区別を既に書く）。
- 再現: 静的のみ。

### P2 — `bulk-reader` エージェント description が設計 YAML から親向けモデル指示へ伸びている

- 証拠: 設計 §12:486 は `Bounded reader of up to three explicitly supplied files, invoked via the token-shunt bulk-reader skill.`。実装 `plugin/agents/bulk-reader.md:3` はパス制限に加え「Launch with model set to a concrete worker model: resolve auto to haiku before calling, and never pass "auto" or omit model」。設計 §26.1:846 は agent md に親向け呼び出し文面を持たせないと書く。`plugin/agents/code-writer.md:3` は設計 YAML（:507）と一致。frontmatter の `model: haiku` / `effort: low` / `maxTurns` / `tools` は両エージェントとも設計どおり。スキルに `agent:` / `context: fork` は無い。
- 影響: 子エージェント定義に親の Agent 呼び出し規約が混ざる。`check-agent-model` がある現状では実害は小さいが、設計の「正本は reader-call-contract、agent は子の実行契約」から外れる。
- 再現: 静的のみ。

### P2 — README の Python 3 不足説明が、既定 ON の Grep / Stop フックまで届いていない

- 証拠: README:219 は Python 3 不足時に `check-file-size` が bulk-reader Read を exit 2 で止め、`check-reader-contract` が全 Read の Pre/Post/Failure で起動失敗し得ると書く。非ワーカーへの影響は「CLI の起動失敗の扱いに依存し、実機では未確認」。同じ Python 3 shebang の `check-grep-bounds`（`plugin/hooks/check-grep-bounds:1`、hooks.json で Grep Pre と Bash Post に既定登録）と `check-final-answer`（`plugin/hooks/check-final-answer:1`、Stop / SubagentStop 既定登録）はこの段落に出てこない。`plugin/.claude-plugin/plugin.json:5` は "Requires jq and Python 3 on Unix" とだけ書く。
- 影響: jq 不足は README:14 どおり Read/Bash/Agent|Task が fail-closed。Python 3 不足は Read 以外（Grep、Stop、Bash のサイズ記録）でもフックプロセスが起き、block か fail-open かは README 自身が未確認とする領域が広がる。虚偽の「Python 不要」主張ではない。
- 再現: 静的のみ。実機の CLI 起動失敗扱いは未検証。

## 確認したが問題なし

- バージョンと目的文: `plugin/.claude-plugin/plugin.json` は name/version 0.1.0、jq と Python 3、Spotify shunt 非併用。README 先頭も 0.1.0 開発中、トークン削減は未確認。90% は製品文面に無い。
- 強制 vs 契約（README ↔ コード）: Read/Bash サイズゲートはフック強制。`agent_type` 完全一致の免除は bulk-reader が Read+Bash、code-writer が Read のみ（`check-file-size:227-236`、`check-bash-read:243-246`）。`tool_input.agent_type` は見ない（`evals/run.sh:118-125` の spoof ケース）。通過時に `permissionDecision` を出さない。writer の Write にフックは無い（README:90、code-writer SKILL:126-129）。
- Grep 境界の実装は README と一致: 単一既存ファイルかつ `output_mode=content` かつ 16384 超のみ判定。directory/glob/複数は触らない。writer には `wc -c` も bulk-reader も案内しない（`grep_bounds.py:161-197`）。記録は PostToolUse Bash の素の `stat`/`wc -c` と Read deny の `--sized`（`check-file-size:197-201`）。成功 Read は記録しない。
- 環境変数: README 表の `TOKEN_SHUNT_MIN_*` / `SCAN_BUDGET_*` 既定値は両サイズフックの `int_env` と一致。負数・非整数は既定に戻す。`TOKEN_SHUNT_HOOK_LOG` は判定を変えない。`TOKEN_SHUNT_SENDBACK` 未設定は有効、`TOKEN_SHUNT_SESSION_MAX_BYTES` 既定 64MiB。比較ランナーの `TOKEN_SHUNT_CASE_TIMEOUT` 既定 600、`SUITE` による絞り込み。
- フックイベント: README が挙げる SessionStart / PreToolUse(Read,Bash,Agent|Task,Grep) / PostToolUse(Read,Bash) / PostToolUseFailure(Read) / Stop / SubagentStop は `hooks.json` に実在する。exec form（`args: []`）と timeout 秒も設計 §7 の残存分と一致。
- スキル本文とエージェント実行契約: 3 パス・Read 6+終了 1・maxTurns 7、writer は maxTurns 12・Read/Write/Grep/Glob、親が検証、明示委譲と読めない参照の優先、は README・SKILL 本文・agent md・設計 §11-12 で揃う。`reader-call-contract` を明示委譲と deny テンプレートの正本にする方針（設計 §26.1）は SKILL 本文:99-105 と一致。
- 導入・doctor: marketplace はリポジトリルート、`plugins[].source` は `./plugin`。doctor は `--plugin-dir "$ROOT/plugin"` と `--setting-sources ""`（`scripts/doctor.sh:53-55`）。jq 不足と Bash <4 だけが硬失敗（:12-13, :23-34）。`plugin + agent registration: confirmed` はソース側プローブ成功時のみ記録（:216-235）。`agent_type` は手順の提示のみで合否にしない（:251-271）。FORCE=1 でモデル比較を無効と報告。README:289 の注意と一致。
- 比較カタログは設計 §26.5 の A/B ID をカバーする。境界は `auto-routing-boundary-*` に分割、曖昧バッチと曖昧 Grep は追加 ID。`require_parent_tokens` は大容量読取 3 + 大規模生成 1 の direct/auto（cases.json の auto-bulk-facts / auto-one-line / auto-explicit-multifile / auto-large-writer）。`suite_cost_usd` の `release_gate` は false（`judge.py:2186`）。`release_eligible` は全必須ペア成功時のみ（:2190）。一部スイートだけではリリース完了にならない（README:279）。
- フック eval（`evals/run.sh`）は設計 §13 の必須 ID をカタログまたは特別ケースとして持ち、`grep_bounds` 回帰も計上する。ZIP 検証は実装の 7 フックに追随。
- 既知限界として README / 設計 §15 が挙げる `cat <file>`、sed、`python -c`、ディレクトリ Grep、Explore 起動自体は止めない、均等行分割しない、自動起動しない、はコードを「文書より悪い」方向へは見ていない（Bash パーサの穴は深追いしていない）。

## 疑ったが未検証

- Python 3 が無いとき、既定登録の `check-grep-bounds` / `check-final-answer` の起動失敗が CLI で tool を止めるか fail-open か（README は契約フックについて未確認と書いており、本レビューも実機未実行）。
- `SENDBACK=on` の実機比較が、保持違反を実際に block し親が `confirmed:` を再掲するか。ランナー既定では観測できない。
- doctor の「フック stdin に `agent_type` が出る」手順を、認証済みセッションで実行した場合のフィールド有無。スクリプトは dump しない。
- スキル description の長さが Claude Code のトリガ選択に与える影響（設計 §11 違反の実害があるかは未測定）。
