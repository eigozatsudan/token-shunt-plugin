# 設計・実装 再照合と偽陽性チェック（2026-09-13, 再実行）

正本: `docs/2026-09-12-token-shunt-design.md`（§1〜15, §26〜27）。
過去レビュー: `reviews/design-impl-*-2026-09-13.md`, `reviews/operational-readiness-2026-09-13.md`。
本ファイルは HEAD `3b0f0ad` 時点のコードを設計と再照合し、出た指摘を自分でコード確認して裁定した記録。実装は変更していない。

## 実行した検証

- `bash evals/run.sh` → **110 pass / 0 fail**
- `python3 -m unittest discover -s evals/compare -p 'test_*.py'` → **55 OK**
- `python3 evals/compare/judge.py --selftest` → **all checks passed**
- 設計文から起こした追加プローブ（eval に無い入力）: `offset=0` / 非整数 `limit` / 非整数 `offset` / `MIN_LINES=0` / `less`・`more` の大ファイル / `agent_type=token-shunt:code-writer` + `cat large` / 大文字 `.PNG` → **全件が設計どおりの deny / pass**
- 実機 A/B 比較（`evals/compare/run.sh`）は未実行（従来どおり認証依存）

## 一致している範囲（差分なし）

- `check-file-size` / `check-bash-read` / `check-jq`: jq fail-closed、env 既定と `0`/負の扱い、トップレベル `agent_type` のみの完全一致 allowlist（`tool_input.agent_type` は無視）、`limit=1` 例外なし、`undetermined=deny`、除外拡張子、通過は空 stdout（`allow` を出さない）
- Bash: 引用対応の演算子スキャン、コメント除去、複合セパレータ優先、パイプ末尾判定（`head`/`tail` はバイト形式のみ通過）、非縮約末尾での全段検査、stdout リダイレクト早期通過の限定、先行 `cd` 追跡
- `hooks.json` exec form / `plugin.json` / `marketplace.json` は設計 §7 の全文と一致。`build-zip.sh` の実行ビット検証あり
- スキル 2 本に `agent:` / `context: fork` なし。`--worker-model` 固定文面あり。agent frontmatter（model/effort/maxTurns/tools）は §12 と一致
- §13 / §26.5 の必須ケース ID は `evals/hook-evals.json` / `bash-hook-evals.json` / `compare/cases.json` に揃っている

前回 FP レビューの真陽性 3 件は**現行コードで解消済み**を確認した:
`quote_leak` は fixture 非依存の fence / 20 行超検査になり `child_mentions` も入った、
`auto-routing-boundary-16k-plus` に `parent_no_full_read` + `child_reads_once`、
`reader-batch-evidence` / `reader-bounds` に `child_no_body` が入った。

## 真陽性

### 1. doctor が §7 / §12 の検証契約を満たさない

- 箇所: `scripts/doctor.sh`
- 設計 §7: doctor は「agent_type だけでなく、呼び出し時モデル指定、Haiku/Sonnet の実モデル、effort、maxTurns の partial 終了も検証し、**実装時に最低対応版を記録する**」。§12 も「`effort: low` が使えること、`maxTurns` と実モデル解決を doctor と実機 eval で確認する」
- 実装: jq / `claude --version` 出力 / `FORCE=1` 警告 / plugin・agent 登録プローブ / hook stdin の手順文のみ。要求モデルと `resolvedModel` の照合、`effort`、maxTurns partial、最低対応版の記録が無い
- FP チェック: §14 の README 向け doctor 列挙（jq / FORCE / agent_type）は満たすので「何も無い」ではない。ただし §7・§12 の要求は別に立っており、少なくとも「最低対応版の記録」は認証なしでも書ける。→ **真陽性（severity: suggestion）**

### 2. README に §14 の必須文が欠けている

- 箇所: `README.md`
- 設計 §14: 「bulk-reader の subagent は 1 起動につき明示最大 3 パスを各 1 回 Read・**maxTurns 4**。**関連探索と再利用は v0.1 対象外**」
- 実装: Skills 節に「max 3 explicit paths per invocation, each read once」はあるが、`maxTurns` の語も、関連探索・再利用が v0.1 対象外である一文も無い（`grep -i 'maxTurns|reuse|resume'` で 0 件）
- FP チェック: Known limits 節にも無い。他の §14 必須項目（費用未証明、検証段階、閾値、jq、`shunt@portal` 併用禁止、既知の限界、`allow` を出さない、環境変数、画像/PDF/ipynb 除外）は揃っている。→ **真陽性（文書欠落）**

### 3. §13 の「スキル/エージェント RED」ケースが無い

- 箇所: `evals/compare/cases.json`
- 設計 §13: 「スキル無し（または『本文を返すな』契約無し）の子がコード引用を最終メッセージに載せることを **1 ケースで確認**し、契約ありで載せないことを 1 ケースで確認する」
- 実装: 契約あり側（`child_no_body`）は多数あるが、契約なし側の対照ケースが 0 件（`general-purpose` / `Explore` / 無契約子を使うケースが `cases.json` に存在しない）
- FP チェック: §13 は「フック eval が先」と書いており順序の猶予はあるが、PR2 の成果物である `cases.json` は既に A/B とも完成しているため、意図的な後回しの痕跡が無い。→ **真陽性**（検出力の欠落。`child_no_body` 判定器そのものが効くかの対照が無い）

### 4. `writer-verification-levels` に `requirements` の正例が無い

- 箇所: `evals/compare/cases.json`（`expect.delegate.verification_level` は `syntax` / `minimal` のみ、`verification_controls` は 3 件とも `forbid_levels: [requirements]`）
- 設計 §26.5: 「必須キー/値を検査する受入条件の成功時**だけ** requirements」「ランナーは…**誤完了・誤拒否**を検出する」
- 実装: 誤完了（requirements を名乗る）側は落ちるが、正しく受入条件を検査したときに `requirements` と報告できるかの正例が無い＝誤拒否側が観測されない
- FP チェック: 他ケースで `requirements` を要求するものは無い（`compare-code-writer-ok` は unittest 成功を見るが `verification_level` を assert しない）。→ **真陽性**

### 5. `auto-edit-grep-location` に「Grep 曖昧 → 非 Edit」の制御ケースが無い

- 箇所: 同上（正答ケース 1 本のみ、`disk_check: edit_hint`）
- 設計 §26.5 末尾: 「**Grep が曖昧な制御ケースは非 Edit を期待し、実メソッド識別の正答ケースとは分ける**」
- FP チェック: `reader-batch-ambiguous` は bulk-reader 側の曖昧さで、Grep→原本 Read→Edit 経路の曖昧さではない。→ **真陽性**

### 6. `writer-bounds` が §26.3 の 16 ファイル上限を見ない

- 箇所: `expect.delegate` は `agent_calls_max: 4` と `child_tool_budget: 20` のみ
- 設計 §26.3: 「内容確認は**最大 16 ファイル**、Read / Grep / Glob 合計 20 回を指示上の上限とし、transcript 超過は fail」
- FP チェック: 800 字上限は `compare-code-writer-ok` / `compare-code-writer-no-ref` の `child_msg_max: 800` で見ているので「800 字が未検査」は**偽陽性として撤回**。残るのは 16 ファイル上限のみ。→ **真陽性（縮小）**

### 7. bulk-reader 側に §26.3 の停止・上限文言が無い（軽微）

- 箇所: `plugin/agents/bulk-reader.md` / `plugin/skills/bulk-reader/SKILL.md`
- 設計 §26.3: 「最終回答に `status`/`stop_reason` を**既存の文字数上限内で**含める。**強制終了で回答が無い場合も partial**」「**上限後は部分結果と未完了範囲を伝える。別 agent 名や resume で迂回しない**」
- 実装: code-writer 側には "inside the 800 character maximum" / "Forced stop without a Write still returns `partial`" / "Shared cap …After the cap, report partial…Do not bypass via another agent name or resume" がある。bulk-reader 側は起動**前**の 4 回チェックのみで、強制終了 partial と上限**後**の扱い・迂回禁止が無い
- FP チェック: 4000 字上限と `status` 併記は同じ「最終回答」への指示なので「上限内」は読み取れる（この部分は弱い）。強制終了 partial と上限後の扱いは文面が実在しない。→ **真陽性（severity: suggestion）**

## 偽陽性・対象外（検討して落としたもの）

| 検討した指摘 | 裁定 | 理由 |
|---|---|---|
| deny reason が `lines=` を省くことがある（§9 の骨子と不一致） | 偽陽性 | `st_size > MIN_BYTES` のとき §8.7 が「行を数えない」、§8.6 が「全区間合計を測って埋めない」と命じている。実装は設計の優先側を採っている |
| `echo $(cat large)` が通過（`bash-subst-cat-pass`） | 対象外 | §10-5 の「先頭トークンが対象コマンドでなければ通過」どおり。README の既知の限界に記載あり |
| 複合内の `head -c 100 large` が全文閾値で deny されうる（誤拒否） | 対象外 | §10-4 が複合では「ステップ 6・§8.7 の全文閾値」と明示。設計どおりの fail-closed |
| `3>` を早期通過にしない | 対象外 | 実装は stdout（fd 省略または 1）のみ早期通過。設計文言より保守的で、判定を逆転しない |
| 未知の末尾コマンドへのパイプが通過 | 対象外 | §4 / §15 の意図した fail-open |
| `--bare` を使わず `--setting-sources ""` + 空 cwd | 偽陽性 | §13 の OAuth 代替そのもの |
| PR3 の 48 実行が未実装 | 対象外 | §26.6 の PR3。README は費用削減をうたっていない |
| `auto-routing-boundaries` が 7 ID に分割 | 偽陽性 | 設計が要求する入力（16KiB 直前/一致/直後、49/50 行、既知区間 deny）は全部実行対象 |
| 走査時間判定が有界走査の**後** | 対象外 | §8.6 実装補足と §15 が残差として明記済み |
| `last-run.json` が失敗ログ | 対象外 | 認証依存。README が release-validated でないと明示 |

## 未検証（今回も残る）

- 実機 A/B 比較全件（`evals/compare/run.sh`）、モデル解決・課金・トークン集計
- `result.usage` が対象 CLI で親のみの累積である点の実機照合
- doctor の live dump
