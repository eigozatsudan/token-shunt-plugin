# クリーンコンテキスト敵対的レビュー

対象: `/home/dev/projects/skills/token-shunt` の現在の作業ツリー。README、現行フック、エージェント契約、比較評価器と現行テストを読んだ。`reviews/`、`docs/history/`、過去実行ログは未読。親からの過去発見情報なし。適用候補 `/AGENTS.md` からリポジトリまでの AGENTS.md は存在しなかった。既存ファイル変更なし。外部API・認証済みモデル呼び出しなし。

安全な再現fixture: `/tmp/ts-adversarial-25g9ildd`。以下の優先度は汎用セキュリティ境界としてではなく、文書化されたサイズ誘導/評価契約に対する不具合として付けた。

## 1. [P2] ゼロ埋めstdout fdを無視するとリダイレクト早期通過が本文をstderrへ流す

場所: `plugin/hooks/check-bash-read:240-248`、特に242行の `[[ -z $fd || $fd == 1 ]]`。

Bashは `01>` と `001>` をfd 1へのリダイレクトとして実行するが、解析器は文字列 `1` のみをstdoutと認識する。先行する通常ファイルへの `>` がCLEAN_GTを立てた後、`01>/dev/stderr` がSPECIAL_GTを立てず、全体を通過させる。

再現:

```python
import json, pathlib, subprocess, tempfile
p = pathlib.Path(tempfile.mkdtemp(prefix='ts-fd-'))
(p/'big').write_bytes(b'A'*80000)
for fd in ['1', '01', '001']:
    cmd = f'cat {p}/big >{p}/out {fd}>/dev/stderr'
    hook = subprocess.run(['bash', 'plugin/hooks/check-bash-read'],
        input=json.dumps({'tool_input': {'command': cmd}}), text=True, capture_output=True)
    real = subprocess.run(['bash', '-c', cmd], capture_output=True)
    print(fd, hook.returncode, repr(hook.stdout), real.returncode,
          len(real.stdout), len(real.stderr))
```

実測: `1` はhook deny、`01` と`001` はhook exit 0/空stdout (pass)。3種類とも実コマンドexit 0、stdout 0 bytes、stderr **80,000 bytes**。しきい値65,536 bytesを超える本文がツール結果に入る。

影響: 単独catと明示的通常ファイル、対応する `>` だけで誘導を回避する。README:123が「標準出力・標準エラーへ戻るリダイレクト先は判定省略の対象にならない」と明記しているため、非対応の間接読取ではない。

修正方針: fdを字句境界込みで解析し、先頭ゼロを除去した数値的fd 1をstdoutとして同一扱いする。オーバーフローする任意長fdを算術評価せず正規表現 `^0*1$` 等を使う。不確実なfd構文では早期通過を抑制する。`01>` / `001>>` / `01>|` を通常fdと対でテストする。

確信度: 高。反証/限界: `>/dev/stdout` を先行リダイレクトの後に置くとその時点のstdoutは出力ファイルなので実測0 bytesになった。これを反例として採用せず、元のstderrへ80,000 bytes出る `/dev/stderr` で確認した。本文をstderrへ渡すことが問題であり、stdoutだけの計測では見逃す。

## 2. [P2] Readの末尾改行パスが別パスに変わりサイズ判定を通過する

場所: `plugin/hooks/check-file-size:137-139`。

`file_path=$(jq -r ...)` はJSONデコード結果の末尾改行もBashのコマンド置換によって削除する。実在する `big-newline\n` を指定しても `big-newline` の存在を調べるので、別パスが存在しなければ通常ファイルではないと判断してpassする。

再現:

```python
import json, pathlib, subprocess, tempfile
p = pathlib.Path(tempfile.mkdtemp(prefix='ts-newline-'))
for name in ['big', 'big-newline\n']:
    f = p/name
    f.write_bytes(b'A'*80000)
    r = subprocess.run(['bash','plugin/hooks/check-file-size'],
        input=json.dumps({'tool_input':{'file_path':str(f)}}), text=True, capture_output=True)
    print(repr(str(f)), len(f.read_bytes()), r.returncode, repr(r.stdout))
```

実測: 通常名80,000 bytesはdeny。末尾改行名も実ファイル読取80,000 bytesだがhook exit 0/空stdout (pass)。改行を含まない別名は存在しない。

影響: Readの明示的な通常ファイルについて、フックと実際の入力パスの同一性が失われる。これはshell展開や間接コマンドでなく、JSONに正確に表現できるPOSIXファイル名。READMEに改行ファイル名の除外はない。

修正方針: jq出力をsentinel付きで捕捉しsentinelのみ除去する、またはNUL区切りread等で末尾改行を保持する。jq自身の追加改行とファイル名の改行を区別する必要がある。末尾LFを1個/複数持つパス、改行除去後の別名が小さいファイル/除外拡張子の場合もテストする。

確信度: 高 (hookのパス破壊と生バイト数を再現)。限界: 認証済みClaude Readツールの実呼び出しは依頼により行っていない。実ファイルをPythonで正確なパスから読み、80,000 bytesを確認した。CLI側がパスの末尾LFを拒否/正規化する仕様なら実際の発火範囲は狭まるが、そのような仕様はこのリポジトリの契約にはない。

## 3. [非採用・補償済み局所制限] 生成後の変更より古い検証結果を関数単独では採用する

場所: `evals/compare/flow_checks.py:130-160`。呼び出し点 `evals/compare/judge.py` の `verification_errors`、対象ケース `evals/compare/cases.json:292` (`writer-verification-levels`)。

verification_errorsは検証コマンド開始→結果→最終報告の順番だけを確認し、検証対象の最後のWrite/Edit/子による変更との順序を比較しない。検証成功後に対象ファイルが壊れても古い成功を採用する。

再現fixture: `/tmp/ts-adversarial-25g9ildd/vl_req.json`、合成transcript保存先 `/tmp/ts-adversarial-25g9ildd/stale-transcript.json`。

オフライン実行した手順:

1. `vl_req.json` に `{"required_key":"rk-1"}` を実際に書く。
2. `python3 /home/dev/projects/skills/token-shunt/evals/compare/flow_checks.py --verify requirements /tmp/ts-adversarial-25g9ildd/vl_req.json --require-key required_key=rk-1` を実行。exit 0、JSON `verification: requirements, ok: true`。
3. transcriptに親Bash呼出/実結果、続けて同じファイルを `{` にする成功Write、最終 `vl_req.json verification: requirements status: complete` を記録し、ディスク上も実際に `{` にする。
4. `verification_artifacts` に同一path、requirements、checker、require_keysを指定し、`verification_controls` にexpected_level requirements/allowed_status completeを指定して `verification_errors(Transcript(events), spec, exp)` を実行。

実測: 最終ファイル **1 byte**、`verification_errors == []`。同じ検証コマンドを最終ファイルに再実行すると **exit 1**。返答形式や検証コマンドの曖昧さによる現象ではない。

影響: 比較評価の「生成物に対して親がrequirements検証を行い、その結果を報告した」という判定に偽成功が残る。修正/再生成の後に再検証を忘れた経路を検出できない。

修正方針: 対象artifactへの最後のWrite/Edit/生成Agent完了より後の検証を要求する。明示的書込ツールは順序チェックできる。Bashや子の書込も含めた最終実体保証はrunner側で最後にcheckerを実行するか、検証結果のdigestと最終artifactのdigestを照合する。順序チェックを入れるなら、成功検証の後の変更がなくてpassする対照も維持する。

確信度: 高 (関数レベルの偽成功は実測)。限界: 完全なrelease suiteの全判定を通す合成ログは作成していない。これは特定verification assertionの誤判定で、他の無関係な判定まで成功したという主張ではない。ディスク上の独立した最終検証が別途必須なら補償可能だが、このverification caseの当該関数にはその保証がない。

## 非採用/反証

- `bash -c`、変数展開、コマンド置換、未対応パイプ末尾、入力リダイレクト等を網羅する一般shell security boundaryとは扱わなかった。
- 複数ファイルや反復呼出の合算をしていないことは、現在の「ファイル単位判定」や明記された呼出間非集計と混同しなかった。
- `cat big >file 01>/dev/stdout` はフックpassでも実出力0 bytesなので、漏れとして採用しなかった。
- エージェント返答上限が指示ベースであることはREADMEに明記されており、新規不具合とは数えなかった。

## 統合後の反証確認

親からrunnerの補償チェックの指摘を受け、第三候補を現行のreportable欠陥から取り下げた。`cases.json:415` の `disk_check: verify_levels` により `run.sh:350-355` が最終生成物へcheckerを再実行し、`judge.py:1517-1521` がdisk_okの成功を必須にする。現行run.shからdisk_check関数をそのまま切り出した `/tmp/token-shunt-disk-refute.sh` を、安全な/tmp fixture（他3成果物は正常、vl_req.jsonだけ1-byteの `{`）に対して実行すると、exit 1、`disk_ok: false`、reason `generated verification-level artifacts failed syntax/minimal/requirements checks`。したがって第三候補の関数単独の[]はrelease偽成功にならず、補償済み局所制限として非採用。確定報告は第一・第二の2件のみ。

再現用単体スクリプト: `/tmp/token-shunt-fresh-adversarial-repro.py`（第三候補は局所関数の挙動確認にとどまり、前述の最終ゲートにより拒否される）。
