# Design vs implementation — hooks / install (2026-09-13)

正本: `docs/2026-09-12-token-shunt-design.md`（承認済み）。対象はフック、マニフェスト、ZIP、doctor、フック eval、README の install/hooks/env/known-limits、`docs/distribution/README.md`。設計ドラフトと旧レビューは現行要件として使っていない。

検証: 現行ファイルの静的照合。`evals/run.sh` は **98 pass / 0 fail**。ZIP 内 3 フックは `mode=0o100755`、`.claude-plugin/plugin.json` がアーカイブ根、`marketplace.json` は ZIP に含まれない。

## Summary

PreToolUse / SessionStart フック、`hooks.json` の exec form、マニフェスト必須フィールド、ZIP 実行ビット、§13 必須フック eval（表の id を分割したケース含む）は現行設計と一致する。jq fail-closed、env 既定（空・非整数・負・0）、トップレベル `agent_type` の完全一致 allowlist、`limit=1` 例外なし、`undetermined=deny`、Read 除外拡張子、通過時空 stdout、Bash の引用演算子・パイプ末尾・複合先行・stdout リダイレクト早期通過・head/tail 解釈、`check-jq` が jq を呼ばないこと、は実装されている。残る齟齬は doctor が §7 / §12 の検証範囲（実モデル、effort、maxTurns、最低対応版の記録、フック stdin dump）を満たさないことだけである。§4 / §15 の既知限界と、既レビューで受容した走査後 `elapsed_ms` 適用・fd>1 の厳格化は再掲しない。

## Issues

### Issue 1 -- Severity: suggestion
- File: /home/dev/projects/skills/token-shunt/scripts/doctor.sh:1
- Design: §7 「インストール手順でフック stdin を 1 回 dump する doctor を載せる」「doctor は agent_type だけでなく、呼び出し時モデル指定、Haiku/Sonnet の実モデル、effort、maxTurns の partial 終了も検証し、実装時に最低対応版を記録する」。§12 「`effort: low` が対象モデル・CLI で使えること、`maxTurns` と実モデル解決を doctor と実機 eval で確認する」。
- Description: doctor は jq の有無（欠落時のみ fail）、`claude --version` の表示、`FORCE=1` 警告、任意の plugin-load プローブ、フック stdin の手順説明まで。`agent_type` の実 dump は行わず、呼び出し時 model / 解決済み Haiku・Sonnet / `effort` / maxTurns partial / 最低対応版の記録は無い。終了コードは jq 欠落以外ほぼ 0。README:162 はこの縮小範囲をそのまま書いており、§14 の短い doctor 箇条（jq / FORCE / agent_type 案内）とは揃うが、§7 / §12 の検証契約は未実装。
- Suggestion: 認証が使えるとき、PreToolUse stdin を 1 回 dump してトップレベル `agent_type` を確認する。同じセッション（または doctor 専用の Agent 起動）で要求 model と `resolvedModel`、`effort: low` の受理、maxTurns 到達時の partial を検証し、通った最低 CLI 版を doctor 出力に記録する。認証オフは hard fail にしないなら、未確認項目を `unverified` と明示し「検証済み」と書かない。
- Status: open
- False-positive risk: medium — §14 の README 必須は短い doctor リストで、実装と README はそのリストに合わせている。モデル / effort / maxTurns はライブ CLI と認証が要る。それでも §7 / §12 は doctor 自身の検証項目として書いてあり、現行スクリプトはそこを省略している。
