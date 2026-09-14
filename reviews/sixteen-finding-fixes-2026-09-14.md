# 2026-09-14 16件の修正と回帰確認

対象: `reviews/clean-context-three-2026-09-14/README.md` の F1–F16。既存の未コミット変更を維持して修正し、ユーザー指定に従い同じコミットへ含める。

## 修正境界

| 指摘 | 修正 | 回帰証拠 |
|---|---|---|
| F1 | 同一 Bash 呼び出しの先行処理・並行ステージによるファイル変更可能性を保持し、事前サイズに依存する reader を拒否。解決可能な先頭 cd、独立した byte-bound は維持 | `test_bash_finding_fixes.py`: cp/mv/ln/tee/install/Python、不存在/既存小ファイル、パイプ、実 Bash 出力との対照 |
| F2 | `+=` を代入プレフィックスとして hook/judge 両方で認識 | 複数代入・prefix redirect・compound/pipeline・head byte-bound |
| F3 | lexer に引用前の展開情報を保持し、コマンドワードを早期 pass より前に検査 | brace/glob/絶対コマンドパス、引用・escape のリテラル対照 |
| F4 | l50.py を実際に50行生成し、50行目に task_fifty を定義 | 実生成・行数・50行目・Python 実行の検査 |
| F5 | test_runner が gitignore 対象の生成済み gold を読む依存を除去 | 一時ディレクトリの新規生成結果と固定契約値を比較。clean snapshot で全回帰 |
| F6 | reader 状態キーと pending path を realpath 正規化 | `./`、重複 slash、symlink でも stopped/retry を維持 |
| F7 | 本文コマンドの列挙依存をやめ、対象パスを使う未知コマンドも検出。引数のパス別名と埋め込みプログラムを確認 | 空白・escape を含むパス、sort/sed/tac/base64/bash/source/zcat/jq/未知 emitter、wc/stat/rg/awk の対照 |
| F8 | 観測した子ツール結果（Read/Grep/Bash 等）・Write 内容を fixture と併せて照合。親 thinking を context 指標と leakcheck に含める | fixture 外の21行本文、行番号付き結果、Write 本文、thinking 単独の漏洩と要約対照 |
| F9 | confirmed の根拠は絶対パスの正規化同一性で照合 | basename/別ディレクトリ/パス接尾辞は拒否、絶対・正規化・行番号 citation は受理 |
| F10 | 子返答の証拠・上限・本文を全委譲に適用。writer は800字、terminal status/stop_reason、Write 時は path/line count/3–5 bullets | ケースフラグ無しの reader/writer、返答欠落・形式欠落・本文・上限超過と正常対照 |
| F11 | 全 plugin worker に要求/解決モデルと auto 初回・retry の制約を適用 | A群の opt-in 宣言無しでも誤モデル・解決モデル欠落を拒否 |
| F12 | startup の名前だけによる無条件除外を廃止。非空 payload/stderr・失敗を外来扱い | 同名 startup の output/stdout/stderr と空正常応答の対照 |
| F13 | 設計 §26.5 の JSON フィールド名を実装に一致させ、補助フィールド・mode 導出を説明 | cases.json / judge / routing_checks との静的照合 |
| F14 | CLI 費用値と固定順全カタログ反復を現実装として明記。単価再計算・48実行・順序交替は未実装の将来計画と明記 | repeat.sh / judge / README / 設計の静的照合 |
| F15 | marketplace は自動起動を意味する route から委譲の推奨へ修正 | manifest と実際の hook deny/案内の照合 |
| F16 | executable 境界で Exception を捕捉して exit 2。BaseException は対象外 | 100,000段 JSON、既存 malformed event/response 回帰 |

## 検証記録

結果: **fixed**。元の再現条件を拒否する回帰テストと、通常の読取・byte-bound・要約・正しいモデル/根拠の正常対照が通過した。

1. 構文・差分: 対象 Bash スクリプトの `bash -n`、Python AST parse、`git diff --check` が成功。
2. 個別再現: `python3 evals/test_bash_finding_fixes.py` 14件、`python3 evals/test_reader_contract.py` 13件、`python3 -m unittest discover -s evals/compare -p test_sixteen_findings.py` 10件が成功。Bash テストはフックの判定と実 Bash の出力を対照した。
3. 全回帰: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s evals/compare -p 'test_*.py'` **252件成功**。`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s evals -p 'test_*.py'` **100件成功**。`PYTHONDONTWRITEBYTECODE=1 bash evals/run.sh` **121項目成功、失敗0**。
4. クリーン状態: `git ls-files --cached --others --exclude-standard` の列挙だけを新しい一時ディレクトリへコピーし、`evals/compare/fixtures/gen` が存在しないことを assert した。そこで比較252件とフック・配布121項目が成功。既存の未追跡生成 gold や tmp 出力に依存していない。
5. 配布: ZIP の構造・実行属性テスト成功。`token-shunt.zip` の全ファイルを `plugin/` とバイト比較し、差分0。

新規の読み取り専用エージェントで実装前の境界調査と実装後のレビューを各1回実施。レビューが発見した空白/escape パスの F7 残存経路と Bash 結果の F8 残存経路を、親側で再現して修正し、正常対照を含む回帰に追加した。

clean snapshot で新たに顕在化した writer テスト3件の生成 fixture 依存も、テスト自身が必要な参照本文を一時ディレクトリへ用意する形で解消した。

実行ログ: [比較252件](sixteen-finding-validation-2026-09-14/compare.log)、[フック・配布121項目](sixteen-finding-validation-2026-09-14/hook-catalog.log)、[補助100件](sixteen-finding-validation-2026-09-14/unit.log)。

## 互換性と限界

- F1 は writer のブラックリストではなく、安全を証明できる段階だけ事前サイズ検査を信用する方式。同じ pipeline の `cat small | tee other | cat` もファイル変更があり得るため保守的に拒否し、準備と読み取りを別呼び出しに分ける。OS レベルでファイルを固定する仕組みではなく、別プロセスの検査後変更までは防がない。
- 空の正常 `SessionStart:startup` は既存 CLI の bootstrap と出力上区別できない。非空 payload の不可視化は修正し、空正常の外来フックを識別できない制限は README に明記した。
- 本文検査は観測可能な transcript が対象。非公開 thinking、未観測の入力、既存の変形・分割引用閾値に関する制限は残る。
- writer が Write しない失敗では line count/bullets を要求せず、partial と stop_reason は要求することを agent 文書に明記した。
- 今回の回帰確認はオフライン。課金される新規モデル比較と48実行の費用測定は実施しない。オフライン成功だけで release_eligible や費用削減を主張しない。
