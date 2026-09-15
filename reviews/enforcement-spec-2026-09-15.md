# Grep フックの具体設計と `gold_confirmed` の転記方式（2026-09-15）

`reviews/enforcement-design-2026-09-15.md` の続き。
**実装なし・課金測定なし。** CLI 2.1.271 のスキーマ確認と、
既存45実行の再集計だけで書いている。

## 0. 仕様確認で分かった2点（先に訂正）

### 0.1 `head_limit` 未指定は「無制限」ではなく **250**

CLI のスキーマ本文:

> `head_limit` … Defaults to 250 when unspecified. **Pass 0 for unlimited**
> (use sparingly — large result sets waste context).

したがって `compare-edit-dense-lines` の3周で観測した
「`head_limit` なしの content Grep」は、無制限ではなく**250行返し得る
呼び出し**である。§26.5 の上限20に対して違反であることは変わらないが、
既存記録で「無制限」と表現した箇所は不正確だった
（`reviews/head-limit-consistency-2026-09-15.md` §3 ほか）。
なお `0` を適合扱いにしない判定（`7fed1c3`）は、**0 が無制限を意味する**
という本スキーマによって裏づけられた。

### 0.2 Grep には `offset` と `multiline` がある

| フィールド | 意味 | 形式強制への影響 |
|---|---|---|
| `offset` | `head_limit` 適用前に N 行/件スキップ。全 output_mode で有効 | `head_limit=20` のまま `offset` をずらして繰り返せば、**1回あたりの上限を守ったまま全文を回収できる**。1呼び出しの形式検査では防げない |
| `multiline` | `.` が改行に一致し、パターンが行をまたぐ | 1「行」が巨大になり得る。**行数の上限が返却量の上限にならない** |

既存の判定器（`flow_checks.position_grep_errors`）はどちらも見ていない。

## 1. 強制できる範囲の切り分け

フックに何ができて何ができないかを3層に分ける。
**この区別を曖昧にしたまま実装しないこと。**

| 層 | 内容 | フックで強制できるか |
|---|---|---|
| L1 呼び出しの形式 | `output_mode` / `head_limit` / `offset` / `multiline` / `-A`・`-B`・`-C` が §26.5 の形に合うか | **できる**。`tool_input` だけで判定できる |
| L2 呼び出しの順序 | 対象について計測が先に済んでいるか | **条件つきでできる**。セッション状態が要り、状態を失えば劣化する（§3.4） |
| L3 意図と結果 | 「答えを取りにいっているのか、位置を特定しているのか」「委譲すべきだったか」 | **できない** |

### 1.1 形式を強制しても防げないこと

- **答えを検索して委譲を回避する行動は防げない。** `head_limit=20` を
  守ったまま `offset` を 0, 20, 40 …とずらせば、形式検査を全部通過した
  まま本文を回収できる。§26.5 の趣旨（ルートを無効化させない）は
  1呼び出しの形式では守りきれない。
  - 対策の方向（未設計）: 同一 (session, agent, path) の content Grep
    回数・累積返却行数に上限を置く。これは L1 ではなく L2 の状態管理に
    なる。
- **`multiline` による1行の肥大も防げない。** 行数上限は返却バイト数の
  上限ではない。初版では `multiline: true` を予算超過対象で拒否する案が
  あるが、正当な用途を塞ぐ可能性があり未判断。

### 1.2 フックがサイズを測っても「親がルート判断した」ことにはならない

フックが `stat` 相当を実行して 80032 B と知っても、**その値は親の文脈に
入らない**（deny しない限り）。したがって L2 で強制できるのは

> 親が自分で計測するか、Read deny でサイズを受け取るまで、
> 予算超過であり得る対象への content 検索を許さない

という**順序**だけである。計測された値をもとに親が正しく委譲したか
どうかは、フックからは観測できない。**「計測済み」状態は、親の判断の
証拠ではなく、親に情報が渡る機会があったことの記録にすぎない。**
今回の実測（`auto-edit-grep-location` で計測が0/9）は「順序が守られて
いない」ことの証拠であって、順序を強制すれば判断が正しくなるという
根拠ではない。

## 2. 対象集合の確定

`head_limit` 判定のサイズ比較には対象の確定が要る。`path` は次を取り得る。

| `path` の形 | 対象集合 | 扱い |
|---|---|---|
| 単一ファイル | 確定する | サイズを測り、予算超過なら形式要件を課す |
| ディレクトリ | 確定しない | **列挙しない。形式要件を無条件に課す** |
| 省略（cwd 既定） | 確定しない | 同上 |
| `glob` 併用 | 確定しない | 同上 |

**確定できない場合に列挙も素通しもしない。** 理屈は次のとおり。

- 対象集合が確定しないということは、**予算超過ファイルを含む可能性を
  排除できない**ということである。
- 排除できない以上、§26.5 の形式要件（`files_with_matches`、または
  `content` + `head_limit` 1-20、`-A`/`-B`/`-C` なし）を課す側に倒す。
- サイズ比較を省くので、**ディレクトリの列挙は一切行わない**。
  コストが読めない走査は発生しない。

副作用として、予算内ファイルだけを含むディレクトリ検索にも形式要件が
かかる。回復は `head_limit` を付ける1往復で済む。
`glob` を展開して「全部予算内」と確認できれば免除できるが、展開コストが
読めないため初版では行わない。

**実測の分布**（45実行、親 Grep 20件）: 全20件が単一ファイルパスかつ
`output_mode=content` で、確定しないケースは出ていない。ただしこれは
本スイートの性質であり、一般の分布の根拠にはならない。

## 3. 「計測済み」状態の定義

### 3.1 記録の単位

`(session_id, agent_id)` ごとに、対象ファイルの**同一性キー**で記録する。

```
key   = (st_dev, st_ino)
value = {path, st_size, st_mtime_ns, recorded_at, source}
```

`(dev, ino)` だけでは inode 再利用を取りこぼすので、失効判定は
`st_size` と `st_mtime_ns` を併用する（§3.3）。
保存先は既存の `check-reader-contract` と同じ
`$TMPDIR/token-shunt-reader-<uid>/` 配下、所有者・権限の検査も同じ。

### 3.2 記録される契機

| 契機 | フック | 計測済みとみなす根拠 |
|---|---|---|
| 親が `stat` / `wc -c` を実行 | `check-bash-read`（既に Bash の PreToolUse にいる） | 親自身が測った |
| Read deny が契約を描画した | `check-file-size` | 契約は `<絶対パス> (<N> B)` を含む（`contract_add_path`）。**対象とサイズが親へ通知されている** |
| Read が成功した | — | **記録しない**。本文が渡っただけで、§26.5 が求める「メタデータからの判断」ではない |

Read deny を計測済みに数えるのは、通知が実際に起きた場合に限る。
契約の描画に失敗して短い deny 文だけになった経路
（`deny_contract` のフォールバック）では**サイズが載らない**ので
記録しない。

### 3.3 失効

| 事象 | 判定 | 結果 |
|---|---|---|
| ファイルが書き換わった | 現在の `(st_size, st_mtime_ns)` が記録と違う | **失効**。再計測を要求 |
| inode が別ファイルに再利用された | 同上で検出（サイズか mtime が一致する確率は低い） | 失効 |
| 対象が消えた | `stat` が失敗 | 失効。ただし Grep 自体が失敗するので deny はしない |
| セッション終了 | 状態ディレクトリごと破棄 | 失効 |
| compact / resume で状態が読めない | 状態なし | **失効扱い（fail-closed）**。親は一度測っているが、再計測の1往復を払う |

**時間ベースの TTL は置かない。** ファイル同一性で失効を判定できるので、
経過時間だけで失効させると正しい状態を捨てることになる。
状態ファイル自体の寿命は既存の reader state と同じ扱いにする。

### 3.4 L2 の限界（再掲）

状態が失われた時に fail-closed で再計測を求める設計は、
**規則を守っている親にも1往復を課す**。逆に fail-open にすると
compact 後は規則が消える。どちらを取るかは未判断。

## 4. 判定と出力

拒否（警告ではない）。`PreToolUse` の
`hookSpecificOutput.permissionDecision = "deny"` を返す。

擬似コード（実装ではない）:

```
if tool != Grep: pass
if output_mode != "content": pass          # files_with_matches は対象外
target = resolve(path, glob)
if target is a single file:
    if size(target) <= 16384: pass          # 予算内は §11.6 の編集経路
    if not measured(target): deny("measure first")
else:                                       # 確定しない
    pass_size_check()                       # 列挙しない
if head_limit is None or not (1 <= head_limit <= 20): deny("form")
if any of -A/-B/-C: deny("form")
```

deny 文には、違反した条件・通る形（`files_with_matches` または
`head_limit` 1-20）・未計測なら `stat`/`wc -c` を先に、を書く。
`offset` と `multiline` は §1.1 のとおり**初版では判定しない**。

### 4.1 拒否ループの上限

`check-reader-contract` は `calls >= 6` で頭打ちにしている。同じ形が要る。
上限に達した後の扱い（deny を続けるか、`additionalContext` に落として
通すか）は未判断。

## 5. 費用（見積りの訂正）

前回の「+$0.006/実行」は **「各 Grep で拒否が最大1回」という仮定の
概算**であり、最悪値ではない。再拒否があり得る。

拒否は少なくとも次の順で重なり得る。

1. 未計測 → deny（計測せよ）
2. 計測後、`head_limit` なし → deny（形式）
3. `head_limit` は付けたが `-A` 併用 → deny（形式）

| 値 | 根拠 |
|---|---|
| 親ターン1回 | 約 **$0.013**（45実行・360親ターン・$4.68 の実測平均） |
| 判定対象の親 Grep | 0.44 件/実行（20 / 45） |
| 拒否 k 回あたり | 約 **k × $0.013 × 0.44 /実行** |

k = 1 で +$0.006/実行、k = 3 で +$0.017/実行。
**k の分布は未測定であり、上限も分かっていない**（§4.1 の頭打ちを
入れれば k ≤ 6 になる）。

## 6. `gold_confirmed` — A案（転記方式）の具体化

### 6.1 置き換える文

現行 description（`545b660` で入れたもの）:

```
In the final answer keep one `confirmed: <absolute path> — <fact>`
bullet per corroborated fact, path unabbreviated.
```

これは**結果の要求**であり、何をどう写すかの手順がない。
実測では `auto-explicit-multifile` で 0/9。
一方、同じ親が `status:` / `stop_reason:` の逐語コピーは全ケース 3/3
成立させている。差は文面にあり、後者は
「verbatim as separate plain lines」＝**転記の手順**である。

### 6.2 提案する文（未適用）

```
Copy each worker `confirmed:` line verbatim, one per line, not merged or
reworded; duplicates once; pathless lines are `unconfirmed:`.
```

134 B。現行文（118 B）と入れ替えると SKILL.md は 6972 → **6988 B**、
上限 7000 B 内（残り 12 B）。**7000 B の上限は変更しない。**

### 6.3 例外の扱い

| 事象 | 規定 | 理由 |
|---|---|---|
| 子が絶対パスを欠いた行を返した | `unconfirmed:` として写す | 実測 `run.qmvXaj0z/sonnet` で発生。逐語転記をそのまま適用すると、親が**子の非遵守を `confirmed:` のまま昇格させる**ことになる。既存設計の「推測を `confirmed` にしない」と整合し、製品要件（`README.md:73`）にも反しない |
| 複数バッチで同じ行が返った | 完全一致する行は1回だけ写す | 4+ paths 分割時に同一事実が複数の子から返る。**完全一致だけを重複とみなす**。言い換えて重複判定すると逐語性が壊れるため、部分的に違う行は両方残す |
| パスは違うが事実が同じ | 両方残す | 別の根拠であり、§2 の「一致が確認できる事実だけを統合」に沿う |
| 子が `confirmed:` を1行も返さない | 写すものがない。親は `partial` として報告 | 既存の `child_status` 経路に合流する |

### 6.4 この案の限界

- **A案も文言の追加であり、今回3件で効かなかった手段そのものである。**
  他と違うのは、同じ「転記」という形の契約（`status:`/`stop_reason:`）が
  全ケースで成立しているという実測がある点だけで、
  転記なら効くという証明ではない。
- 逐語転記は親の出力トークンを増やす。子の `confirmed:` は4000字契約内、
  実測で3〜6項目なので増分は数百字。親ターン単価 $0.013 に対して誤差の
  範囲だが、測っていない。
- 検証は、契約テストで文面を固定したうえで、動作測定が要る。

## 7. B案（`Stop` フック）— 保留。仕様確認の結果

**`continue: false` は差し戻しではない。** CLI のスキーマ本文:

> `continue` - Set to `false` to block/stop (default: true)
>
> … "block" produced when ok is false. **Default false (turn ends).**
> Whether continue:true lets the turn proceed depends on the event's
> decision:

つまり `continue: false` は**ターンを終わらせる**。これを差し戻しの
つもりで使うと、**誤って応答を打ち切る**。

差し戻し（モデルの再呼び出し）は `Stop` / `PostToolUse` /
`UserPromptSubmit` の `decision: "block"` + `reason` である
（`PreToolUse` では非推奨で、`hookSpecificOutput.permissionDecision`
を使う）。

さらに、その `block` が**破棄される経路**が存在する:

> Stop hook block discarded (turn ended by tool result / MCP end-turn /
> loop tick, **no model re-invoke**)

ループ対策として `stop_hook_active` が入力に渡り、true の間は成功を
返すことが求められる（上限は `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`）。

したがって B案を実装するなら:

1. `continue: false` は使わない（停止と継続要求は別物）。
2. `decision: "block"` + `reason` を使う。
3. `stop_hook_active` を必ず見て、true なら素通しする。
4. block が破棄される経路があるため、**強制手段としての信頼性は
   実機確認が要る**。

本記録では実機確認していない。B案は保留のままとする。

## 8. 未判断として残すもの

- ディレクトリ・`glob` を `glob` 展開で免除するか（コスト不明）。
- `offset` の累積と `multiline` をどう扱うか（§1.1）。
- L2 の状態欠落時に fail-closed / fail-open のどちらを取るか（§3.4）。
- 拒否ループ上限に達した後の挙動（§4.1）。
- A案を適用するか（§6.4 のとおり、文言追加であることは変わらない）。
