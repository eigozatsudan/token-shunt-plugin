# 通常・正確性レビュー（クリーンコンテキスト）

実施日: 2026-09-15。会話非継承。reviews/・git履歴は根拠にしない。ソース変更なし。

対象は現行ソース・テスト・README。優先ファイルのフック実装を読み、stdin でフックを回して疑義を確認した。`evals/compare/run.sh` は未実行。

## 指摘事項

### P2 — `test_a_read_deny_that_named_the_size_counts_as_measured` は Read deny 配線を通していない

- 証拠: `evals/test_grep_bounds.py:205-210` は `check-grep-bounds --sized` を空の Read イベントで直呼びし、その後の content Grep が通ることだけを見ている。サイズが「Read 拒否本文で告げられた」経路の実装は `plugin/hooks/check-file-size:197-201`（`record_sized`）と `206-209`（`deny_contract` 成功時だけ呼ぶ）にある。このテストは `check-file-size` を起動しない。
- 影響: `record_sized` の呼び出しが消える・stdin を渡さない・`CONTRACT_SIZED` が空のまま、といった配線壊れは、テスト名が主張する規則では落ちない。`--sized` モード自体と、実フックからの通知は別物。
- 再現: した（テストは `--sized` 直呼び。別途 oversized ファイルで `check-file-size` が deny したあと、同じ `session_id` の `head_limit=5` content Grep は通過することを確認した。製品経路は現状動く。欠けているのはテストの範囲）

### P2 — DENY_CAP の加算はユニットが `decide()` に事前セットした値しか見ていない

- 証拠: `evals/test_grep_bounds.py:99-103` と `120-125` は `state['denials'] = gb.DENY_CAP` を置いてから `gb.decide()` する。加算は `plugin/hooks/check-grep-bounds:85-90` の `judge()` 側（`reason` があるとき `denials += 1`）。`decide()` 単体はカウンタを増やさない。
- 影響: 上限メッセージの文言分岐（親は `report partial` / `bulk-reader`、writer は `files_with_matches`）はカバーされている。一方「拒否するたびに 6 まで増える」はテスト名 `test_refusals_stop_at_the_cap` が暗示する動作なのに、フック実行では検証されない。加算を外してもこれらのテストは緑のまま。
- 再現: した（同一 session で未計測 content Grep を 8 回: 6 回通常 deny のあと 7・8 回目が `refused 6 times`。加算自体は動く。欠けているのはテスト）

### P2 — スキル説明テストのコメントが「Grep はフックされていない」のまま

- 証拠: `evals/test_reader_call_contract.py:501-502` コメントは `Grep is not hooked at all, so no deny can ever stand in for the route-before-search rule.`。同じテストのアサーションは `plugin/skills/bulk-reader/SKILL.md:3` の `Grep output_mode=content` を要求し、本文 `26-31` は「1 ファイル・予算超過の content は hooked」と書いている。`plugin/hooks/hooks.json:55-65` は `matcher: Grep` で `check-grep-bounds` を登録している。
- 影響: テストは現行スキルに対して緑。コメントだけが実装前の前提を残しており、説明文を「フックされていない」側へ戻す変更を正当化しかねない。
- 再現: 静的のみ（テスト 58 件は OK。コメントとアサーションが矛盾）

### P2 — SessionStart の Python 3 警告が Grep フックを言わない

- 証拠: `plugin/hooks/check-jq:19-21` は「Python 3 is required for the bulk-reader runtime contract. Bulk-reader Reads remain blocked」。`plugin/hooks/check-grep-bounds` は shebang が python3 で、`hooks.json:55-65` により親の Grep にも乗る。python3 が無いと Grep は起動できず `hooks.json` どおり fail-closed（stdin 不正時は `check-grep-bounds:143-145` で exit 2）。`plugin/.claude-plugin/plugin.json` は Python 3 をプラグイン要件にしている。README の依存不足節は契約フックが全 Read に載ることまでで、Grep には触れていない。
- 影響: 導入時メッセージを読むと「無いと止まるのは bulk-reader の Read」に読める。実際は親の Grep も止まる。プラグイン要件としては Python 3 必須なので経路そのものは「Python 3 がある」前提では壊れない。
- 再現: 静的のみ（本環境には python3 がある。欠落時の SessionStart 文言と hooks.json の登録範囲の不一致）

## 確認したが問題なし

### Grep 判定範囲とパス解決

`plugin/hooks/grep_bounds.py:161-177` が判定するのは `tool_name=Grep` かつ `output_mode == "content"` かつ `target_file()` が通常ファイル 1 件を返したときだけ。`glob` あり・path 欠落・ディレクトリ・欠ファイルは `None` で未判定。予算 `BUDGET=16384` 以下も未判定。`files_with_matches` / `count` / `output_mode` 省略は通過。省略は Claude Code の既定 `files_with_matches` と一致する（stdin で省略イベントを流し、over-budget でも通過を確認）。

相対パスは `plugin/hooks/check-grep-bounds:58-76` がイベントの絶対 `cwd` へ `chdir` してから `os.path.abspath`。`cwd` 不正は判定経路では deny、記録経路（`--sized` と PostToolUse Bash）では絶対パスだけ残す（`96-106`）。`evals/test_grep_bounds.py:212-254` がセッション cwd・同名デコイ・壊れた cwd をカバー。README の「cwd 省略時はフック起動ディレクトリ」と一致。

### サイズが measured になる経路

記録源は 2 つだけ。成功 Read は記録しない（`grep_bounds.py:18-23` のコメントどおり）。

1. PostToolUse Bash: `hooks.json:79-88` → `check-grep-bounds:119-134` → `metadata_paths`（`grep_bounds.py:100-136`）。`stat` / `wc -c`（`--bytes`）の展開なしコマンドだけ。`$` やパイプは空。
2. Read deny: `check-file-size:194-201,206-209` が契約本文にバイト数を載せたパスだけ `--sized`。サイズ不明は `CONTRACT_SIZED` に入らない。

計測の同一性は inode + size + mtime_ns（`grep_bounds.py:84-97`）。変更後は未計測に戻る。テストと、`check-file-size` deny 後の Grep 通過の両方で確認した。

### DENY_CAP と agent_type なりすまし

拒否回数は session+agent 単位（`check-grep-bounds:28-34`、親は `agent_id` 欠落で `'parent'`）。`denials >= 6` のとき親は `bulk-reader` / `report partial`、writer は `files_with_matches` と Read（`grep_bounds.py:179-188`）。判定は `event.get('agent_type')` のみ。`tool_input.agent_type` は見ない。

再現: `tool_input.agent_type=token-shunt:code-writer` の親 Grep は `wc -c` 案内（`evals/test_grep_bounds.py:138-142`）。160000 バイトファイルで Read/Bash も `tool_input.agent_type` を bulk-reader / code-writer にしても deny。トップレベル `agent_type` だけが免除（`check-file-size:224-236`、`check-bash-read:244-246`）。

### Writer を持たない経路へ送らない

`plugin/agents/code-writer.md:7` の tools は Read, Write, Grep, Glob。Bash なし。`check-file-size:235` が writer の Read をサイズ免除するので、Read deny 経由の計測も起きない。したがって writer の予算超過 content Grep は常に未計測分岐（`grep_bounds.py:189-193`）に入り、案内は `files_with_matches` か必要範囲の Read。`wc -c` も `bulk-reader` も出さない。上限到達時も同様（`181-185`）。stdin で writer + `head_limit=5` でも未計測 deny、文言に `bulk-reader` / `wc -c` が無いことを確認。親は従来どおり `wc -c` と上限時の委譲案内。README 152 行付近と一致。Grep ゲートは writer が取れない経路へは送っていない。

### Sendback: 既定オン、off、block / pass、SubagentStop

`plugin/hooks/hooks.json:91-114` が Stop と SubagentStop の両方に `check-final-answer` を登録。`sendback_stop.py:158-167` は `TOKEN_SHUNT_SENDBACK` が `off`/`0`/`false`/`no` のときだけ切る。未設定・`on`・空文字は有効。off はセッションを読まず `DISABLED`（`321-324`）。`evals/compare/test_sendback_hook.py` の `SwitchTests` / `WorkerTests.test_the_switch_turns_the_worker_side_off_too` が両方を固定。

親 Stop が block するのは、ワーカー出力が取れ、最終回答が `last_assistant_message` で特定でき、`line_retention` が violation のときに限る（`370-400`）。`stop_hook_active`、実行中ワーカー、出力不能、回答不明、ワーカー側契約違反、transcript 由来の本文は通す。SubagentStop（または `agent_id` あり）は `decide_worker`（`325-329`）。対象は `token-shunt:bulk-reader` だけ（`258-260`）。writer と他エージェントは `not a bulk-reader worker`。`unconfirmed:` のみ・インフラエラー・入力に報告が無いときは通す。比較評価が `TOKEN_SHUNT_SENDBACK=off` にするのは README 190 行どおり製品既定とは逆で、フック側の既定オンを壊していない。

### スキル文面と hooks.json（Grep の hooked / not）

`plugin/skills/bulk-reader/SKILL.md:3,26-31` は「1 ファイルの予算超過 `output_mode=content` は hooked（先にサイズ、そのあと head_limit 1-20）。ディレクトリ / glob / 裸検索は not hooked。`-o` や `head -c` もこのフックの対象外」。`hooks.json` の Grep マッチャと `grep_bounds.decide` の早期 return と一致。`head -c` ファイルオペランドは Bash フック側の話で、README 制限事項どおり Grep フックは見ない。`plugin/skills/code-writer/SKILL.md` は Grep フックに触れないが、拒否本文が writer 向け案内を返すため、通常の writer 手順（参照を Read して Write）は壊れない。

### 読取契約とモデル指定

bulk-reader の Read はサイズ免除のあと `check-reader-contract` が 6 回・直列・絶対パス・最大 3 パス・実返却行のカーソルを強制。親・writer は `agent_type` 不一致で即 return（`check-reader-contract:128-129`）。`evals/test_reader_contract.py` 17 件 OK。`check-agent-model` は `tool_input.subagent_type` が token-shunt ワーカーのとき `haiku|sonnet` 以外を deny。呼び出し側の正当なフィールドであり、`tool_input.agent_type` によるサイズ免除とは別。

### 実行したテスト

- `python3 -B evals/test_grep_bounds.py` 35 OK
- `python3 -B evals/test_reader_call_contract.py` 58 OK（skip 3）
- `python3 -B evals/test_reader_contract.py` 17 OK
- `python3 -B -m unittest test_sendback_hook`（`evals/compare`）51 OK
- `evals.compare.test_retention_checks` 27 OK

## 疑ったが未検証

- 親の Stop 入力に `agent_id` が付く CLI があるか。付くと `sendback_stop.py:325` が `decide_worker` に落とし、親の保持判定が走らない。テストの親イベントは `agent_id` 無し。実 CLI の Stop ペイロードは見ていない。
- SubagentStop に `agent_type` が無い場合。`decide_worker` は `event.get('agent_type') != token-shunt:bulk-reader` で通すため、ワーカー差し戻しが死ぬ。README はトップレベル `agent_type` を環境要件にしている。実機 SubagentStop は未確認。
- Grep の `context` キー（`-C` の別名として公開スキーマに出ることがある）。`_form_error` は `-A`/`-B`/`-C` だけを見る。stdin で `context: 5` は通過した。この CLI が `context` を受理するかは未確認。
- `-A`/`-B`/`-C` が JSON 文字列 `"5"` のとき、`isinstance(value, int)` が偽で文脈チェックをスキップし、計測済み `head_limit=5` が通過する（確認済み）。スキーマは number。通常の数値 JSON では deny される。通常経路の想定型ではないので指摘には上げない。
