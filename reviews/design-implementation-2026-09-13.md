# 設計・実装照合と偽陽性チェック（2026-09-13）

## 修正後の状態

ユーザー指示により、3つのサブエージェントと親エージェントで以下の6件を修正した。後続の本文は修正前の再現記録として保持する。

| 指摘 | 修正 | 回帰確認 |
|---|---|---|
| 1. 欠測を合格扱い | 実行ごとのマニフェストと独立した証拠ディレクトリ。予定した全結果・必須ディスク/隔離/トークン証拠を必須化。選択実行成功と出荷評価完了を分離 | 空計画、モード/fixture/証拠欠測の拒否、古い結果の除外、全必須ペアの正常系 |
| 2. 再試行の誤判定 | 初回と再試行を区別し、要求/実モデル、同一パス、前回結果の到着、短い再試行理由、resume禁止を検査 | Haiku→Sonnetの正常系、モデル違反、resume、理由/順序/回数違反 |
| 3. 編集順序 | 対象を一意に特定したGrep結果→原文Read成功→Editの時系列とold_stringを照合 | 先行Edit、未完了Read、無関係/曖昧Grepを拒否。関数定義をGrepして必要範囲を読む正常系 |
| 4. 生成検証 | 各成果物・制御入力について、親の検証コマンドと結果、報告時点、個別の検証段階とpartialを照合 | 検証なし/complete誤報告/制御入力の省略を拒否。正当なMarkdownコードブロックを許容 |
| 5. 生成物持ち越し | モードごとにモデルから見える作業ディレクトリ全体と参照fixtureを再作成。判定・transcriptは外側に保持 | target消去、参照復元、証拠保持、別実行の証拠分離 |
| 6. 曖昧なバッチ制御 | `reader-batch-ambiguous`を実行対象へ追加。Read契約を起動単位にし、境界確認を許容 | 同名TOKENの独立した事実はconfirmed可、根拠のない関係はunconfirmed/partial。重複Readと指定外Readは拒否 |

検証結果: 新規回帰テスト49件、既存judge selftest12件、フック/配布チェック98件が成功。ランナー全体もCLI代替プログラムで4モードを実行し、選択ケースの成功が `release_eligible=true` にならないことを確認した。`bash -n`も成功。

Claude実モデルでの全A/B比較は未実行。これらは評価プログラムの修正・回帰確認であり、プラグインの出荷検証完了やトークン節約の実測を意味しない。再試行理由や関係の正しさに関する自由文の意味判定は完全ではなく、明示された理由・識別子とtranscriptの契約を検査している。

## 修正前のレビュー

正本は `docs/2026-09-12-token-shunt-design.md`（承認済み版、§27 まで）。設計ドラフトや過去レビューを現行要件として扱っていない。フック、スキル、エージェント、配布、doctor、比較評価を確認した。実装の修正は行っていない。

結論: フックとスキルの主要契約は一致するが、比較評価に以下の6件の不整合がある。現状の評価合格だけでは設計上の出荷条件を満たしたと判断できない。

## 検証

- `/tmp/token-shunt-review.2W4msm` にコピーして `evals/run.sh`: **98 pass / 0 fail**。元の ZIP や fixture を再生成せずに確認。
- `python3 evals/compare/judge.py --selftest`: **12件成功**。
- 追加の合成 transcript と集計入力で下記の誤判定を再現。証拠は `/tmp/shunt-controls-f0vegs0o/`。
- コピー上でランナーの実際の `gen_fixtures` / `restore_fixtures` を呼び、生成物の持ち越しを再現。
- Claude の実モデルを呼ぶ比較評価は未実行。以下は評価プログラムの実行結果であり、モデルが実際に違反したという報告ではない。
- この作業環境では `.git` から Git 管理情報を取得できず、コミット差分ではなく現在のファイルを対象にした。

## 1. [P1] 隔離の比較データ不足を合格扱いにする

箇所: `evals/compare/judge.py:1408–1427`、`evals/compare/run.sh:430–438`。

設計 §3.10 / §26.5 は必須ケース・指定モードの成功と必須測定を要求する。集計は存在する verdict だけを列挙し、direct や fixture サイズが無い場合に `iso_ok=None` のまま、`False` のときだけ失敗にする。空の verdict ディレクトリでも終了0になる。

再現: (a) verdict 0件で `aggregate: cases=0 fail_runs=0`、終了0。(b) `delegate_lt_direct_and_fixture` の auto 合格結果だけを置き direct を省くと、`isolation.ok=null` / `missing modes` にもかかわらず終了0。

偽陽性確認: 単一ケース実行を許すこと自体は問題ではない。しかし選択したケースの比較に必要な direct の欠落まで成功とするのは別問題。既存 verdict/spec を起動時に消さないため、過去試行の結果も混ざる。部分評価の成功と出荷ゲート合格を分け、実行マニフェストに対する完備性を確認し、必須隔離の欠測は失敗にする必要がある。

## 2. [P2] auto の正当な Sonnet 再試行を拒否し、禁止された再試行契約は検査しない

箇所: `evals/compare/judge.py:1019–1036`、`evals/compare/cases.json` の `expected_resolved_model` と `retry-policy`。

設計 §26.1 / §26.5 は初回 Haiku、許可理由に限った Sonnet 再試行1回、resume禁止を要求する。B の auto は期待値が `haiku` で、判定器は全起動に同じ値を要求する。一方、A の `retry-policy` は名前と起動数1〜2しか検査しない。

再現: B と同じモデル期待値で Haiku→Sonnet を入力すると2回目を `model ['claude-sonnet'] does not match alias haiku` と拒否。現行 `retry-policy` に Opus指定・`resume`付き Agent を入力すると合格。

偽陽性確認: 前者の制御はモデル判定だけを切り出したもので、B 全体の正答を主張していない。他のチェック以前に正当な再試行を必ず拒否することが問題。起動ごとの初回/再試行を区別し、要求モデル・実モデル・再試行理由・同一パス・resume禁止を検査する必要がある。

## 3. [P1] 編集前の原文確認を、編集後の Read で満たせる

箇所: `evals/compare/judge.py:903–932`。

設計 §11.6 / §26.5 は Grep→原本 targeted Read成功→Edit成功の順序と対象識別を要求する。実装は各ツールの存在と成功を別々に調べるだけで、順序を確認しない。Grep は対象パス・パターン・成功も問わない。

再現: Edit成功→targeted Read成功（原文マーカー入り）→無関係パスへのGrepという入力が `edit_flow=true` で合格。

偽陽性確認: ランナーのディスク比較は最終バイト列を検証するが、「編集前に原文を確認したか」は復元できない。正しい最終結果でも禁止経路なら失敗にする設計なので、ディスク比較では補完できない。

## 4. [P1] 生成検証を実行せず complete と報告しても検証段階ケースが合格する

箇所: `evals/compare/judge.py:956–981`、`evals/compare/cases.json:127–145`、`evals/compare/run.sh` の `verify_levels`。

設計 §11 / §27.1 は minimal / syntax を partial とし、親の実検証を必須にする。現行ケースは最終回答中のファイル名とレベル名を確認するだけ。親 Bash の実行条件がなく、生成物への complete 禁止もない。制御サンプルは名前を回答から省くと検査自体を飛ばせる。

再現: code-writer Agent 1回、親 Bash 0回、回答を `vl_config.json verification: syntax status: complete` と Markdown/YAML の `minimal status: complete` にすると、現行ケースの transcript 判定が合格。

偽陽性確認: ディスク側は JSON parse と Markdown/YAML 非空だけを調べる。適切なファイルが存在すれば、親の検証未実行・誤った完了報告を拒否する補助判定はない。各成果物の検証ツール結果・報告段階・partial、および全制御サンプルへの回答を必須にする必要がある。

## 5. [P2] モード間で生成 target が残り、同じ初期状態で比較できない

箇所: `evals/compare/run.sh:35–42`、`restore_fixtures`、`:385–386`。

設計 §13 / §26.5 は各試行の fixture 初期状態を揃え、生成物を持ち越さないことを要求する。再作成するのは `$CWD0` と参照 fixture で、`$TMP/large_test.py` / `small_cfg.json` / `w49.py` / `w50.py` / `vl_*` は残る。`restore_fixtures` が消す出力は `$FIX/codegen/out/*` だけ。

再現: コピー上で `gen_fixtures` → `$TMP/large_test.py` を作成 → `gen_fixtures` → `restore_fixtures` と実行すると `ARTIFACT_SURVIVES_RESET`。

偽陽性確認: Claude の cwd は初期化されるが、対象ファイルはその外側の `$TMP` にある。既存 target を読む worker 契約により次モードの入力・トークン量が変わり、生成しなくても存在チェックを満たせるケースが生じる。対象生成物もモードごとに初期化する必要がある。

## 6. [P2] 必須の曖昧なバッチ統合制御がケースに接続されていない

箇所: `evals/compare/run.sh` の `gen/collide` fixture 生成、`evals/compare/cases.json` の `reader-batch-evidence`。

設計 §26.5 / §27.4 は、一意な参照を持つ正答ケースに加え、同名シンボルで曖昧な場合に境界確認または unconfirmed / partial へ進む制御を要求する。`collide/alpha.py` と `beta.py` は生成されるが、ケースの prompt / fixtures に使われていない。実際の batch ケースは Rails の正答経路だけ。

偽陽性確認: `gold_confirmed` は回答内の gold と対応パスを確認するが、曖昧さへの対応を試す入力の代わりにはならない。また `child_reads_once` は全起動合計で各パス1回を要求するため、設計で認める境界確認時の再読も表現できない。曖昧な制御を実行対象へ追加し、Read上限を起動単位で検証する必要がある。

## 撤回・不具合に数えない事項と未検証範囲

- 未知の末尾パイプ、`sed` / `python`、スライド Read のフック通過: §4 / §15 の明示的な対象外。新規の封鎖要件として報告しない。
- 巨大ファイルを子が1回で読み切れない: 省略時 partial は設計済み。対応範囲拡張を不整合としない。
- 費用未測定・実機未完了: README は開発中・release-readyではない・トークン節約未確認と明示。未検証出荷を実行したとは判断しない。PR3 の48実行や費用集計の未完を現在のリリース違反と混同しない。
- `3>` などで stdout を保護する保守判定: 過去レビューに設計文言の補正候補として記録済み。今回の新規指摘には重複計上しない。
- doctor は登録確認と手動dump案内までで、設計 §7 / §12 の effort / maxTurns / 実モデル互換性検証・最低対応版の記録は未完。README も限定した実装範囲を説明している。上記6件とは別の、出荷前に残る検証作業。
- `parent_input_tokens` は最終 result の usage を採用している。その値が対象CLIで親のみの累積usageであるかは今回確認していないため、正しいとも誤りとも断定しない。実機の親メッセージusageとの照合が必要。
