# 撤回済みレビュー履歴

現行要件ではない。節番号は当時の参照を保存している。正本は [現行設計](../2026-09-12-token-shunt-design.md)。

## 16. レビュー裁定の記録

§17〜25 は変更履歴であり、当時の決定を記録する。現行仕様は §1〜15 と §26。履歴中の関連探索、バイト窓編集保証、再利用必須も今回の改訂で撤回した。履歴中の Sonnet 固定・費用最適化対象外・Haiku 比較不要・無条件再起動は §26 で撤回した。

Critical 相当は初版で閉じた。Major のうち Explore 封鎖・Grep フック・Write フックはユーザー既決で既知の限界。スキル/エージェント改名は却下（名前空間が違う。呼び出しは修飾名に固定）。

## 17. 【履歴・現行要件ではない】実装前修正（2026-09-12）

Explore / Grep / Write 非強制は既知の限界のまま。以下 5 件を仕様に入れた。

| # | 深刻度 | 内容 |
|---|---|---|
| 1 | P1 | 通過は決定なしの exit 0。`permissionDecision: "allow"` 禁止。対象外 Bash の権限確認を省略しない |
| 2 | P1 | `head`/`tail` は行数指定が小さくても対象範囲の `range_bytes` を見る。1 行 70KiB の `head -n 1` は deny |
| 3 | P2 | targeted Read は平均行長ではなく `range_bytes(offset, limit)`。偏り fixture を eval 必須 |
| 4 | P2 | 単一ファイルは 200KiB 合計の例外。200KiB 超は path + 行範囲の順次呼び出し（§18 で撤回） |
| 5 | P1 | marketplace.json に必須 `owner.name`。検証は構文だけでなく marketplace スキーマ / `claude plugin validate` |

フック eval と marketplace スキーマ検証は実装時に機械化する。Claude 実機の比較 eval は開発中 skip 可、リリース時は成功必須（§19）。

## 18. 【履歴・現行要件ではない】再レビュー修正（2026-09-12）

実装前修正の 5 件のうち 4 件は仕様上解消。巨大ファイルの均等行分割は不十分だった。Explore / Grep / Write 非強制は既知の限界のまま。以下 4 件を入れた。

| # | 深刻度 | 内容 |
|---|---|---|
| 1 | P1 | `head`/`tail` は解釈できる `-n N` / `-c C` だけ範囲判定する。`+N`・負数・混在・重複は全文閾値へ戻す。`head -c 70000` と `tail -n +1` を eval 必須 |
| 2 | P2 | 単一ファイルはサイズを問わず 1 ワーカーに path だけ渡す。親の均等行分割を撤回。子が Grep/Read で探索する |
| 3 | P2 | 全文が両閾値以下なら `limit` を見ずに通過。`Read(limit=400)` の 10 行ファイルを eval 必須 |
| 4 | P2 | 同一質問の直接 vs 委譲を比較する eval。正確性は合格条件。親トークン・合計・時間は記録（合計減は合格条件にしない） |

§17 の修正 4（行範囲の順次呼び出し）はこの節で置き換える。複数ファイルの 8 パス / 200KiB バッチは残す。

Spotify 記事との対応は §21。Portal Modes は対象外。親に細かな分割管理をさせない。

## 19. 【履歴・現行要件ではない】検証契約の修正（2026-09-12）

フック対象の拡大はしない。意図した経路で動き、有用な結果を返したと証明する側を固めた。Explore / Grep / Write 非強制は既知の限界のまま。

| # | 深刻度 | 内容 |
|---|---|---|
| 1 | P1 | Claude 未導入は比較 eval を skip。ロード失敗は fail。リリースは実機比較 eval の成功が必須 |
| 2 | P2 | transcript で直接モードの親 Read、委譲の `subagent_type`、子→親テキスト契約を検証。フック deny → 委譲の実機ケース `compare-hook-deny-route` を必須に |
| 3 | P2 | `parent_added_chars`（親へ追加された量）と `usage_parent` / `usage_tree`（累積使用量）を分離。cache は分けて記録。message id で重複排除。実モデル ID を記録。Agent `totalTokens` は全実行合計に使わない |
| 4 | P2 | 入力 8 パスは起点のみ。子は関連先を追う。`confirmed` / `inferred` / `unconfirmed` を契約に。Rails の model→concern→job を `compare-rails-follow` で検証 |

§18 の比較 eval は、本節の経路契約・指標分離・リリースゲートで置き換える。

## 20. 【履歴・現行要件ではない】比較 eval 判定の修正（2026-09-12）

| # | 深刻度 | 内容 |
|---|---|---|
| 1 | P2 | `compare-hook-deny-route` は「First use the Read tool on \<path\> with no offset or limit」を明示する。スキル名は書かない。事前委譲は正常だが、このケースでは Read→フック deny を必須にする |
| 2 | P2 | フック経路の証拠は token-shunt 自身の `permissionDecision: "deny"` と誘導 reason。通常の Read エラーは不可。直接モードは対象 Read（Rails では関連ファイルの Read/Grep も）の tool_result が成功していること |

`TOKEN_SHUNT_HOOK_LOG` は比較 eval のフォールバック。一次証拠は `--include-hook-events`。本番の通過/deny は変えない。

## 21. 【履歴・現行要件ではない】実行不能検証と運用穴の修正（2026-09-12）

費用最適化対象外の方針は §26 で撤回済み。編集・探索の現行範囲は §11〜13 を正本とする。

公式ドキュメントで裏が取れた前提（plugin `agent_type` は `token-shunt:bulk-reader`、exit 2 は JSON で上書き不可、通過は空 stdout、`"allow"` は権限確認省略、marketplace の `owner.name`、`--plugin-dir` の zip 配置、plugin agent の `effort`）は維持。

記事との関係: **親から大量 I/O を外す構造を踏襲する。安価ワーカーへのルーティングによる費用最適化は対象外とし、親コンテキスト隔離を目的とする。** 「方向性のずれは無い」とは書かない。

| 観点 | 評価 |
|---|---|
| 大量読み取りを子に渡し、親には要約だけ返す | 一致 |
| フックで誘導し、スキルで呼ぶ | 一致 |
| 参照必須の定型生成を直接ファイルへ書く | 一致 |
| 編集・難しい推論を親に残す | 方針は一致。v0.1 が保証するのは targeted Read がフック通過するときと、先頭 `head -c` / EOF に達した末尾 `tail -c`。巨大行の先頭窓外は対象外（記事の「親が対象箇所を直接読む」に沿う。例外をプラグインで解かない） |
| 安価なモデルへ処理を移す | 意図的な変更。sonnet 固定では費用効果を保証できない。記事の約 90% は bulk-read で Claude に渡すトークン削減であり、安価モデル単価の削減率ではない |
| 指定ファイルを渡す一回の処理 | 関連ファイルを自律探索する子へ拡張。実行量が増える |

記事の費用レバー（安価ワーカー）は意図的に捨て、§1・§12 に書いた。haiku に落とすと path_ok が先に壊れる、は仮説（比較測定なし）。

| # | 深刻度 | 内容 |
|---|---|---|
| 1 | P1 | 比較 eval 起動は `-p --output-format stream-json --verbose --include-hook-events --forward-subagent-text`。子の tool_use は verbose stream の `parent_tool_use_id`、無ければ `agent_transcript_path` |
| 2 | P1 | フック deny の一次証拠は `--include-hook-events` の `hook_response`。`TOKEN_SHUNT_HOOK_LOG` はフォールバック |
| 3 | P1 | `range_scan` は `MIN_LINES+1` / `MIN_BYTES+1` で打ち切る。全文バイトは `st_size`。戻り値に区間合計は要求しない。読み飛ばしの時間保証は §22 の走査予算で置き換え |
| 4 | P1 | Read は画像 / PDF / `.ipynb` を除外。eval 必須。Bash の `cat` は除外しない |
| 5 | P2 | Bash `MIN_BYTES` 65536 は維持。30k inline 上限との二重防御を §15 に書く。eval 根拠文を訂正 |
| 6 | P2 | SessionStart `check-jq` で jq 欠落を 1 回警告（block 不可） |
| 7 | P2 | `"args": []` は exec form。シェバン＋実行ビット。zip 検証必須 |
| 8 | P2 | パイプ全通過と `|&`（bash ではパイプ。早期通過にはしない）を §10・§15 に書く |
| 9 | P2 | `limit=350` 逐次 Read で全文回収できることを §15 に書き、`parent_added_chars` で観測 |
| 10 | P2 | スキル frontmatter の `agent:` を落とす（`context: fork` 無しでは無効。fork は設計と衝突） |
| 11 | P3 | ワーカー sonnet 固定の根拠を §12 に書く。haiku 必須 eval は増やさない。path_ok が先に壊れるは仮説 |
| 12 | P3 | `bash-head-full` の fixture を 400 行×50 バイトに固定し、期待を通過と断定 |
| 13 | P3 | Bash フックの code-writer allowlist と Bash 側 worker eval を落とす。Read 側だけ残す |

## 22. 【履歴・現行要件ではない】比較隔離・編集例外・走査予算・隔離合格・code-writer 実機（2026-09-12）

Explore / Grep / Write 非強制は既知の限界のまま。以下 5 件を仕様に入れた。

| # | 深刻度 | 内容 |
|---|---|---|
| 1 | P1 | 比較 eval の直接モードは token-shunt 未ロード、委譲はロード。`--bare` を第一選択。親モデル・権限・fixture は揃える。`system/init.plugins` で検証。1 行 70KiB の直接 Read 成功を成立させる。OAuth 代替の詳細は §23 |
| 2 | P1 | 編集・デバッグは委譲しない。`Read(limit=1)` はフックのバイト閾値だけ外す。原文取得の保証は §23 のバイト窓 |
| 3 | P2 | `range_scan` に走査予算（既定 8MiB / 2s）。開始行までの読み飛ばしを含む。判定不能は deny。timeout 10s の fail-open は既知の限界として残る |
| 4 | P2 | 代表的な大容量ケースの isolation_ok を合格条件にする。単位は §23 で UTF-8 バイトに統一。合計費用減は任意のまま |
| 5 | P2 | `compare-code-writer-ok` と `compare-code-writer-no-ref` を必須にし、リリースに含める。成果物は §23 で unittest 実行を必須にする |

§13 の起動コマンドは本節の直接/委譲の分離で置き換える。§21 の「方向性のずれは無い」は本節の目的文で置き換える。§21 修正 3 の「timeout を全走査で踏まない」は走査予算＋既知の限界に置き換える。

## 23. 【履歴・現行要件ではない】編集バイト窓・生成テスト実行・隔離単位・設定スコープ（2026-09-12）

Explore / Grep / Write 非強制は既知の限界のまま。以下 4 件を仕様に入れた。

| # | 深刻度 | 内容 |
|---|---|---|
| 1 | P1 | `Read(limit=1)` は原文取得を保証しない（公式: 明示的 limit がトークン上限超でエラー。走査予算は末尾の limit=1 も deny）。`confirmed` に `byte_start`。親は `dd` で最大 8192 バイトを temp へ書き Read する。`compare-edit-byte-window` と `compare-edit-long-line` を必須 |
| 2 | P2 | code-writer の成果物は識別子検査では足りない。`greet("Ada") == "Hello, Ada!"` / 空文字は `ValueError` を固定し、eval ランナーが `python -m unittest` で 1 件以上実行・成功したあと、`greet` を壊して再実行し失敗することを必須にする。本文は親へ渡さない |
| 3 | P2 | isolation_ok は `parent_added_utf8_bytes` と fixture の UTF-8 バイト数を比較する。`parent_added_chars` と `st_size` を混ぜない |
| 4 | P2 | `CLAUDE_CONFIG_DIR` は User スコープだけ移す。Project / Local は `<cwd>/.claude/`。OAuth 代替は空 `--setting-sources`＋`.claude` の無い一時 cwd＋`--add-dir`。他フックは `hook_started` / `hook_response` で検出。managed は切れない |

§22 の limit=1 保証と isolation の文字/バイト混在、および `CLAUDE_CONFIG_DIR` 単独の代替は本節で置き換える。

## 24. 【履歴・現行要件ではない】編集保証経路（byte-span / 原本既読 / 行キャップ）（2026-09-12）

費用最適化対象外の方針は §26 で撤回済み。編集・探索の現行範囲は §11〜13 を正本とする。

Explore / Grep / Write 非強制は既知の限界のまま。以下 3 件を仕様に入れた。

| # | 深刻度 | 内容 |
|---|---|---|
| 1 | P1 | 子の tools は Read / Grep / Glob のまま。公式 Read は行番号、公式 Grep `content` はパス・行番号・行内容であり、バイトオフセットは返らない。`plugin/lib/byte-span` が `range_scan` と同じ改行規則で `byte_start` と **必須の `byte_len`** を機械計算する。子は path / `start_line` を返し、バイトを算術しない。LF / CRLF+日本語 / 行キャップのフック eval 必須 |
| 2 | P1 | temp の Read 成功は原本 Edit 成功ではない。公式の read-before-edit は原本 Read（PARTIAL 不可）またはパイプ・リダイレクト無しの `head`/`tail`/`cat`/`grep` 等。`dd` は含まれない。保証経路は先頭 `head -c` と末尾 `tail -c`（リダイレクト無し）、および原本の targeted Read。比較 eval は値の回答ではなく原本 Edit 成功と対象以外の不変（期待バイト列一致）まで見る。`allowedTools` に Edit を足す。Opus 4.6 / Haiku 4.5 / より古いモデルの未読 Edit は保証しない |
| 3 | P2 | 「8KiB 以下なら両閾値以下」は不成立（`a\n` × 4096）。`TOKEN_SHUNT_EDIT_WINDOW_LINES` 既定 64（`MIN_LINES` で切る）。抽出はバイトと行の両方で制限する。temp が行超過なら targeted Read。`read-edit-window-dense` と `compare-edit-dense-lines` を必須 |

§23 の「`confirmed` に `byte_start`。親は `dd` で temp を Read。temp の `st_size` は窓以下なので両閾値以下」は本節で置き換える。

## 25. 【履歴・現行要件ではない】巨大行対象外・末尾 fixture・Bash 引用・生成検証（2026-09-12）

費用最適化対象外の方針は §26 で撤回済み。編集・探索の現行範囲は §11〜13 を正本とする。

Explore / Grep / Write 非強制は既知の限界のまま。記事は編集を親が対象箇所を直接読む方針であり、v0.1 は targeted Read で扱えない編集を広げない。以下 4 件を仕様に入れた。

| # | 深刻度 | 内容 |
|---|---|---|
| 1 | P2 | `byte-span` は行の先頭から最大 `EDIT_WINDOW_BYTES`。行内シークも検索文字列も無い。巨大行の先頭窓より後ろは取得・編集対象外。`truncated=true` で窓に `old_string` が無ければ Edit しない。`byte-span-long-line-trunc` を必須（先頭 eval だけでは検出しない） |
| 2 | P2 | 末尾 `tail -c` は JSON が `byte_start + byte_len >= st_size` のときだけ。`compare-edit-byte-window` のマークは**最終行**（後ろに空行を置かない）。`line_count` 省略時 1。`byte-span-eof-last-line` を必須 |
| 3 | P2 | Bash は引用を踏まえて演算子を見る。引用内の `\|` はパイプではない。複合セパレータがあるときリダイレクトは早期通過にしない（対象コマンドに属するときだけ）。複合は解析せずサイズ対象は全文閾値。`bash-quoted-pipe-name` と `bash-compound-redirect` を必須 |
| 4 | P2 | code-writer の製品手順は生成→要約で終わらない。親が spec の検証コマンド（`.py` 既定は `python -m py_compile`、テストなら unittest）を Bash し、その結果で完了判定する。本文は vis しない。`compare-code-writer-ok` は親の検証 Bash 成功を path_ok にする |

§11.6 の「再呼び出しで任意地点の窓」と §10 の記号包含パイプ判定、および code-writer の要約完了は本節で置き換える。

