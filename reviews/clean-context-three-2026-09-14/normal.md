# 通常・正確性レビュー（クリーンコンテキスト）

実施日: 2026-09-14。会話を継承しない独立コンテキストで実施。`reviews/`・`docs/history/`・git 履歴は根拠に使わず、現行ソース・仕様・テストのみを確認。ファイル変更なし（読み取り専用）。

---

# token-shunt コードレビュー報告

## 確定した問題

### 1. 【中】比較評価ケース `auto-routing-boundary-50-lines` — fixture と gold の不整合により恒常失敗

- **箇所**:
  - `evals/compare/run.sh:151`（コメント「50-line py」）、`run.sh:161-163`（生成コード）
  - `evals/compare/cases.json:1151-1164`（`"gold": ["def task_fifty"]`、プロンプト「line 50 に定義されている関数名」）

- **引用**（run.sh:161-163）:
  ```python
  py = ["def task_%d():\n    return %d" % (i, i) for i in range(1, 50)]
  src = "\n\n".join(py) + "\n\ndef task_fifty():\n    return 50\n"
  ```

- **内容**: 各関数は `def` 行 + `return` 行 + 空行の3行構成のため、`task_i` の `def` は `3i-2` 行目。`def task_fifty` は **148行目**（return は149行目）にあり、ファイル全体は149行。**50行目は `    return 17`**（task_17 の本体、def は49行目）であり、50行目に `def` 文は存在しない。「50行ファイル」という命名・コメントの意図（おそらく `def task_N(): return N` の1行関数×50）とも生成物が一致していない。

- **影響**: `judge.py:1141` の accuracy は `gold` 文字列の部分一致（`g not in final` → fail）のみで、「50行目」という意味論は検証しない。正しい回答（task_17 または「該当なし」）では `def task_fifty` が出現せず**必ず失敗**する。逆に誤答でも文字列を含めば合格し得る。経路側の期待（`agent_zero`）は 149行 < 350行 かつ 約1.7KB < 64KiB で偶然成立するが、accuracy は両モードで恒常的に失敗する。このケースは必須スイートに含まれるため、`planned == mandatory` を要求する `release_eligible`（judge.py:2128）はこのケースが残る限り永遠に true にならない。

- **再現**: 確定済み（構築により自明＋実機証跡あり）。`python3 -c '...'` で上記生成式を再現し `sed -n '49,51p;148,149p'` で確認可能（※統合側で再現済み: total=149行、50行目は `    return 17`、`def task_fifty` は148行目）。

- **修正案**: (a) `["def task_%d(): return %d" % (i,i) for i in range(1,50)]` を `"\n"` 連結し50行ファイルにする（コメントと整合）、(b) gold を実際の該当関数に修正、(c) 質問を「`task_fifty` は何行目で定義されているか」に変更。

### その他の確定した問題

なし。上記1件のみ。

## 確認したが問題なし

**フックスクリプト**

- `check-jq`（全27行）: `jq` を一切呼ばず、Bash 4 未満・`jq` 欠如・Python 3 欠如を全件 `additionalContext` で報告し常に exit 0。`evals/run.sh:141-167` のテストが両欠如の同時報告を検証。
- `check-file-size`: Bash 4 ガード→exit 2、jq 必須→exit 2、不正JSON→exit 2（fail-closed）。`agent_type` はトップレベルのみ参照し `tool_input` 内の偽装を無視（`evals/run.sh:119-125` の spoof テストで確認）。bulk-reader には `command -v python3` ゲート。code-writer の Read は無条件免除。`jq -j`+sentinel でファイル名末尾改行を保持。拡張子除外は `${file_path,,}` 小文字化で一致。`int_env` は15桁超・負数→既定値、`10#` で8進数回避。`range_scan`/`full_file_verdict`/`tail_scan` は budget+1 の `head -c` で入力を制限し、固定1バイトの EOF マーカーで未終端最終行を stat 非依存で判定、`pipefail`+ドレインで SIGPIPE と読み取りエラーを区別、出力形式不正は undetermined→deny。しきい値ちょうどは超過に含めない（`>` 比較、README:106 と一致）。`stat -L` でシンボリックリンク先を測定。
- `check-bash-read`: 字句解析（引用/エスケープ/コメント/heredoc 対応）、`{fd}>` 名前付きfd拒否、`>&`/`&>`/`>>|`/ゼロ埋めfd（`02>`等）の識別、`is_isolating_target`、パイプ末尾 `head|tail` は純stdinかつ単一 `-c N`（N≤MIN_BYTES、≤15桁）のみ通過、中間段の side output は `PIPE_FDS` 記述子モデルで検査、先頭リテラル `cd` 連鎖のみ追跡。`$( )`/バッククォートは当該セグメントを uninterpretable にするだけで他セグメントの検査を免除しない。全て `test_bash_operational_hooks.py`・`test_bash_finding_fixes.py`・`test_cd_hooks.py`・`test_review_hooks.py` で実 bash の出力バイト数と突き合わせ済み。
- `check-reader-contract`（Python、fcntl.flock）: 状態は `(session_id, agent_id)` ごとに `O_NOFOLLOW`+0600 ファイル、0700 所有権検証済みディレクトリ。PreToolUse で `calls>=6` 拒否（拒否試行も消費）、pending 直列化、≤3パス、`offset==cursor['next']`、拒否時 `floor(count/2)` の強制 retry 値、limit=1 拒否→stopped（1行ファイルに限り1回の有界 retry を許容）、`PostToolUse` は `tool_response.file` の実返却 startLine/numLines/totalLines でカーソル更新、結果メタデータ欠落・不正→`stopped`（fail-closed）。`tool_use_id` が一致しない post イベントは別 Read を確定しない。`evals/test_reader_contract.py` が全項目を検証。
- `check-agent-model`: token-shunt の2ワーカーのみを対象に `model ∈ {haiku, sonnet}` を要求。`tool_input` が非オブジェクト→exit 2、jq 失敗→exit 2、非 token-shunt Agent は素通り。
- `hooks.json`: SessionStart/PreToolUse(Read: file-size+reader-contract、Bash、Agent|Task)/PostToolUse/PostToolUseFailure(Read) の登録は judge の `TS_HOOKS`/`TS_HOOK_NAMES`（judge.py:24-34）と一致。

**未防御だが仕様書・README に明記された意図的制限（欠陥ではない）**: `<file` 入力リダイレクト（README:185）、`$'...'` ANSI-C 引用（186）、`$(cat …)` 等のコマンド置換・`bash -c`/`xargs`/`dd if=`（182）、未知のパイプ末尾コマンドへの fail-open（`check-bash-read:805`、§15）、`(`/`{`/if/`time`/`sudo` 等の前置形（184）、呼び出し跨ぎの読取量非集計（189）、同一マッチャ上の外来 pass フックの不可識別性（192）。

**評価ハーネス**

- `evals/run.sh` + 2カタログ（計約100件）: 全期待値を実装に対して突き合わせ一致。`deny` は理由中の `bulk-reader` を要求、`deny_safety` は `token-shunt` 帰属のみ要求、`deny_budget` は scan budget 詳細を要求 — `deny()` が `token-shunt:` を自動付与するため帰属は常に保持される。`render_command.py` は引用コンテキスト別に `@FIX@` を安全置換。ambient `TOKEN_SHUNT_*`/`CDPATH` の除去後にカタログ env のみ適用。
- `evals/compare/run.sh`: 作業開始前の `last-run.json` 無効化（384行目）、隔離 RUN_ROOT、load/isolation/plugin-validate の3プローブ、`deny_route` ケースのプロンプト機密語ガード、`gold_file` の事前検証、spec/verdict/disk/leak/manifest の証跡分離、`cli_exit_code` の保存（非0単独では不合格化しない）、judge クラッシュ時は run 全体を abort（保守的方向）、leakcheck は rc=1=clean/0=leak/2=unverified で run.sh:580 と整合。
- `judge.py`: `validate_tool_inputs`、`foreign_hooks`、`ts_deny_payload`、`deny_route` の位置順序束縛、`child_result_evidence`、`child_status`、引用漏洩検出（>2048バイト連続/非空21行）、トークン内訳の厳格検証（欠測は0補完せず不合格）、`retry_policy`、`aggregate`（manifest planned/required 検証、spec/verdict 同一性、disk_ok、親トークン証跡、isolation 3ポリシー、`suite_cost_usd.release_gate:false` 固定、`selected_run_valid` と `release_eligible` の分離）。
- `test_quote_metrics.py`・`test_aggregate.py`・`test_input_validation.py`・`test_async_retry_routing.py`・`test_writer_boundaries.py`・`test_live_rerun_regressions.py` 等24ファイル: いずれも実装と矛盾なし。
- `scripts/build-zip.sh`: 実行ビット付与・manifest 一意性・配置・キャッシュ除外を python3/zipinfo 両経路で検証（`test_build_zip.py`）。
- `scripts/doctor.sh`: 記録の原子的作成・失敗時旧記録保持（`test_doctor_record.py`）、jq欠如/Bash4未満/記録保存失敗は hard fail、実機プローブ不可は `unconfirmed`（設計どおり）。
- README/docs: 「トークン・料金の削減効果は未確認」と明記（README:7、配布README:3,79）。制限事項の記述は実装と一致。

**軽微な観察（影響なし）**: `check-file-size`/`check-bash-read` は `tool_input` が非オブジェクトの型混乱入力で jq エラー→空値→pass（fail-open）だが、`file_path`/`command` を文字列として運べない以上、実害はなく `check-agent-model`（fail-closed）との非対称に留まる。`run.sh:502` のコメント「UNSUBSTITUTED prompt」は実際には `{WMHINT}` 置換済みの段階で走査する（`{FIX}` は未置換であり意図は正しい）。

## 疑ったが未検証

- **テストスイートの実実行**: 本セッションではシェル実行が不可能だったため、`evals/run.sh`・`unittest discover`・`judge.py --selftest` の実走行は未実施。全ての整合性は静的照合と既存の実行証跡（`reviews/live-rerun-*`）に基づく。
- **実 CLI のイベントスキーマ依存項目**: `check-reader-contract` が依存する `hook_event_name`（`PostToolUseFailure`）、`agent_id` の存在、`tool_response.file.{startLine,numLines,totalLines}` の形、失敗時 `error` 文字列「File content … exceeds maximum allowed tokens」、非同期 `tool_use_result.isAsync`/`task_notification` の各フィールドは、テストと実機証跡で確認済みの CLI 版に一致するが、他バージョンでは未検証（欠落時は全て fail-closed 方向）。
- **jq の `//` の型誤用時の版差異**: `{"tool_input":"x"}` 等で `.tool_input.file_path // empty` がエラー終了するか空になるかは jq 版に依存する可能性。どちらでも pass に帰着するため実害なし。
- **`timeout --kill-after` の GNU 依存**: compare 評価は GNU coreutils の `timeout` を前提。macOS 等では未検証（README は `timeout` を要件として明記）。
- **`EPOCHREALTIME`/`date +%s%3N` の経路差異**: フォールバック（`SECONDS*1000`）あり。非 Linux 環境での時刻予算精度は未検証。
- **`fcntl.flock` の非 Unix 非対応**: Unix 要件として明記済み。非 Unix では import 時に失敗→exit 2（fail-closed）と推測されるが実機未検証。
- **`echo $(cat large)` 型の置換内読み取りが実機で本文を流出させること**: 実 bash の意味論上は流出するが、文書化済みのスコープ外であり、実測による確認は未実施。
