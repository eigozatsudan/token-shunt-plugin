# 俯瞰・設計整合性レビュー（クリーンコンテキスト）

実施日: 2026-09-14。会話を継承しない独立コンテキストで実施。`reviews/`・`docs/history/`・git 履歴は根拠に使わず、現行ソース・仕様・テストのみを確認。ファイル変更なし（読み取り専用）。

---

# token-shunt 設計整合性監査報告（読み取り専用）

対象: `/home/dev/projects/skills/token-shunt`。現行ソース・仕様書・テストのみを根拠にし、`reviews/`・`docs/history/`・git 履歴は証拠に使っていません。ファイルの変更は一切ありません。

## 指摘事項

### P1 — 文書化されたオフライン回帰コマンドがクリーンなチェックアウトで失敗する（現ツリーでも該当ファイル不在）

- **証拠**:
  - `evals/compare/test_runner.py:97-98` — `committed_gold = Path(__file__).parent / "fixtures/gen/gold-edit-hint.json"` を無条件に `read_text()`。変数名が「committed」を自称するが、当該ファイルはコミット対象外。
  - `evals/compare/.gitignore:2` — `fixtures/gen/` が ignore 対象。
  - `evals/compare/run.sh:32` — 「runtime fixtures (generated, not committed)」。`gold-edit-hint.json` は `run.sh:207` で `$GEN`（= `$RUN_ROOT/work/fixtures/gen`、`run.sh:39`）にのみ生成され、`SOURCE_FIX=$CMP/fixtures`（`run.sh:12`）への書き込み経路は存在しない。
  - find 確認の結果、現作業ツリーにも `evals/compare/fixtures/gen/` は存在しない（`fixtures/` 配下は `codegen/`・`edit/`・`rails/` のみ）と報告（※統合側の偽陽性チェックで、未追跡ファイルは現ツリーに存在することが判明。クリーン checkout での失敗自体は成立）。
  - 破損する文書化コマンド: `README.md:204` と `docs/distribution/README.md:74` の `python3 -m unittest discover -s evals/compare -p 'test_*.py'`。
- **再現**: クリーン checkout で上記 unittest discover を実行 → `test_edit_hint_gold_and_prompts_agree_with_disk_check` が `FileNotFoundError` でエラー。なお `evals/run.sh:209` が走らせる `test_unreadable_and_model.py` 単体指定は `test_runner.py` を含まないため、そちらは影響なし。
- **影響**: 設計 §26.6 / 配布 README:79 の「配布前の確認」手順の一つが実行不能。判定ロジック自体の誤りではないが、リリース確認経路の一部が壊れている。

### P2 — `gold_confirmed` が basename のみの `confirmed:` 引用を受理（SKILL 契約より弱い）

- **証拠**: `evals/compare/judge.py:638-661` — `gold_path_needles` が `os.path.basename(fp)`（:649）と `os.path.basename(rp)`（:655）を needle に追加し、`gold_confirmed_ok`（:664-679）はいずれかの needle を含む `confirmed:` 項目を合格とする。
- **契約側**: `plugin/skills/bulk-reader/SKILL.md:78-86` — 「preserve the literal `confirmed:` label and absolute path」「Do not replace them with basename-only citations」「A trailing `(confirmed: basename)` citation does not satisfy this contract」。
- **影響**: `compare-explicit-multifile`（`cases.json:175` の `gold_confirmed`）で、basename だけの引用をする親回答が判定を通過し得る。検証不足であり、仕様違反の成功を許容する。
- **再現**: 未検証（実機 transcript 要）。

### P2 — 子返答検査ブロックが宣言依存で、6 委譲ケースが `child_no_body` 未適用、2 ケースは返答到達証跡も未検査

- **証拠**: `evals/compare/judge.py:1374` — ブロック全体が `cap or exp.get("child_no_body") or any bulk-reader` 条件で起動。`child_no_body` 引用検査は :1411-1420 で宣言時のみ。
- **未宣言ケース**: `retry-policy`（`cases.json:557-567`、cap も無し）、`writer-bounds`（:579-586、cap/no_body 共に無し）、`writer-verification-levels`（:306-358、同）、`auto-large-writer`（:931-950、cap のみ。:953 の `writer_body_absent` で親側は補償）、`auto-routing-boundary-16k-plus`（:1138-1147、cap のみ）、`auto-routing-boundary-50-lines-writer`（:1227-1232、cap のみ）。
- **追加の非対称**: `writer-bounds` と `writer-verification-levels` は code-writer のみかつ cap/no_body 未宣言のためブロックが完全スキップされ、`child_result_evidence`（子返答が起動後・最終結果前に親へ届いた証跡、:1381-1398）すら未検証。また `child_status` は bulk-reader 限定（:1400）のため、writer 子の返答契約（`status`/`stop_reason`・800字・パス+行数+3〜5 bullet、`plugin/agents/code-writer.md:18-21`）は全ケースで機械未検証。
- **影響**: §13/§11 の子→親契約に対する検証カバレッジの非対称。design §26.5 が当該検査をケース別に必須化していないため仕様違反ではないが、検証の盲点として記録に値する。
- **再現**: 未検証（実機 transcript 要）。

### P2 — A 群の delegate モードでは要求/解決モデルが未検証、`expected_resolved_model` の値は実質有効化フラグ

- **証拠**: `evals/compare/routing_checks.py:256-258` — ルーティング検査ブロックは `expected_resolved_model`・`retry_policy`・`batch_invocation` のいずれか宣言時のみ有効化。`expected` は :279-284 で `mode` と再試行回数からハードコード導出（auto→初回 haiku、再試行→sonnet）。宣言値（例 `"haiku_then_authorized_sonnet"`）は有効化以外では参照されない。
- **影響**: A 群（compare-bulk-facts/one-line/explicit-multifile の haiku/sonnet/auto モード、compare-hook-deny-route、compare-code-writer-ok/no-ref、writer-bounds）では、要求モデルと実モデルの照合が走らない。例えば `sonnet` モードで haiku が起動しても検出されない（`worker_attempts[].requested_model` には記録される、`judge.py:464`）。design §917 の対応表照合は B 群の記述（「**B** の path_ok は機械判定」）なので仕様スコープとは整合するが、モード名を持つ A 群での未検証は記録に値する非対称。B 群の委譲ケースは全て `expected_resolved_model` 宣言済みで、そちらは fail-closed（:310-315、resolvedModel 欠測・不一致で fail）。
- **再現**: 未検証（実機 transcript 要）。

### P2 — `BUILTIN_HOOKS` が同名の外来 `SessionStart:startup` フックを不可視化

- **証拠**: `evals/compare/judge.py:26`（`BUILTIN_HOOKS = {"SessionStart:startup"}`）と :991-992 — 同名の `hook_response` は payload 検査前に skip。managed settings のフックは `--setting-sources ""` では切れないため、`startup` マッチャに載った外来 SessionStart フックは検出不能。
- **影響**: `README.md:192` が文書化する残穴は「同一 PreToolUse マッチャ上の外来**通過**フック」のみで、SessionStart の名前衝突は未記載の追加盲点。狭いが、ドキュメント未記載。
- **再現**: 未検証。

### P2 — 設計 §26.5:893 の cases.json フィールド名が実装とドリフト

- **証拠**: `docs/2026-09-12-token-shunt-design.md:893` は `suite`、`routing`、`worker_model`、`expected_agent_calls`、`required_paths`、`expected_resolved_model` を規定。実装の語彙は `expect.<mode>.agent_type`、`agent_calls_min/max`、`child_reads_once`、`single_invocation_paths`、`batch_invocation`、`expected_resolved_model`、`require_parent_tokens`。`required_paths` は `routing_checks.py:117` に実装されるが全ケース未使用（同様に `deny_route.allow_range`＝`judge.py:1323`、`expect.plugin` 既定＝`judge.py:1109` も未使用の防御的語彙）。
- **影響**: 意味的カバレッジは完全で、名称のみ陳腐化。設計読者の誤解リスク。
- **再現**: 静的確認済み。

### P2 — 費用集計と 48 実行反復が設計記述とドリフト

- **証拠**:
  - 設計 §931（`design:931`）は「それぞれの単価を掛けて合計」「単価の公式出典 URL・取得日・価格適用日・プロバイダーを保存」を規定 → 実装は CLI 報告 `total_cost_usd` のみ（`judge.py:479`、集計 :2096-2124）。`README.md:229` は実装どおり「CLI 報告費用」と正直に記述しており、誤魔化しはないが設計本文が未更新。
  - 設計 §928（`design:928`）は「4 件 × 4 モード × 3 反復・順序交替・新しい会話」を規定 → `evals/compare/repeat.sh:11-21` は `run.sh` をそのまま N 回（既定 2）実行するだけで、順序交替も 4 件限定も無い（全カタログを各反復で実行）。
- **影響**: §933 で「内部回帰・出荷条件ではない」と明示されているため軽微だが、規定手法と実装の差分は記録に値する。
- **再現**: 静的確認済み。

### P2 — marketplace 説明文が自動ルーティングをやや誇張

- **証拠**: `.claude-plugin/marketplace.json:13` — `"Hooks block oversized Read/Bash and route to bulk-reader / code-writer subagents."` 実際のフックは deny + 理由文中のスキル案内のみ（`check-file-size:145`、`check-bash-read:162` の `Use /token-shunt:bulk-reader`）で、サブエージェントを起動しない。`README.md:5` は「フックが自動でサブエージェントを起動するわけではありません」と明記しており、マーケット文言だけが「subagents へ route」するかのように読める。
- **影響**: マーケットプレイス閲覧者への軽微な誤認リスク。`plugin.json:5` の記述（"delegating to Haiku/Sonnet subagents"）は目的の言及として妥当。
- **再現**: 静的確認済み。

### P2 — `check-reader-contract` の捕捉例外が 4 型に限定され、想定外例外は PreToolUse で fail-open

- **証拠**: `plugin/hooks/check-reader-contract:116-117` — `except (OSError, ValueError, TypeError, KeyError)` → exit 2（fail-closed）。それ以外の例外（例: 極端に深いネスト JSON に対する `json.load` の `RecursionError`）→ トレースバック + exit 1。PreToolUse の exit 1 は非ブロッキングエラーなので Read が通過し、契約がバイパスされる。
- **影響**: 入力起因の全既知経路（不正 JSON・欠損 ID・不正形状・状態破損）は exit 2 で覆われており、残るのは内部バグ/到達困難なクラッシュ経路のみ。`tool_input` が通常フラットなため実現可能性は低い。設計 §306 の「ID 欠落や不正形状は診断付き exit 2」との厳密な不一致は、未捕捉例外型に限られる。
- **再現**: 未検証（CLI が実際にそうした stdin を生成できるか不明）— ※統合側で深さ100,000の JSON により RecursionError→exit 1 を再現済み。

## 確認したが問題なし

- **§26.5 必須ケースの完全性**: A 群（`compare-bulk-facts`/`one-line`/`explicit-multifile` が direct+haiku+sonnet+auto の 4 モード、`compare-hook-deny-route`、`compare-code-writer-ok`/`no-ref`、`compare-edit-dense-lines`、`worker-model-invalid`、`writer-verification-levels`、`reader-batch-evidence`/`ambiguous`、`reader-bounds`/`retry-policy`/`writer-bounds`）と B 群（auto-bulk-facts/one-line/explicit-multifile、auto-small-files/known-range/small-writer、auto-large-writer、auto-edit-grep-location/ambiguous、境界 16k-minus/equal/plus・50-lines read・49/50-lines-writer・known-range-deny）が全て `cases.json` に存在。`require_parent_tokens` は設計 §915 の 4 件（大容量読取 3＋大規模生成 1）に正確に宣言（:604,653,724,901）され、judge（:1079-1092）と aggregate（:2013-2019）の両方で欠測 fail。
- **`selected_run_valid` vs `release_eligible`**: `judge.py:2127-2128` で意図的に分離（後者は `planned == mandatory` を要求）。`test_aggregate.py:52-58` が部分成功≠リリース適格を明示テスト。`README.md:225`・配布 `README.md:79` と整合。**部分実行で selected_run_valid=true になり得るのは設計どおり**（`manifest.required` は全カタログ必須＝`judge.py:1985`、部分集合は `planned ⊆ mandatory`）。
- **モデル検査の証拠源**: `agent_resolved_models`（`judge.py:700-736`）は tool_result の `resolvedModel`/`modelsUsed`/raw/JSON text と子 assistant の `model` を読む — これは design §755 が規定する証拠そのものであり、実装上の欠落ではない。`check-agent-model` が起動時に非 haiku/sonnet を deny する一次防止は `test_unreadable_and_model.py:14-50` で検証済み。
- **本文リーク検査の網羅性**: `parent_added_text`（`judge.py:404-437`）は親 assistant の text＋全 tool_use 入力（`input_text` で Agent プロンプト・Write 本文・Bash コマンドをリテラル化）＋親 user メッセージの tool_result テキスト＋認証済み非同期完了を重複排除して集約。`leakcheck`（:1918-1938）は target 本文との >2KiB 連続一致（`contiguous_bytes`、検証付きローリングハッシュ）または 21 連続行を検出し、不明瞭は clean にしない（exit 2）。`run.sh:572-587` は `writer_body_absent` ケースで clean のみ合格。
- **flow_checks.py の強度**: `edit_flow_errors`（:34-87）が「成功かつ一意一致の Grep → 成功した原本 targeted Read（mark 含有・非 partial）→ Edit」の位置順序を要求し、`old_string` が検証済み Read 内容に存在することを要求。`verification_commands`（:151-203）はシェルを実行せず、展開・パイプ・条件を証拠から排除。`verify_writer_boundary`（:311-348）は実際に unittest を baseline+mutation で実行。
- **deny 帰属**: `check-bash-read:54` の `deny()` が `token-shunt:` を自動前置（:668 の `cd` 未解決 deny を含む全経路に帰属）。design:977 と `evals/run.sh:68-82`（`deny_safety`=`token-shunt` 帰属、`deny`=`bulk-reader` 案内）に整合。
- **hooks.json 配線 vs 実装**: 5 スクリプトが `hooks.json`・実ファイル・配布 README（:17-29）・`build-zip.sh`（chmod :10、検証 :45-85）・`TS_HOOKS`（`judge.py:24`）で完全一致。`check-reader-contract` は Pre/Post/Failure:Read に登録され、bulk-reader の `agent_type` 完全一致時のみ動作（:88）。
- **doctor.sh**: ハード失敗は jq 欠落・Bash<4・記録保存失敗のみ（:24,33,241,245）— design §980 の原子記録（同 dir mktemp→mv）と README:235 に整合。`--plugin-dir`+`--setting-sources ""` による隔離プローブ、FORCE=1 でモデル比較を「INVALID」報告、doctor-last-probe.txt（2.1.270）が存在。ライブ確認不能項目は exit code を変えない設計どおり。
- **既知限界の実装整合**: 未知末尾コマンドのパイプ fail-open（`check-bash-read:805` ↔ design:398,808）、`cat <file` 入力リダイレクト・`$''` ANSI-C 引用・Explore/Grep content・逐次 targeted Read 回復は全て README:180-194 / design §15 で文書化済み。`deny_bypass` が Grep 本文取得を検出しない点も design:448 で明示。
- **spoof 防止**: `agent_type` はトップレベルのみ参照（`check-file-size:154`、`check-bash-read:170`、`check-reader-contract:88`）、`tool_input.agent_type` は不読。`evals/run.sh:118-125` にスプーフ回帰テスト。
- **fail-closed**: jq 欠落・不正 JSON・ID 欠落・状態破損・走査予算超過は全て exit 2 / UNDETERMINED→deny（`check-file-size:14-16,99,132`、`check-bash-read:13-15,95,153`、`check-reader-contract:116-117`）。`evals/run.sh:127-184` で実測テスト済み。
- **判定器の fail-closed 伝播**: 壊れた JSONL・不正 tool_input 型・未解決パス同一性・空 manifest・spec/verdict 不一致・`gold_file` 無効・欠測トークンは全て fail（`judge.py:106-119,1047-1056,1276-1278,2003-2019`、`test_runner.py:233-257`）。`release_gate: False`（:2124）で費用は出荷を左右しない。
- **プローブ環境失敗**: load/isolation プローブで init/result 欠落・エラー結果・外来プラグイン・外来フック混入を abort 前に検出（`run.sh:404-479`、CLI ダブルで `test_runner.py:285-328` が検証）。
- **REPL 側の集計健全性**: `suite_cost_usd` の `basis` は「単回・4件・中央値でない」と正直にラベル（:2113）。

## 疑ったが未検証

- `agent_resolved_models` は transcript 記録メタデータの照合であり、CLI が報告した `resolvedModel` とプロバイダ側で実際に動いたモデルの一致までは静的に証明不能（design §755 はこの証拠源自体を規定）。
- `check-reader-contract` の未捕捉例外 fail-open（上記 P2）の到達可能性 — CLI が hook stdin に深いネスト JSON を emit し得るか未確認。
- `routing_checks.py:16` の `_paths` 正規表現は `()` 等をパスから除外 — 括弧入りパス名は分割される。評価 fixture は清浄なパスのみ。
- `bash_mentions_path`/`bash_recovers_body` の basename 照合は同名別 dir ファイルを誤検出し得るが、方向は保守的（過検出）で影響軽微。
- `run.sh:467` の `claude plugin validate .` が意図どおり marketplace ルートを検証するかは CLI ダブル経由のため実 CLI 未検証。
- `test_runner.py:97` の FileNotFoundError は静的に確定的だが、実行による最終確認は未実施。
- 実機挙動全般（実 `claude` 実行結果）は未実行。監査は静的コード＋オフライン判定ロジックの照合に限定。

## 実施できなかった事項

- 実行系検証（`evals/run.sh`、`unittest discover`、`doctor.sh`、`run.sh` 実機実行）は read-only モードのため未実施。
