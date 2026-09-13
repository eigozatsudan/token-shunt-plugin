# 実装レビュー突合 + 偽陽性チェック（2026-09-13）

1次: Critical 2 / Major 6 / Minor 2 ＋ note 4。2次: 指摘 13 件（修正要 0・受容/note）。敵対: 真陽性 5（うち Critical 1）＋ 設計許容 fail-open 確認。

## 偽陽性チェック（各指摘の実機再現 → 裁定）

| 指摘 | 再現 | 裁定 |
|---|---|---|
| `n=0` 走査不能（P-1） | 全 Bash ケースが誤通過で再現 | **真陽性** → 修正済 |
| `[[ =~ ]]` syntax error（P-2） | 全 Bash が exit 2 | **真陽性** → 修正済 |
| 引用トークン消失（P-3） | `cat 'large\|name.txt'` pass で再現 | **真陽性** → 修正済 |
| 整数 wrap（P-4/A-2） | `head -c 10^19`・`limit=10^20` で負値 pass を再現 | **真陽性** → 15 桁 cap |
| `--` 未対応（P-5/A-5） | `cat -- -weird.txt`（70KB 実ファイル）が pass で再現 | **真陽性** → 修正済 |
| `3>` 早期 pass（P-6/A-3） | `cat large 3>/dev/null` が pass で再現 | **真陽性** → fd=1/無指定のみ clean。spec 文言「直前が 2 でも & でもない」は fd>1 を clean に読める不十分さがあり、設計意図（stdout redirect のみ）に従い厳格化。**設計本文の文言修正案として記録**（変更は承認ハッシュ失効を伴うため本 PR では実施しない） |
| パイプ末尾解釈不能（P-7/A-4） | `cat large \|`・`... \| head 'unclosed` が pass で再現 | **真陽性** → fail-closed 先頭判定 |
| detached `>\|`/`&>>`（P-8） | リダイレクト先の誤収集（保守方向） | **真陽性** → 修正済 |
| UNDETERMINED reason 欠落（P-9） | scan-budget 句が出ないことを確認 | **真陽性** → 修正済 |
| allowlist 偽装（A-1） | `tool_input.agent_type` で Read/Bash とも bypass を再現 | **真陽性（Critical）** → トップレベルのみ + spoof eval 2 件 |
| `head -- -n5 large` の嫌疑 | 再検討: `-n5` は `--` 後の被演算子ファイル。実 head は `large` を既定 10 行で出力 → pass は**正しい判定**（旧実装も verdict は同じ。理由の正確性のみ改善） | **偽陽性**（指摘自体は取り下げ、`--` 対応は P-5 で正当化） |
| `cat large >out 2>&1` の deny | 親に出力ゼロだが spec が `2>&1` 非存在を要求 → over-block | **偽陽性**（spec 順守の保守 deny。設計改訂で緩和余地として S-1 に記録） |
| `cat large \| wc -l` の pass | §10-4・§15 が意図する fail-open | **偽陽性**（設計選択。既知の限界として README 記載済） |
| 文末 `&` | 空セグメントで判定同値 | **偽陽性**（note のみ） |
| unreadable file pass | 実 Read が error で終了 | **偽陽性**（実害なし） |
| `jq -e` が `null`/`false` を exit 2 | spec リテラル | **偽陽性** |
| `bash -c`/`xargs`/`dd`/`$(...)`/未知末尾パイプ/スライド Read/Grep・Explore・Write・`@file`/env 弱化 | すべて再現 | **設計許容 fail-open**（§4・§10-4・§15。新規封鎖は追加しない） |

## 実施した修正まとめ（本レビューラウンド）

- `check-bash-read`: ローカル初期化順序、`[[ =~ ]]` regex、quoted `have`、15 桁 int cap、`--`（3 箇所）、fd リダイレクト分類（`N>`/`>\|`/`&>>`）、パイプ末尾 fail-closed、`bash_reason` 引数整理
- `check-file-size`: 15 桁 int cap（env/limit/offset）、`agent_type` トップレベルのみ
- `evals/run.sh`: `cd || exit`、env フィールド対応、deny reason の `bulk-reader` 名指し検査、check-jq present ケース、spoof ケース 2 件
- eval JSON: +20 ケース（fd redirect、`>|`、`--`、巨大値、パイプ末尾 edge、env 上書き、偽装）

## 最終検証

- `bash -n` 全スクリプト: OK
- `./evals/run.sh`: **pass 83 / fail 0**（§13 必須表 + 追加ケース）
- `zip-exec-bits`: build-zip.sh 内で検証済（`plugin.json` ルート・hooks 実行ビット）

## 残リスク / 次へ

- spec 文言「直前が `2` でも `&` でもない」の fd>1 厳密化は設計変更候補。実装は厳格側（fail-closed）に倒しており安全だが、文言を正本に反映するなら設計改訂 + 再承認が必要
- `>out 2>&1` の緩和も同じく設計改訂候補（受容済み保守 deny）
- PR1 マージ条件は満たした。実機 `agent_type` 配線・compare eval・親トークン計測は PR2/PR3。費用削減の主張は引き続き不可
