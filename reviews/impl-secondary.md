# 実装 2次レビュー（2026-09-13）

対象: PR1 実装。観点: 堅牢性・可搬性・eval 品質・ドキュメント整合（1次の仕様適合と重複しない独立 sweep）。

判定: **合格**（指摘はすべて保守方向または spec 意図通り）。

## 指摘・観察

| ID | 種別 | 内容 | 裁定 |
|---|---|---|---|
| S-1 | 保守方向 | `cat large >out 2>&1` は deny。spec は早期通過に「`2>&1` / `>&` / `&>` が無い」を要求するため、実害は無いが慣用句で over-block。将来の設計改訂で緩和余地あり（stderr→stdout→file は親に出ない） | spec 順守として受容。synthesis に記録 |
| S-2 | 同値 | 文末の `&` を複合セパレータ扱い（spec は「文末以外の `&`」）。空の末尾セグメントは target を持たず判定同値 | note |
| S-3 | 可搬性 | `stat -c`（GNU）→ `stat -f %z`（BSD）→ `wc -c` の fallback あり。`date +%s%3N` も `EPOCHREALTIME` 無し時の fallback あり | OK |
| S-4 | 安全性 | deny JSON・hook log はすべて `jq -nc --arg` 生成。reason に生パスを出さない（§10-6） | OK |
| S-5 | 性能 | `tail_scan` は `tail` を最大 3 回起動。各行は N で束縛。`head -c BUDGET+1` で出力計測を cap | OK |
| S-6 | 契約 | `check-jq` は stdin を読まない。SessionStart はブロック不能なので警告 JSON + exit 0 で正しい | OK |
| S-7 | 堅牢 | 既存だが読み取り不可のファイルは `[[ -f ]]` 通過後に probes 失敗 → 0/0 → pass。実 Read が error になるため実害なし | 受容 |
| S-8 | eval 品質 | `run.sh` の `env` フィールドは空白を含む値を非対応（`read -ra` 分割）。eval 用途では許容 | note |
| S-9 | eval 品質 | 本ラウンドで deny 期待に「reason が `bulk-reader` を名指し」（§3-1）を追加検査。`deny_budget` は scan-budget 句も要求 | 改善済 |
| S-10 | eval 品質 | `check-jq` の jq 存在時（exit 0・空出力）ケース、agent_type 偽装ケース、`env` 上書きケースを追加 | 改善済 |
| S-11 | spec 整合 | `TOKEN_SHUNT_MIN_LINES=0` は「0 は 0」で全ファイル deny、負値は invalid → 既定値。どちらも spec 通り | OK |
| S-12 | eval 再現性 | fixture はすべて生成物・決定的。`big-scan.txt`（>9MiB）は size キャッシュで再生成を回避し、リポジトリに置かない（§13 通り） | OK |
| S-13 | ドキュメント | README: jq 必須・`agent_type` を stdin に載せる版・Spotify shunt 併用禁止・90% 非請求・既知の限界を列記。hooks.json は exec form + timeout。整合 | OK |

## 残課題（PR2 以降の範囲）

- フック eval は stdin JSON → 決定の静的検証で、実機の `agent_type` 配線は未検証（doctor は PR2 の範囲、§13/§26.6）
- compare eval・親トークン計測は PR2/PR3。現時点で費用削減は未検証
