# worker 側の制限適用の確認（2026-09-14）

## 確認方法

### Step 1: フック側3制限（サイズ閾値・走査予算バイト数・走査予算時間）

`/home/dev/projects/skills/token-shunt` 直下で、fixture を作成して各フックに
`agent_type` 付き／なしの入力を与え、`hookSpecificOutput.permissionDecision` を
観察した。実行したスクリプト（brief 記載のものと同一。probe 関数は当初 jq の
空入力エラーを "pass" 扱いにできず出力が空になったため、後段で `probe_raw`
（生の stdout と終了コードを記録）に切り替えて再確認した）:

```bash
cd /home/dev/projects/skills/token-shunt
T=$(mktemp -d)
cat > "$T/mkfix.py" <<'FIXEOF'
import sys, pathlib
d = pathlib.Path(sys.argv[1])
(d / 'big.txt').write_bytes(b'x\n' * 200000)           # サイズ超過（stat だけで確定）
(d / 'oneline.txt').write_bytes(b'y' * 200000 + b'\n')  # 単一巨大行
(d / 'tiny.txt').write_bytes(b'abc\n')                 # 両閾値を下回る → 走査予算検証用
FIXEOF
python3 "$T/mkfix.py" "$T"

probe() { # label env... hook   (payload は stdin)
  local label=$1; shift
  printf '%-44s -> ' "$label"
  env -u CDPATH "$@" | jq -r '.hookSpecificOutput.permissionDecision // "pass"'
}

# (1) サイズ閾値
for agent in '' 'token-shunt:bulk-reader'; do
  for f in big.txt oneline.txt; do
    probe "size ${agent:-parent} read $f" plugin/hooks/check-file-size \
      <<<"$(jq -nc --arg a "$agent" --arg c "$T" --arg p "$f" \
        '{cwd:$c, tool_input:{file_path:$p}} + (if $a == "" then {} else {agent_type:$a} end)')"
    probe "size ${agent:-parent} bash $f" plugin/hooks/check-bash-read \
      <<<"$(jq -nc --arg a "$agent" --arg c "$T" --arg p "$f" \
        '{cwd:$c, tool_input:{command:("cat " + $p)}} + (if $a == "" then {} else {agent_type:$a} end)')"
  done
done

# (2) 走査予算バイト数: tiny.txt は両閾値を下回るので、ここだけが予算超過で deny になる
for agent in '' 'token-shunt:bulk-reader'; do
  probe "scan-bytes ${agent:-parent} read" TOKEN_SHUNT_SCAN_BUDGET_BYTES=1 \
    plugin/hooks/check-file-size \
    <<<"$(jq -nc --arg a "$agent" --arg c "$T" \
      '{cwd:$c, tool_input:{file_path:"tiny.txt"}} + (if $a == "" then {} else {agent_type:$a} end)')"
  probe "scan-bytes ${agent:-parent} bash" TOKEN_SHUNT_SCAN_BUDGET_BYTES=1 \
    plugin/hooks/check-bash-read \
    <<<"$(jq -nc --arg a "$agent" --arg c "$T" \
      '{cwd:$c, tool_input:{command:"cat tiny.txt"}} + (if $a == "" then {} else {agent_type:$a} end)')"
  # (3) 走査予算時間: 設計 §5 でテンプレート対象外。worker への適用有無だけ記録する
  probe "scan-ms ${agent:-parent} read" TOKEN_SHUNT_SCAN_BUDGET_MS=0 \
    plugin/hooks/check-file-size \
    <<<"$(jq -nc --arg a "$agent" --arg c "$T" \
      '{cwd:$c, tool_input:{file_path:"tiny.txt"}} + (if $a == "" then {} else {agent_type:$a} end)')"
done

# (4) 拒否理由の全文: どの制限が発火したかを文言で確定させる
env -u CDPATH TOKEN_SHUNT_SCAN_BUDGET_BYTES=1 plugin/hooks/check-file-size \
  <<<"$(jq -nc --arg c "$T" '{cwd:$c, tool_input:{file_path:"tiny.txt"}}')" \
  | jq -r '.hookSpecificOutput.permissionDecisionReason'
env -u CDPATH TOKEN_SHUNT_SCAN_BUDGET_MS=0 plugin/hooks/check-file-size \
  <<<"$(jq -nc --arg c "$T" '{cwd:$c, tool_input:{file_path:"tiny.txt"}}')" \
  | jq -r '.hookSpecificOutput.permissionDecisionReason'
rm -rf "$T"
```

実際の出力（親側は全て `deny`、worker (`token-shunt:bulk-reader`) 側は
`probe` の jq フォールバックが空入力で機能せず空欄になった。 pass() はフック側で
`hook_log pass ""; exit 0` — つまり **標準出力ゼロバイト、終了コード0** で、
これは deny JSON を返さない、すなわち「許可（pass）」を意味する。空欄がその
pass を表している）:

```
=== (1) サイズ閾値 ===
size parent read big.txt                     -> deny
size parent bash big.txt                     -> deny
size parent read oneline.txt                 -> deny
size parent bash oneline.txt                 -> deny
size token-shunt:bulk-reader read big.txt    ->
size token-shunt:bulk-reader bash big.txt    ->
size token-shunt:bulk-reader read oneline.txt ->
size token-shunt:bulk-reader bash oneline.txt ->
=== (2)/(3) 走査予算 ===
scan-bytes parent read                       -> deny
scan-bytes parent bash                       -> deny
scan-ms parent read                          -> deny
scan-bytes token-shunt:bulk-reader read      ->
scan-bytes token-shunt:bulk-reader bash      ->
scan-ms token-shunt:bulk-reader read         ->
=== (4) 拒否理由の全文 ===
File exceeds token-shunt thresholds (lines=1/350, bytes=2/65536). Use /token-shunt:bulk-reader. For edits, use a targeted Read of the original that passes the hook. If that fails, editing is outside v0.1 scope. Scan budget exceeded (read_bytes=2/1, ms=5/2000); use /token-shunt:bulk-reader for analysis. Editing still requires a successful targeted Read of the original.
File exceeds token-shunt thresholds (lines=1/350, bytes=4/65536). Use /token-shunt:bulk-reader. For edits, use a targeted Read of the original that passes the hook. If that fails, editing is outside v0.1 scope. Scan budget exceeded (read_bytes=4/8388608, ms=5/0); use /token-shunt:bulk-reader for analysis. Editing still requires a successful targeted Read of the original.
```

空欄が実際に「pass（deny JSON なし）」であることを、`probe_raw`（生の stdout と
終了コードをそのまま表示、jq を介さない）で個別に再確認した:

```bash
probe_raw() {
  local label=$1; shift
  local out
  out=$(env -u CDPATH "$@")
  local rc=$?
  printf '%-44s rc=%s out=%q\n' "$label" "$rc" "$out"
}
```

出力（すべて `token-shunt:bulk-reader`、`agent_type` はスクリプト内で明示的に
文字列として渡した。空文字にはならない）:

```
size token-shunt:bulk-reader read big.txt    rc=0 out=''
size token-shunt:bulk-reader bash big.txt    rc=0 out=''
size token-shunt:bulk-reader read oneline.txt rc=0 out=''
size token-shunt:bulk-reader bash oneline.txt rc=0 out=''
scan-bytes token-shunt:bulk-reader read      rc=0 out=''
scan-bytes token-shunt:bulk-reader bash      rc=0 out=''
scan-ms token-shunt:bulk-reader read         rc=0 out=''
```

`rc=0` かつ `out=''`（deny JSON なし）＝ pass。これで (1)(2)(3) すべてについて
worker が pass することを、jq のフォールバックに頼らない形で確認した。

(4) の拒否理由の全文は brief の予測と一致した:
`Scan budget exceeded (read_bytes=2/1, ms=5/2000)` （バイト側が先に発火、
`TOKEN_SHUNT_SCAN_BUDGET_BYTES=1` を与えたケース）と
`Scan budget exceeded (read_bytes=4/8388608, ms=5/0)` （`TOKEN_SHUNT_SCAN_BUDGET_MS=0`
を与えたケース、`ms=5/0` で時間側が発火）。`read_bytes=X/Y` と `ms=A/B` の
両方が同じ文言内に常に出力されるため、**どちらの予算が発火したかは
`Y`（`SCAN_BUDGET_BYTES` の値）と `B`（`SCAN_BUDGET_MS` の値）を見て判別する**
（発火させた側の分母が異常値（1 や 0）になっている）。

コード上の該当箇所を確認した:

```
plugin/hooks/check-file-size:153-165  agent=$(jq -r '.agent_type // empty' <<<"$input")
                                       case $agent in
                                         token-shunt:bulk-reader) command -v python3 ... pass ;;
                                         token-shunt:code-writer) pass ;;
                                       esac
plugin/hooks/check-bash-read:173      [[ $agent == token-shunt:bulk-reader ]] && pass
```

両方とも `full_file_verdict` / `bash_read_verdict`（サイズ判定・走査予算判定）
より**前**にある。したがって worker が allowlist にマッチした時点で即座に
`pass` し、以降のサイズ判定・走査予算判定のコードパスには一切入らない。

### Step 2: ネイティブ Read のトークン上限（ハーネス側、フック外）

```bash
cd /home/dev/projects/skills/token-shunt
grep -n "one-line\|unreadable_line\|read_max_output_tokens" reviews/live-rerun-2026-09-14c.md reviews/cost-structure-2026-09-14.md
grep -n "read_max_output_tokens" evals/compare/cases.json
```

`reviews/live-rerun-2026-09-14c.md` と `reviews/cost-structure-2026-09-14.md` の
grep 結果には `unreadable_line` の直接一致は**なかった**（brief の期待とは
食い違う点。下記「未確認のまま残ること」に記録）。`cost-structure-2026-09-14.md`
の `auto-one-line` 実行では、子（worker）が実際に該当行を読み切り、コストが
爆発しただけで partial には落ちていない（69,886 バイトの単一行 ≒ 4バイト/token
換算で約17,500トークンとなり、そのケースの `read_max_output_tokens: 40000`
を下回るため、この特定の実行では上限に到達していない）。

そこで別の実機記録を確認した:

```bash
grep -n "unread line\|CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS\|read_max_output_tokens" reviews/live-rerun-2026-09-14.md
```

`reviews/live-rerun-2026-09-14.md:84`:
```
- `compare-one-line` 3モード — 子は `unread line 1` 付きのプレーン行を出力する
  ようになったが、sonnet が `confirmed: none — unable to retrieve payload_sha value.`
  と書いたため、`unreadable_line_partial()` の「`confirmed:` 行があってはならない」
  規則に抵触して accuracy 免除が外れる。空の confirmed ラベルを事実主張と見なさない
  方針（Codex の B 修正）が、この否定形の行までは覆っていない
```

これは worker (child) が `unread line 1` を報告した実機記録であり、
worker 側でもネイティブ Read が同じトークン上限で拒否されたことを示す
（`compare-one-line` ケースは worker に委譲する `token-shunt:bulk-reader` を
使うケース）。

さらに `evals/compare/cases.json` を確認:

```bash
grep -n "read_max_output_tokens" evals/compare/cases.json
```
```
47:      "read_max_output_tokens": 40000,
640:      "read_max_output_tokens": 40000,
```

L47 は `compare-one-line` ケース定義内で、この上限は**ケース全体**（direct
モードでも delegate モードでも同じ）に適用される。delegate 側の `expect` には
`allow_unreadable_line_partial` が明示されている（cases.json:80-82 相当）:

```json
"allow_unreadable_line_partial": [
  "{FIX}/gen/oneline.json"
]
```

これは、この上限に worker が引っかかって `status: partial` /
`stop_reason: unreadable_line` を返すことを、判定器 (`evals/compare/routing_checks.py`
の `unreadable_line_partial()`) が正規のケースとして許容していることを意味する。

`CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS` がどこで環境変数として設定されるかも
確認した:

```bash
grep -rn "CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS" evals/compare/cost_probe.py evals/compare/test_runner.py
```
```
evals/compare/cost_probe.py:79:    env["CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS"] = str(
evals/compare/cost_probe.py:80:        case.get("read_max_output_tokens", 25000))
evals/compare/test_runner.py:272:    self.assertEqual(case['read_max_output_tokens'], 40000)
evals/compare/test_runner.py:280:printf '%s' "$CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS"
```

この環境変数はケース実行を起動する**親プロセス**の環境に1回だけセットされる。
`Agent`（サブエージェント委譲）は同じプロセスの子として起動されるため、
環境変数は継承され、worker（子）の Read にも同じ上限が適用される。これは
brief の記述（「ハーネス（フック外）の制限であり、親プロセスの環境変数として
サブエージェントにも継承される」）と一致する。

## 結果

| 制限 | worker に適用されるか | 根拠 | 委譲で処理継続が可能か |
|---|---|---|---|
| サイズ閾値 | 適用されない（allowlist で before-check pass） | `check-file-size:153-165` / `check-bash-read:173`。実測: worker 入力は全ケースで `rc=0 out=''`（pass） | 可（設計 §5 で既に「返す」に確定済み） |
| 走査予算バイト数 | 適用されない（allowlist で before-check pass） | 同上。実測: `TOKEN_SHUNT_SCAN_BUDGET_BYTES=1` を与えても worker は `rc=0 out=''`（pass） | 可 |
| 走査予算時間 | 適用されない（allowlist で before-check pass） | 同上。実測: `TOKEN_SHUNT_SCAN_BUDGET_MS=0` を与えても worker は `rc=0 out=''`（pass） | 設計 §5 でテンプレート対象外（適用有無は記録のみ・本タスクの結論を変えない） |
| ネイティブ Read トークン上限 | 適用される（同じプロセスツリー内の環境変数） | `reviews/live-rerun-2026-09-14.md:84`（`compare-one-line` で子が `unread line 1` を報告した実機記録）、`evals/compare/cases.json` の `allow_unreadable_line_partial`、`evals/compare/cost_probe.py:79-80` の env 継承コード | 継続可能だが「委譲」ではなく既存の partial 契約（「First call only ... stop and report partial」節）が担当。テンプレート適用対象外（Task 5 の範囲外、既存契約が既にカバー） |

## 走査予算超過へのテンプレート適用の可否

**継続可能（可）**。フック側の3制限（サイズ閾値・走査予算バイト数・走査予算時間）
はすべて worker allowlist（`check-file-size:153-165` / `check-bash-read:173`）で
判定より前に pass するため、親がこれらのいずれかで deny された同一ファイルを
worker に委譲すれば、worker はフック側のチェックを一切経由せず Read/Bash を
実行できる（実測: 全ケースで `rc=0 out=''`）。走査予算超過（バイト側）はこの
3つの中の一つであり、他の2つと区別すべき理由はない。したがって Task 5 は
走査予算超過（バイト側、`Scan budget exceeded (read_bytes=X/Y, ...)` で
`Y` が異常値になっている側）の deny 文言に委譲コンタクト・テンプレートを
追加してよい。時間予算側（`ms=A/B` で `B` が異常値）は設計 §5 の既定どおり
テンプレート対象外のまま維持する（本タスクはこの制約を上書きしない）。

ネイティブ Read のトークン上限は worker にも同じく適用されるが、これは
フックの走査予算とは無関係の別制限であり、単一巨大行に起因する拒否は
既存のテンプレート節（「First call only ... stop and report partial」）が
すでに担当する対象である。走査予算超過テンプレートの可否判断には影響しない。

## 未確認のまま残ること

- brief が名指しした `reviews/live-rerun-2026-09-14c.md` と
  `reviews/cost-structure-2026-09-14.md` には、期待されていた
  `unreadable_line` / `status: partial` の直接的な実行記録が実際には
  **含まれていなかった**（`auto-one-line` の実行では fixture のトークン数が
  そのケースの `read_max_output_tokens: 40000` を下回っており、上限に到達
  していない）。代わりに `reviews/live-rerun-2026-09-14.md:84`
  （`compare-one-line` ケース、別の実行記録）にある実機記録で worker 側の
  ネイティブ Read 拒否を確認した。Step 2 の結論自体は変わらないが、根拠と
  なった記録ファイルは brief の指示と異なる。
- `check-file-size` の worker allowlist には `command -v python3` チェックが
  あり、python3 が存在しない環境では `exit 2`（フック実行エラー）になる。
  今回の実行環境には python3 があったため、この分岐（python3 欠如時の挙動）は
  未検証。ただし Task 1 の判定表（走査予算超過へのテンプレート適用可否）には
  影響しない。
