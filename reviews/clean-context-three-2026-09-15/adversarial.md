# 敵対的レビュー（クリーンコンテキスト）

実施日: 2026-09-15。会話非継承。reviews/・git履歴は根拠にしない。ソース変更なし。再現は /tmp のみ。

対象 HEAD: 83a3602。ゲートは現行ソースと `/tmp/token-shunt-adv-20260915` でのフック実行だけで判定した。Claude Code 2.1.272 の Grep スキーマはローカルバイナリから確認した。

## 指摘事項

### P1 — `stat`/`wc -c` の「測定」がサイズ非告知でも content Grep を許可する

- 証拠: `plugin/hooks/grep_bounds.py:43`（`_UNSAFE` に `#` が無い）、`plugin/hooks/grep_bounds.py:100-135`（`metadata_paths` は `stat` の出力形式を見ない。`-c` の次語を捨てて残りのオペランドを記録する）、`plugin/hooks/grep_bounds.py:72-81`（`record` は inode/size/mtime を残すだけで「呼び出し元がサイズを見た」ことを検証しない）、`plugin/hooks/grep_bounds.py:189-197`（未測定なら拒否、測定済みなら形式検査へ進む）、`plugin/hooks/check-grep-bounds:119-134`（PostToolUse Bash で `metadata_paths` の結果を記録する）。README は「サイズは引数が展開を含まない `wc -c` / `stat` と、拒否本文が実際にサイズを告げたパスから記録」と書く。実装は「サイズを告げた」を検証していない。
- 再現: 80,006 B のファイルで PostToolUse のあと PreToolUse Grep。

```bash
FIX=/tmp/token-shunt-adv-20260915/fix2
HOOK=/home/dev/projects/skills/token-shunt/plugin/hooks/check-grep-bounds
LARGE=$FIX/large-80k.txt   # 80006 B
SMALL=$FIX/small.txt

# 1) サイズを出さない stat。実 bash の stdout はパス名のみ
stat -c %n "$LARGE"
# stdout: /tmp/.../large-80k.txt  （数字ではない）

python3 - <<'PY'
import json, subprocess
from pathlib import Path
HOOK="/home/dev/projects/skills/token-shunt/plugin/hooks/check-grep-bounds"
L=str(Path("/tmp/token-shunt-adv-20260915/fix2/large-80k.txt"))
S=str(Path("/tmp/token-shunt-adv-20260915/fix2/small.txt"))
def run(ev):
    p=subprocess.run([HOOK], input=json.dumps(ev), capture_output=True, text=True)
    print("rc", p.returncode, "out", p.stdout[:180] or "(empty=pass)")
run({"hook_event_name":"PostToolUse","tool_name":"Bash","session_id":"s-statn",
     "tool_input":{"command":"stat -c %n "+L}})
run({"hook_event_name":"PreToolUse","tool_name":"Grep","session_id":"s-statn",
     "tool_input":{"pattern":"LEAK","output_mode":"content","path":L,"head_limit":5}})
# -> out empty = pass

# 2) コメントで測定していないパスを混ぜる。実 bash は small だけ数える
run({"hook_event_name":"PostToolUse","tool_name":"Bash","session_id":"s-hash",
     "tool_input":{"command":"wc -c %s # %s"%(S,L)}})
run({"hook_event_name":"PreToolUse","tool_name":"Grep","session_id":"s-hash",
     "tool_input":{"pattern":"LEAK","output_mode":"content","path":L,"head_limit":5}})
# -> out empty = pass
# 実 bash: wc -c small # large  の stdout は "6 .../small.txt" のみ
PY
```

結果: `stat -c %n` も `wc -c small # large` も PostToolUse が large を測定済みにし、続く `output_mode=content` + `head_limit=5` は deny JSON 無し（pass）。同じ測定のあと `head_limit` 無しの content Grep は「no bound」で拒否された（第2規則は残る）。
- 影響: 「メタデータが先」が黙って落ちる。親はサイズを知らないまま超過ファイルへ content Grep できる。1回あたりは `head_limit` 1–20 行（Claude 2.1.272 ではさらに `--max-columns 500` と `maxResultSizeChars:20000`）なので全文ダンプではない。ただしスキルがサイズを見て委譲する前提を外す。
- README 既知限界との関係: 未記載。README は記録源を「`wc -c` / `stat`」と書くが、形式がサイズを含むことまでは要求として実装されていない。コメント `#` も「展開を含まない」検査の対象外。

### P1 — `confirmed: /abs/path:行` を消失ファイル扱いし、保持違反を見逃す

- 証拠: `plugin/hooks/sendback_retention.py:80-86`（citation は `:12` まで取り込み、末尾の `.,;:)` だけ削る）、`plugin/hooks/sendback_retention.py:112-124`（存在しないパスは VIOLATION ではなく UNDETERMINED）、`plugin/hooks/sendback_retention.py:136-149`（usable が空で unknown だけなら child_items は undetermined）、`plugin/hooks/sendback_stop.py:296-298`（worker 側も undetermined なら block しない）。
- 再現:

```python
import sendback_retention as rc, sendback_stop as ss
from pathlib import Path
p = "/tmp/token-shunt-adv-20260915/fix2/large-80k.txt"  # 実在
line = f"confirmed: {p}:12 — TOKEN is 42"
print(rc.citation(line))
# -> /tmp/.../large-80k.txt:12
print(rc.classify_path(rc.citation(line)))
# -> undetermined
print(rc.check_child_items([line + "\nstatus: complete"]))
# -> status=undetermined, reason='every worker citation names a file that no longer exists'
rec, out = ss.decide({
    "hook_event_name": "SubagentStop",
    "agent_type": "token-shunt:bulk-reader",
    "agent_id": "r1",
    "last_assistant_message": line + "\nstatus: complete\nstop_reason: done",
})
print(rec["outcome"], rec["reason"], out)
# -> no_block  worker items undetermined  {}
```

- 影響: 行番号付きパスは LLM がよく書く形。この形だと SubagentStop も親 Stop も差し戻さない。親が `confirmed:` 行を落としても通過する。契約文面は `confirmed: <absolute path> — fact` だが、ゲートは「絶対パスが付いているがファイルが無い」を親の落ち度にしないため、`:行` が消失と区別できない。
- README 既知限界との関係: 未記載。「引用先が現存しないなど判定不能を違反にしない」は意図だが、生きているファイルへの `:12` 付与まで判定不能に落とすのは記載より広い見逃し。

### P1 — 取得不能な bulk-reader 起動が1件あると、成功ワーカーの drop も判定しない

- 証拠: `plugin/hooks/sendback_session.py:311-316`。`usable` があっても `blocked`（`text is None`）が1件でもあれば `child_texts` は `None`。`plugin/hooks/sendback_stop.py:370-372` はそれを `worker output unobtainable` として通す。
- 再現: 成功した reader（usable な `confirmed:` 行あり）のセッションに、transcript も notification も無い `agentType=token-shunt:bulk-reader` の meta.json を1つ足す。親は confirmed 行を落とす。

```
# 成功ワーカーだけの Stop:
outcome=blocked  lost_lines=1  decision=block

# 同じセッションに空の bulk-reader meta を追加した Stop:
outcome=no_block  reason=worker output unobtainable  out={}
```

具体 JSON は `/tmp/token-shunt-adv-20260915/repro.py` の `SB-PARENT-DROP` / `SB-POISON-UNAVAILABLE`。失敗起動の meta は `.../sid-retain/subagents/agent-cccccccccccccccccccccccccccccccccccc.meta.json` に `{"agentType":"token-shunt:bulk-reader","toolUseId":"tu2"}` だけ置いた。
- 影響: 失敗・未完了の reader 起動が1つあると、完了済みワーカーの行保持が全部オフになる。README の「出力が取得できないときは通す」は、そのワーカーを除外する話としては妥当だが、実装は成功分まで捨てる。
- README 既知限界との関係: 記載より悪い。「ワーカーの出力が取得できない／最終回答を特定できない」は突き合わせ対象が無いとき、と読める。成功ワーカーの本文は手元にある。

### P2 — Grep の `context` が実装済みの前後行禁止をすり抜ける

- 証拠: `plugin/hooks/grep_bounds.py:37`（`CONTEXT_FLAGS = ('-A', '-B', '-C')`）、`plugin/hooks/grep_bounds.py:138-157`（int の `-A/-B/-C` だけ見る。`context` キーも文字列の `-A` も無視）。Claude Code 2.1.272 の Grep 入力スキーマは `context` を rg `-C` の本体、`-C` をその alias としている（`$xs` 内: `if (F!==void 0) De.push("-C", F.toString()); else if (M!==void 0) ...`）。
- 再現: 測定済み 80,006 B ファイル。

```
tool_input: {output_mode:content, path:<large>, head_limit:5, "-C":5}
-> deny  "head_limit with a 5-line context window does not bound the returned lines"

tool_input: {output_mode:content, path:<large>, head_limit:5, "context":5}
-> pass  (stdout empty)
```

- 影響: ゲートが「前後行は上限を無効にする」として拒否する呼び出しと、CLI が同じ `-C` に写す呼び出しが、フィールド名だけで分岐する。2.1.272 では `head_limit` は文脈展開後の行配列をスライスするため、`context=5` + `head_limit=5` でも出力は5行で、無制限リークではない。規則の欠落は再現した。
- README 既知限界との関係: 未記載。README は `-A/-B/-C` だけ名指し。CLI の `context` は同義。

### P2 — 接頭辞の `Confirmed:` だけ変えた保持を改変として親を止める

- 証拠: `plugin/hooks/sendback_retention.py:53-61`（収集は `line.lower().startswith("confirmed:")` で大小無視）、`plugin/hooks/sendback_retention.py:43-50` と `215-233`（照合は `normalize` のみ。lower しない）。収集には乗るが本文一致には失敗し `altered` になる。
- 再現:

```python
good = "confirmed: /tmp/token-shunt-adv-20260915/fix2/large-80k.txt — TOKEN is 42"
parent = "Confirmed: /tmp/token-shunt-adv-20260915/fix2/large-80k.txt — TOKEN is 42"
# check_line_retention: status=violation, 1 altered
# Stop decide: outcome=blocked, file_coverage=ok, line_retention=violation
# リストマーカー付き "- confirmed: ..." は kept（markers は剥がす）
```

- 影響: スキルは verbatim。接頭辞のタイトルケースだけ変えた親は、事実もパスも残しているのに差し戻される。正しい回答を止め得る。
- README 既知限界との関係: 未記載。verbatim 方針の内側だが、収集だけ case-insensitive なのが不一致。

### P2 — deny 契約ブロブが親向け「読むな」と worker へ渡すパスを同一テキストに載せる

- 証拠: `plugin/hooks/reader-call-contract:1-13`（`Delegate now — do not read these paths yourself` と `prompt must contain exactly: your question, then the paths below` と `Never copy these instructions into it` が同一テンプレ）、`plugin/hooks/check-file-size:204-209`（Read 拒否理由としてこのテンプレを返す）、`plugin/skills/bulk-reader/SKILL.md` 明示委譲（契約ファイルを読んで `call Agent exactly as that contract specifies`）。
- 再現: 80,006 B への Read。`check-file-size` は deny。理由本文に次が同時に含まれることを確認した。

```
File exceeds token-shunt thresholds (bytes=80006/65536). ...
Delegate now — do not read these paths yourself, and do not load the
bulk-reader skill for this call.
Agent: subagent_type=token-shunt:bulk-reader
  ...
  prompt must contain exactly: your question, then the paths below with
  sizes. Never copy these instructions into it: they are addressed to
  you, and a worker told not to read the paths reports nothing.
paths:
/tmp/token-shunt-adv-20260915/fix2/large-80k.txt (80006 B)
```

- 影響: 親が deny 全文を Agent `prompt` に入れると、reader は「これらのパスを自分で読むな」と指示される。フックは起動を止めない。ワーカーが読まない経路へ送られる。機械的な本文リークではない。
- README 既知限界との関係: 未記載。テンプレ自身がコピー禁止を書いているが、禁止文とパスが同一ブロブ。

## 確認したが防がれる / 設計内

- **相対 Grep + イベント `cwd`**: フック起動ディレクトリに同名の小ファイルを置いても、`cwd` がセッション側なら大きい方を判定する（deny）。`plugin/hooks/check-grep-bounds:58-76`、`plugin/hooks/grep_bounds.py:68`。
- **`cwd` 省略**: フックプロセスの cwd で相対パスを解く。README 記載どおり。省略時にデコイ小ファイル側で pass するのは、ドキュメント済みの基準ディレクトリの話。
- **`--sized` / PostToolUse と壊れた `cwd`**: 相対オペランドは捨て、絶対パスだけ記録。絶対パスの `--sized` のあと Grep は pass。相対 `wc -c big.txt` + 不正 cwd では記録されず Grep は未測定 deny。
- **`tool_input.agent_type` 偽装**: Grep はトップレベルだけ見る。writer 偽装でも親向け `wc -c` 文面。Read のサイズ免除も `jq -r '.agent_type'` のみ（`plugin/hooks/check-file-size:224-236`）。80,006 B で `tool_input.agent_type=token-shunt:bulk-reader` は deny、トップレベル reader/writer は pass（免除は意図）。
- **writer 案内**: トップレベル `token-shunt:code-writer` の超過 content Grep は `wc -c` も bulk-reader も出さない。Bash が無い経路へ送らない。
- **writer 状態の分離**: `agent_id` 付き writer Grep は親の測定を使わない（未測定 deny）。欠落時は `plugin/hooks/check-grep-bounds:33` で `parent` に落ち、親の測定を共有して pass になるが、ワーカー PreToolUse に `agent_id` が付くかは実機未確認（下記）。
- **glob / ディレクトリ / 省略 path**: 単一ファイルに解けない Grep は判定しない。README と `target_file` の意図。
- **末尾スラッシュ**: Python `abspath` が `/file/` を `/file` に戻すので Grep は本体を判定する。Node `fs.statSync('/file/')` は ENOTDIR。Read フックは `[[ -f file/ ]]` が偽で pass するが、ツール側も読めない。
- **NUL 入り `file_path`**: bash のコマンド置換が NUL を削除してパスを連結し、存在しない名前になって pass し得る。Node 2.1.272 は `path must be ... without null bytes` で Read 自体が失敗する。本文リークにはならない。
- **不正 JSON の Grep**: exit 2（fail-closed）。
- **`DENY_CAP`**: 6 回拒否のあと、測定済みで `head_limit` 正当な Grep も止める。README の再試行抑止。
- **offset + head_limit ページング**: 測定後は通る。README「呼び出しをまたぐ読み取り量も集計しません」。
- **reader 契約**: 相対パス deny、offset≠cursor deny、欠ける `tool_use_id` は exit 2、非 reader と `tool_input.agent_type` 偽装は no-op。symlink は `realpath` で同一カーソル。6 回目以降は `budget_exhausted`。
- **sendback の成功パス**: 使える `confirmed: /abs — fact` を親がそのまま書けば `retention ok`。落とすと block。writer / Explore の SubagentStop は `not a bulk-reader worker`。`unconfirmed:` だけの報告は通す。`TOKEN_SHUNT_SENDBACK=off` は documented disable。
- **`last_assistant_message` がツール前ナレーションと同一**: `plugin/hooks/sendback_stop.py:149-150` が意図的に非判定。古い本文での誤 block を避ける設計。プレビューと同じ落ちた回答は見逃し得るが、README の「判定できるときだけ」に沿う。
- **check-agent-model**: `subagent_type` が token-shunt worker のとき、省略 / `auto` / `opus` / `inherit` / `fable` / `Haiku` / `haiku ` は deny。`haiku`/`sonnet` は pass。`tool_input.agent_type` や `type` に載せた起動はフック対象外だが、2.1.272 の AgentInput は `subagent_type` であり、これでは token-shunt worker は起動しない。Explore 等は README どおり止めない。
- **Bash `cat <file>` / `$(<file)`**: フック pass、実 bash は 80,006 B。README 制限事項の入力リダイレクト・コマンド置換。`cat large` と `head -c 70000 large` は deny（後者は bash なら 70000 B）。`head -c 100` は pass / 100 B。
- **ハードリンク**: reader 契約は `realpath` のみ。同一 inode の別パスは別カーソルとして 2 枠使う。親への本文リークではない。

## 疑ったが未検証

- writer の Grep PreToolUse で `agent_id` が空なら親の測定状態を共有するコードは再現した。2.1.272 のワーカーフック入力に常に `agent_id` が付くかは、この環境ではイベント実物が無く未確認。
- `output_mode: "Content"` はゲート未判定。Grep ツールは `strict` かつ enum が小文字だけなので、実ツールが受けるかは未確認。
- `-A: "3"`（文字列）は int 検査を外れて pass。strict スキーマが数値以外を落とすかはフック前段の話で未確認。
- multiline の1マッチが巨大でも、2.1.272 は `--max-columns 500` と 20k 文字上限がある。フックはバイト上限を見ていない。実出力の切り詰めは CLI 側の話。
- `check-file-size` / `check-bash-read` について、README 制限事項に無い新しいオペランド形の本文リークは、今回の試行では再現できなかった。
