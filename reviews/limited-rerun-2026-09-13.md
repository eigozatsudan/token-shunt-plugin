# 偽陽性確認・契約整合・限定再実行

## 偽陽性確認

1. 引用漏れ: fixture が `a\n` ×100、返答が同 ×21 で旧判定は非違反。実際の連続21行なので真の見逃し。21行窓で照合し、1文字・20行・離散引用を通し、21行の部分引用を落とす。
2. 分割Read: 旧判定は拒否なしの分割、拒否後の1–10→101–110、101–110→1–10をすべて通した。子契約の「全文のトークン上限拒否後だけ、連続・非重複、順に」に反する。最初の全文拒否の種別と成功範囲の順序・隣接性を検査する。単発targeted Read、正当な分割、答えが得られた時点での終了は許す。拒否された範囲は既読扱いしない。
3. 行数取得: サイズだけの経路判定と、委譲用の行数取得は両立する。旧記述は同じ段階のメタデータと書いていた点が不整合。設計§11/§26.2とスキルを「サイズで委譲確定後にwc -lc」に統一した。

## オフライン検証

- compare unit: 87件成功（回帰4件追加）。
- evals/run.sh: 110 pass / 0 fail。配布ZIPを再生成。
- bulk-reader skill quick_validate: valid。
- git diff --check: 成功（フック検証のfixture生成・復元完了後）。

## 限定実機再実行

10ケース、既定モード計19実行。全体リリース判定ではない。
compare-code-writer-ok / compare-code-writer-no-ref / writer-bounds /
writer-verification-levels / auto-bulk-facts / auto-one-line /
compare-edit-dense-lines / compare-explicit-multifile /
reader-batch-ambiguous / retry-policy。

サンドボックス内の初回run.ubjhmq7dは事前プローブでAPI再試行を繰り返したため中断。
承認された環境でrun.uoPCOPJpを実行した。ロード・隔離プローブは通過扱いだったが、応答を確認するとプローブも利用上限を返していた。

19実行すべてが `You've hit your session limit · resets 4:50pm (Asia/Tokyo)` で終了。修正後の契約遵守・精度を評価できる実行は0件。製品の振る舞いの失敗とは区別する。`selected_run_valid` と `release_eligible` はともにfalse。

証跡: `evals/compare/tmp/runs/run.uoPCOPJp/`（transcripts / verdicts / manifest）。ログ: `/tmp/token-shunt-limited-rerun.log`。
利用上限解除後に同じ10ケースを再実行する必要がある。今回の結果から修正の実機有効性は主張しない。
