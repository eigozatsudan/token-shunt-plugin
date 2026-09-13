# 敵対的レビュー

## 範囲と方法

現行ツリー（HEAD `cb1ab7c94952df128aa9d171217177390b4a151e`）のフックとオフライン判定器を、文書化された契約（README、設計 §1–15・§26）より弱く通せるかを実コマンドで検証した。

- 対象: `plugin/hooks/check-file-size`、`plugin/hooks/check-bash-read`、`plugin/hooks/hooks.json`、`evals/compare/judge.py`、`flow_checks.py`、`routing_checks.py`
- 方法: フックへ実 JSON を渡し、同じコマンドを `bash --noprofile --norc -c` で実行して stdout バイト数を照合。判定器は `PYTHONDONTWRITEBYTECODE=1` でモジュール import し、合成 JSONL を `judge()` に渡した
- 実験場所: `/tmp/shunt-adv/`（リポジトリは未変更）
- 見なかったもの: `reviews/`、`docs/history/`、git log/blame、設計 §27、ウェブ上の先行レビュー
- 走らせなかったもの: `evals/compare/run.sh`（live Claude API）

攻撃として実際に試したもの: 引用・エスケープ、stdin/stdout/fd エイリアス、パイプ、複合、`cd`、空白・パイプ文字・末尾改行を含むファイル名、`tool_input.agent_type` 偽装、symlink/device、`$''` 引用、隣接リダイレクト、判定器の confirmed ラベル、Grep 本文回収、欠損 fixture の引用検査、非同期通知、親検証コマンド。

## 確認した不具合

### P1: 単独 cat/head/tail の stdin リダイレクト `<file` がサイズゲートを素通りし、70KiB 本文が親 stdout に載る

- 場所
  - `plugin/hooks/check-bash-read:266-301`（`tokenize` が `<` をリダイレクト演算子にしない）
  - `plugin/hooks/check-bash-read:318-329`（`collect_file_args` は単語オペランドだけを見る）
  - `plugin/hooks/check-bash-read:481-482`（`FILES` が空なら `head`/`tail` は即 `pass`）
  - `plugin/hooks/check-bash-read:660-662`（`cat`/`less`/`more` もファイル引数 0 件なら通過）
- 再現

```bash
export PYTHONDONTWRITEBYTECODE=1
FIX=/tmp/shunt-adv/fix
HOOK=/home/dev/projects/skills/token-shunt/plugin/hooks/check-bash-read
mkdir -p "$FIX"
python3 - <<'PY'
from pathlib import Path
p = Path("/tmp/shunt-adv/fix")
p.mkdir(parents=True, exist_ok=True)
(p/"large.txt").write_bytes((b"L"*700 + b"\n") * 120)   # 84120 bytes
(p/"oneline.txt").write_bytes(b"{" + b"x"*70000 + b"}")  # 70002 bytes
PY

run() {
  local cmd=$1
  python3 - "$HOOK" "$cmd" <<'PY'
import json,sys,subprocess
hook,cmd=sys.argv[1],sys.argv[2]
p=subprocess.run([hook],input=json.dumps({"tool_input":{"command":cmd}}).encode(),
                 capture_output=True,cwd="/tmp/shunt-adv/fix")
d="pass" if not p.stdout.strip() else json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"]
print("hook", d)
PY
  bash --noprofile --norc -c "$cmd" | wc -c
}

cd "$FIX"
run 'cat large.txt'                 # deny, 84120  — 対照（契約どおり）
run 'cat <large.txt'                # pass, 84120  — バイパス
run 'cat<large.txt'                 # pass, 84120
run '<large.txt cat'                # pass, 84120
run 'head -c 70000 large.txt'       # deny, 70000  — 必須ケース bash-head-c-70000 相当
run 'head -c 70000 <large.txt'      # pass, 70000  — バイパス
run 'head -n1 oneline.txt'          # deny, 70002  — 必須ケース bash-head-n-1-minify 相当
run 'head -n1 <oneline.txt'         # pass, 70002  — バイパス
run 'less <large.txt'               # pass, 84120
```

実測（この環境）: `cat <large.txt` / `head -c 70000 <large.txt` / `head -n1 <oneline.txt` はいずれもフック `pass`、bash の stdout はそれぞれ 84120 / 70000 / 70002 バイト。`cat < large.txt`（`<` の両側に空白）だけはファイル名が独立トークンになるため deny になる。空白なし、または `<` の直後にパスが密着する形はすべて通過する。

- 影響
  README の Bash 表は「単独の `cat` / `less` / `more` は入力ファイル全体」「単独の `head` / `tail` は解釈できる行数・バイト数を判定」と書く。設計 §10-7 は `head -c 70000` を `actual=min(C,st_size)` で deny、`head -n 1` の 70KiB 行も deny とする。必須フック eval（`bash-cat-large`、`bash-head-c-70000`、`bash-head-n-1-minify`）はファイルオペランド形だけを試す。親エージェントは `cat <file` や `head -c 70000 <file` を普通に出すので、ゲート対象コマンドのまま 64KiB 超の本文を親ツール結果へ流せる。パイプ末尾の `head -c 70000` は deny されるのに、同等の stdin リダイレクトは通る。§15 の既知穴（未知パイプ末尾、`bash -c`、`python -c`、逐次 Read）には載っていない。
- 修正方向
  `tokenize` で引用外の `<` / `<>` / `n<` をリダイレクトとして切り、そのターゲットが通常ファイルなら `FILES` に入れる。`head`/`tail` は空の `FILES` でも、解釈できた `-c C` が `MIN_BYTES` 超、または行形式で明示入力があるなら deny。パイプ末尾の stdin `head -n` と同じ「バイト数が分からない行指定は deny」を単独コマンドにも揃える。
- 確信度
  高（フック判定と bash 実出力の両方を再現）

### P2: ANSI-C 引用 `$'path'` が明示ファイル検査を外す

- 場所
  - `plugin/hooks/check-bash-read:266-301`（`tokenize` の引用状態は `'` / `"` / `\` のみ。`$` は通常文字）
  - `plugin/hooks/check-bash-read:327`（クォート除去後のトークン `$large.txt` は既存ファイルではない）
- 再現

```bash
cd /tmp/shunt-adv/fix
python3 - <<'PY'
import json,subprocess
hook="/home/dev/projects/skills/token-shunt/plugin/hooks/check-bash-read"
for cmd in ["cat large.txt", "cat 'large.txt'", "cat $'large.txt'", "cat $'/tmp/shunt-adv/fix/large.txt'"]:
    p=subprocess.run([hook],input=json.dumps({"tool_input":{"command":cmd}}).encode(),
                     capture_output=True,cwd="/tmp/shunt-adv/fix")
    d="pass" if not p.stdout.strip() else json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"]
    b=subprocess.run(["bash","--noprofile","--norc","-c",cmd],capture_output=True,cwd="/tmp/shunt-adv/fix")
    print(d, len(b.stdout), cmd)
PY
```

実測: `cat large.txt` と `cat 'large.txt'` は deny。`cat $'large.txt'` は hook `pass`、bash stdout 84120 バイト。

- 影響
  README は引用を踏まえて明示入力ファイルを検査すると書く。`'path'` / `"path"` はファイル名に復元されるが、`$''` は `$` が残るため「対象 0 件 → 通過」。空白・改行・パイプ文字を含むパスを扱うために `$''` はよく使われる。プラグイン自身が「変わったファイル名も指定パスそのものを見る」と謳う経路で、引用を変えるだけで `cat` が通る。
- 修正方向
  通常状態で `$'` を見たら ANSI-C 引用として中身を 1 トークンに復元する。解釈しないなら、`$''` を含むサイズ対象コマンドは解釈不能として全文閾値へ落とす（fail-closed）。
- 確信度
  高。設計 §10-4 の状態機械は `'` / `"` / `\` だけなので、仕様の列挙そのものは狭い。ただし表の「単独 cat は明示ファイルを判定」より実装が弱い。

### P2: Bash フックがコマンド末尾の改行を落とし、末尾改行付きの大きいファイルを小さい同名ファイルとして通過させる

- 場所
  - `plugin/hooks/check-bash-read:148-150`（`cmd=$(jq -r ...)` と末尾空白 trim）
  - 対照: `plugin/hooks/check-file-size:137-140`（`jq -j` + sentinel で末尾 LF を保持）
- 再現

```bash
FIX=/tmp/shunt-adv/fix
python3 - <<'PY'
import json, os, subprocess
from pathlib import Path
fix = Path("/tmp/shunt-adv/fix")
(fix/"nlfile.txt").write_bytes(b"SMALL_COUNTERPART\n")          # 18 bytes
(fix/"nlfile.txt\n").write_bytes((b"L"*700 + b"\n") * 120)      # 84120 bytes
hook = "/home/dev/projects/skills/token-shunt/plugin/hooks"
cmd = "cat " + str(fix/"nlfile.txt\n")   # コマンド文字列が LF で終わる
print("command repr", repr(cmd))
p = subprocess.run([hook+"/check-bash-read"],
                   input=json.dumps({"tool_input":{"command": cmd}}).encode(),
                   capture_output=True, cwd=str(fix))
print("bash hook", "pass" if not p.stdout.strip() else json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"])
p = subprocess.run([hook+"/check-file-size"],
                   input=json.dumps({"tool_input":{"file_path": str(fix/"nlfile.txt\n")}}).encode(),
                   capture_output=True)
print("read hook", "pass" if not p.stdout.strip() else json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"])
PY
```

実測: Read フックは末尾 LF 付きパスを deny。Bash フックは `pass`（trim 後に小さい `nlfile.txt` を見ている）。`evals/test_symlink_hooks.py` の `test_read_preserves_trailing_newlines` が Read 側でまさにこの取り違えを禁止している。

- 影響
  README の Read 節は末尾改行を保持して指定パスを検査すると明記する。Bash 側は同じディレクトリに「LF なしの小さいファイル」と「LF 付きの大きいファイル」があると、後者への `cat` を前者のサイズで通す。親 stdout には大きい方の本文が乗る。
- 修正方向
  コマンド抽出を `jq -j` + sentinel にし、trim は行末コメント処理の前に「末尾の ASCII space/tab だけ」へ限定する。ファイルオペランドの末尾 LF は Read フックと同じく保持する。
- 確信度
  高（Read は deny、Bash は pass を同一ペアで確認）

### P2: deny 後の Grep 本文回収を path_ok が検出せず、違反トランスクリプトが全チェック通過する

- 場所
  - `evals/compare/judge.py:653-664`（`bash_recovers_body` は Bash の `cat|head|...` とパイプだけ）
  - `evals/compare/judge.py:1119-1131`（`deny_bypass` は親の成功 Read と上記 Bash だけを見る。Grep ツールは見ない）
  - 契約: 設計 §11.8「Grep `output_mode=content` はフック対象外なので、契約と eval で担保する」。§26.5「deny 後の迂回回収も path_ok で検出する」
- 再現

```bash
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
import json, os, sys, tempfile
sys.path.insert(0, "/home/dev/projects/skills/token-shunt/evals/compare")
import judge
path = "/tmp/shunt-adv/fix/large.txt"
usage = {"input_tokens":10,"cache_read_input_tokens":0,"cache_creation_input_tokens":0,"output_tokens":5}
evs = [
    {"type":"system","subtype":"init","plugins":[{"name":"token-shunt"}]},
    {"type":"assistant","message":{"id":"m0","content":[{"type":"tool_use","id":"r0","name":"Read","input":{"file_path":path}}]}},
    {"type":"system","subtype":"hook_response","hook_name":"PreToolUse:Read",
     "output":json.dumps({"hookSpecificOutput":{"permissionDecision":"deny",
         "permissionDecisionReason":"File exceeds token-shunt thresholds. Use /token-shunt:bulk-reader."}})},
    {"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"r0","content":"denied","is_error":True}]}},
    {"type":"assistant","message":{"id":"mg","content":[{"type":"tool_use","id":"g1","name":"Grep",
        "input":{"path":path,"pattern":"payload","output_mode":"content"}}]}},
    {"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"g1","content":"1:{\"payload_sha\":\"LEAKED\"}"}]}},
    {"type":"assistant","message":{"id":"ma","content":[{"type":"tool_use","id":"a1","name":"Agent",
        "input":{"subagent_type":"token-shunt:bulk-reader","prompt":path}}]}},
    {"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"a1",
        "content":"confirmed: payload_sha — path: %s\nstatus: complete"%path}]}},
    {"type":"result","result":"LEAKED","usage":usage},
]
spec = {"id":"deny-grep","gold":["LEAKED"],"fixtures_abs":[path],
        "expect":{"delegate":{"agent_type":"token-shunt:bulk-reader","deny_route":{"path":path},
                              "child_no_body":True,"child_msg_max":4000}}}
f=tempfile.NamedTemporaryFile("w",suffix=".jsonl",delete=False)
for e in evs: f.write(json.dumps(e)+"\n")
f.close()
v, ok = judge.judge(f.name, spec, {"mode":"auto"})
os.unlink(f.name)
print(v["verdict"], ok, v["checks"].get("deny_bypass"), v["reasons"])
print("python -c recovered?", judge.bash_recovers_body(
    {"input":{"command":"python3 -c \"print(open(%r).read())\""%path}}, path))
PY
```

実測: `verdict=pass`、`deny_bypass=True`、`reasons=[]`。同じパスへの親 Grep content で答えを取り、短い Agent 返答を付けただけでも deny-route 契約を満たす。`python3 -c 'open(path).read()'` も `bash_recovers_body` は False。

- 影響
  compare-hook-deny-route と B の大容量委譲は、deny 後の連続 Read とパイプ回収だけを機械検出する。実エージェントが Read deny の直後にやる次手は Grep content である。§11.8 が eval で塞ぐとした穴が、判定器に実装されていない。gold は Grep 結果から埋められる。isolation_ok も短い Grep ヒットでは壊れない。
- 修正方向
  `deny_bypass` 対象パスへの親 `Grep` で `output_mode` が `content`（欠落時の既定も含む）、または `-A`/`-B`/`-C`/`-o` 付きのものを fail にする。編集ケースの位置特定は既存 `edit_flow` の短い一意ヒットだけ例外にする。Bash の `python -c` / `sed` / `nl` は §15 のフック既知穴だが、§26.5 が「判定不能は pass にしない」と書くなら `open(path)` 系も同じゲートに入れる。
- 確信度
  高（合成トランスクリプトが deny_route / deny_bypass / agent_type / child_no_body 全部 pass）。§26.5 本文が明示するのは Read とパイプだけなので、Grep を「§11.8 の eval 担保」として読む点が本指摘の前提。

### P2: fixture が読めないとき child_no_body は 2KiB 引用を fail-open し、1 行 3000 バイトの漏れを通す

- 場所
  - `evals/compare/judge.py:733-754`（`quote_leak` は `body is None` で `continue`）
  - `evals/compare/judge.py:1157-1167`（フォールバックは `long_nonempty_run`＝21 行以上だけ。1 行には効かない）
  - 対照: `evals/compare/judge.py:1665-1681`（`leakcheck` は読めなければ exit 2＝未検証。clean 扱いにしない）
- 再現

```bash
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
import json, os, sys, tempfile
sys.path.insert(0, "/home/dev/projects/skills/token-shunt/evals/compare")
import judge
usage = {"input_tokens":10,"cache_read_input_tokens":0,"cache_creation_input_tokens":0,"output_tokens":5}

def run(path, body):
    evs = [
        {"type":"system","subtype":"init","plugins":[{"name":"token-shunt"}]},
        {"type":"assistant","message":{"id":"ma","model":"claude-sonnet-4","content":[
            {"type":"tool_use","id":"a1","name":"Agent",
             "input":{"subagent_type":"token-shunt:bulk-reader","prompt":path}}]}},
        {"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"a1","content":body}]}},
        {"type":"result","result":"ok","usage":usage},
    ]
    spec = {"id":"qleak","fixtures":[path],"fixtures_abs":[path],
            "expect":{"delegate":{"agent_type":"token-shunt:bulk-reader",
                                  "child_no_body":True,"child_msg_max":4000}}}
    f=tempfile.NamedTemporaryFile("w",suffix=".jsonl",delete=False)
    for e in evs: f.write(json.dumps(e)+"\n")
    f.close()
    v, ok = judge.judge(f.name, spec, {"mode":"delegate"})
    os.unlink(f.name)
    print(path, v["verdict"], v["reasons"][:1], "child_no_body", v["checks"].get("child_no_body"))

missing = "/tmp/shunt-adv/does-not-exist-oneline.json"
run(missing, "Y"*3000)  # 2048 < 3000 < 4000、1 行
exist = "/tmp/shunt-adv/fix/oneline.txt"
run(exist, open(exist,encoding="utf-8",errors="replace").read()[:3000])
PY
```

実測: 欠損 fixture への 3000 バイト 1 行引用は `verdict=pass` / `child_no_body=True`。同じ 3000 バイトを実在する `oneline.txt` から取ると `child_no_body: >2KiB contiguous quote` で fail。

- 影響
  設計 §13 の子→親契約は「20 行超 **または** 2KiB 超の連続引用」。compare-one-line は 70KiB の 1 行 JSON で、まさに 21 行検査が無力なクラス。fixture パス解決失敗・権限エラー時、writer の `leakcheck` は未検証（exit 2）にする一方、reader の `child_no_body` は「漏れなし」として通す。文字数キャップ 4000 より短い 2049–4000 バイトの 1 行引用が残る。
- 修正方向
  `quote_leak` がどの fixture も読めなければ `child_no_body` を fail（判定不能）。`leakcheck` の exit 2 と同じ。フォールバックの 21 行検査を 2KiB 検査の代用にしない。
- 確信度
  高。実ランナーが fixture を正しく置けば本番 compare-one-line は読めるので、発火条件はパス解決失敗・消失。それでも判定器の契約は「判定不能を pass にしない」。

## 不具合としない観察

- `tool_input.agent_type=token-shunt:bulk-reader` は Read/Bash とも deny。トップレベル完全一致だけ免除。README / 設計 §8.4 どおり。
- `hooks.json` の `"args": []` は Claude Code の exec form（shell なし spawn）。`CLAUDE_PLUGIN_ROOT` に空白があっても `bash -c "$command"` には乗らない。パス空白によるフック起動失敗は、現行マニフェストでは再現根拠がない。
- `command cat` / `exec cat` / `eval cat` / `env cat` / `{ cat f; }` / `(cat f)` / `time cat` / `bash -c 'cat f'` / `cat f | command cat` / `cat f | stdbuf -o0 cat` は先頭トークンまたは未知パイプ末尾で通過する。設計 §10-5 と §15 の意図した限定パーサ / fail-open。
- `cat f | grep`、`sed`、`python -c`、`nl`、`dd` はフック対象外。README / §15 に明記。ただし上の P2 のとおり、**eval が Grep を担保すると書いた部分**は別。
- `tee < large` が通るのは、単独コマンドのサイズ対象が `cat|head|tail|less|more` だけで `tee` はパイプ末尾にしか出てこないため。仕様の列挙どおり。
- 除外拡張子の symlink（`large.txt` を `fake.png` にリンク）は Read フックがパス拡張子で通過する。設計 §8 は path の最終拡張子。公式 Read が画像経路に乗るかは本レビューの範囲外。
- FIFO / デバイスは `[[ -f ]]` でないので通過。設計「通常ファイルでないなら通過」。
- `gold_confirmed` は `gold_paths` の basename 部分文字列。`/tmp/other/user.rb` でも `user.rb` を含めば通る。cases.json が basename を針にしているので、実装は設定どおり。推測を `confirmed:` で包むのは形式検査の限界。
- `deny_route` の deny が別ファイルのものでも、対象パスへの成功 Read は `deny_bypass_paths` が `deny_route.path` を必ず足すため fail になる。ここは塞がっていた。
- 走査予算の「時間は走査後」は README / §15 の既知限界。安価な FIFO では `-f` でないためスキャン自体に入らない。FUSE 遅延は未再現。
- 検証段階の表と散文は、`verification:` / `status:` なしの「complete / requirements」言及を主張にしない。`flow_checks.py` の回帰どおり。
- 子 Read の行番号ラベルを合成して「途中打ち切り」に見せる重複 Read は、実 CLI の tool_result をモデルが書けない限り到達しない。

## 検証

```text
フック: /tmp/shunt-adv/fix に 84120 バイト large.txt と 70002 バイト oneline.txt を置き、
check-bash-read へ JSON stdin、同時に bash --noprofile --norc -c の stdout バイト数を計測。
判定器: PYTHONDONTWRITEBYTECODE=1 python3 で evals/compare を sys.path に入れ、
judge.judge() に合成 JSONL を渡した。evals/compare/run.sh は未実行。
```

確認した不具合は P1×1、P2×4。stdin リダイレクトは必須フック eval がファイルオペランド形しか置いていないため、現行ゲートの実効範囲は文書より狭い。
