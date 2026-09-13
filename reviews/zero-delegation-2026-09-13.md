# 委譲0回の6件の調査

対象: `evals/compare/tmp/runs/run.xv9H1gDW/`。実機再実行・判定器変更・スキル変更は行っていない。以下の行番号は `transcripts/<case>.auto.jsonl` の物理行。

## 結論

単一のスキル発見障害ではない。writer 4件は Skill 呼び出しと本文展開に成功している。3件は小仕事規則による親生成、1件は不存在参照の親での事前停止。reader 2件はプラグイン登録済みだが Skill を呼ばず、Grep 経由で正答した。6件とも親の Agent / Task 呼び出しは0回。

| ケース | 観測証拠 | 原因 |
|---|---|---|
| compare-code-writer-ok | L6 Skill、L16 参照179 bytes、L25 小仕事として親生成すると明言、L26 Write（19行） | A群の強制委譲例外が実行指示に反映されていない |
| compare-code-writer-no-ref | L10 Skill、L17–20 statで不存在確認、L21 委譲もWriteもしないと明言 | 「参照パス未指定」と「指定パスが不存在」の混同。子の拒否契約を親の事前停止が覆い隠す |
| writer-bounds | L6 Skill、L13 参照75 bytes、L23 小仕事規則を引用、L24 Write（5行） | 上限契約を測るfixtureが通常の小仕事分岐に入る |
| writer-verification-levels | L13/16/19/22 Skill、L32 参照75/56/56 bytes、L38 全件を小仕事と判定、L55/57/59/61 親Write | 小仕事分岐と委譲期待の衝突。Markdown specも明示的に30行。冒頭は「Three delegated generations」だが実際は4件 |
| auto-bulk-facts | L7 MAGIC_TOKENのGrepは該当なし、L17 65669 bytes、L21–22 magicのGrepで関数位置取得、L26 offset=1/limit=40のRead成功、L30 正答 | 範囲不明の大容量読取を委譲する前に、Grepで既知区間へ縮小できる。スキル未起動 |
| auto-one-line | L8–12 69886 bytesを確認、L14/17 Grep（-o）でキーと値を抽出、L19 正答 | 巨大行でも短い一致部分だけ取得でき、Read denyもスキル起動も発生しない |

## 設計・実装との対応

- 設計 §26.2 最終項は「§13 の機構強制ケース A は小仕事判定の例外」。§26.5 は compare-code-writer-ok / no-ref を強制委譲と定義する。
- `plugin/skills/code-writer/SKILL.md` step 1 は小仕事なら無条件に親生成を指示し、A群の例外や明示委譲の優先順位を表現していない。実際に展開された本文も同じ。`suite: A` は評価データであり、`evals/compare/run.sh:425` 以降のプロンプト構築では親へ渡す強制委譲規約になっていない。「スキルを呼ぶ」は「workerを必ず起動する」と同義ではない。
- no-refではパス自体は指定済み。親はスキルの「Without a reference file path」を不存在にも適用した。子の `plugin/agents/code-writer.md` には unreadable reference 時の非Write契約があるが、子は起動していないため未検証。
- `plugin/skills/bulk-reader/SKILL.md` は範囲不明で予算超過なら委譲とする一方、descriptionはoversized Read/Bashのdenyまたは必要I/Oの超過を入口にする。短いGrep結果から回答できる課題について、Grep前にサイズ判定して委譲すべきことが発見用descriptionから明確ではない。
- `plugin/hooks/hooks.json` のPreToolUseはRead/Bashのみ。Grepを止めないのは設計にも記載された限界。reader 2件はRead deny後の迂回ではなく、denyが発生する前の直接経路である。
- §26.5 Bは同じ大容量fixtureで委譲必須とするが、§26.2は必要区間が既知なら直接を許す。「Grepで位置を知る前と後のどちらで経路を固定するか」が未整理。

## 再実行前の修正方針

1. A群の機構試験には、小仕事判定を適用せず指定workerを起動する指示を明示し、スキル側にも明示委譲とauto判定の優先順位を揃える。`--worker-model` はモデル選択であり、強制委譲の指定として流用しない。Bの小仕事は引き続き親で処理する。
2. 参照パス未指定と指定済みパス不存在を分ける。Aのno-refは子がRead失敗を処理して非Writeを返す契約試験として明示する。親で停止する製品方針を採るなら、そのケースとは分離する。
3. Bの経路方針を決める。現行の「範囲不明・大容量なら委譲」を維持する場合、編集・既知区間の例外を残しつつ、本文Grepより前にメタデータで経路を決めることを発見用descriptionと手順に明示する。短いGrep抽出を製品として許すなら、先に §26.2 / §26.5 とBの課題を改訂する。今回の失敗だけを判定緩和で通さない。
4. 上記の契約整備後、6件の限定実機確認で分岐を検証し、本文返却・Read回数など別契約の修正を含めてA/B全必須ケースを再実行する。今回は調査のみで再実行していない。

## 併せて確認した点と限界

- `auto-bulk-facts.direct.jsonl:23` は値のreturn行21を回答。fixtureは関数定義20行、return21行で、文字どおりの `MAGIC_TOKEN` 変数は存在しない。goldの20は関数定義行として正しいが、質問の「on which line?」は値の行とも読める。fixture/質問で求めるシンボルと関数定義行を明確にする必要がある。
- compare-code-writer-okは指定の `python` が見つからず、親が `python3` に切り替えて3テスト成功。これは委譲0回の原因とは別の実行環境不整合。
- auto-large-writerのhaiku/sonnet/auto、および50行writer境界のautoはsession limitで実処理に入っていない。このrunだけから「大きいcode-writerでも委譲不能」とは結論できない。
- スキル登録は各init、writerの本文展開は各Skill直後のuserイベントで確認。モデル内部の選択理由は推測せず、明示された発言とツール順序に基づく。子の本文返却・Read回数違反の詳細調査は今回の6件の範囲外。

## 追補: `child_reads_once` 違反の原因（委譲0回とは別系統）

委譲が成立した側の失敗も同じ run から切り分けた。子の複数 Read は指示違反ではなく、**ハーネスの Read 上限との衝突**である。

```
compare-bulk-facts.auto  child: Read(全体) → ERR "File content (47078 tokens) exceeds maximum allowed tokens (25000)"
                                → Read(175,344) → Read(400,119) → Read(350,50)
auto-bulk-facts.haiku    child: Read(全体) → 同 ERR → Read(176,343)/(470,49)/(250,100)/(350,120)
compare-hook-deny-route.auto, reader-bounds.auto, compare-bulk-facts.sonnet, auto-bulk-facts.sonnet も同型
```

- `plugin/agents/bulk-reader.md` は「Read each specified path at most once (3 Reads total maximum)」と規定するが、token-shunt が委譲対象とする閾値（MIN_BYTES 65536）を超えた単一ファイルは Read ツール自身が 25000 トークン上限で全体読取を拒否する。子は範囲分割するしかなく、契約を満たせない。
- 一方 `*-explicit-multifile` / `reader-batch-*` の 3×`Read(全体)` は 3 パス各1回であり違反ではない（判定器の集計単位の問題ではない）。
- 修正方針: (a) 子契約を「各パスを1回だけ読む」から「**各パスの各領域を1回だけ読む／重複範囲の再読を禁止**」に改め、全体読取が上限で拒否された場合の分割読取を明示的に許可する。(b) 判定器 `child_reads_once` を呼び出し回数ではなく**範囲の重複**で判定する。(c) 分割が maxTurns 4 を圧迫するため、分割が必要なサイズでは turn 予算の見直しが要る（現状 auto-bulk-facts.haiku は 5 Read で上限に当たっている）。
- これは製品側の真の欠陥であり、A群/B群の指示不整合とは独立に修正が必要。

## 実施した修正（2026-09-13）

ユーザー判断: no-ref は**子の拒否契約を検証する**、B群は**メタデータで経路を先に決める**。

| 対象 | 変更 |
|---|---|
| `plugin/agents/bulk-reader.md` | 契約を「各パス1回」→「**各領域1回**」。Read ツールが全文を拒否した場合のみ、親が渡した行数から連続・非重複に分割。`maxTurns: 4` → `6` |
| `plugin/skills/bulk-reader/SKILL.md` | 委譲プロンプトに `wc -lc` のサイズ・行数を含める。step 1 に「**本文検索より前に経路を決める**」を追加（超過既知のファイルへの content Grep は位置特定・既知範囲確認に限定）。description も同旨に更新 |
| `plugin/skills/code-writer/SKILL.md` | step 1 の小仕事判定に優先する2条件を明記。(a) 明示的な委譲指示、(b) **指定されたが読めない参照**は親で停止せず委譲し、子の非Write契約を働かせる |
| `evals/compare/cases.json` | A群4ケースの prompt に機構試験の強制委譲文を追加。no-ref は「参照の存在を親で判断しない」を明示。`Three delegated generations` → `Four` |
| `evals/compare/routing_checks.py` | `child_reads_once` を呼び出し回数から**範囲重複**判定へ。失敗した Read は被覆にも重複にも数えない。起動あたり Read 上限 3 → 6 |
| `evals/compare/test_routing_checks.py` | `SplitReadTests` 5件を追加（分割許可／重複拒否／開区間／失敗のみは非被覆／予算上限） |
| 設計書 §1・§11・§12・§13・§15・§26 | maxTurns と領域単位契約、経路判定の順序、参照不存在の扱いを同じ正本に反映。実機で判明した Read ツール上限との衝突を注記 |
| `README.md` | ワーカー設定 6 turn、分割読取、Grep 本文出力の穴を制限事項に追記 |

オフライン eval `evals/run.sh` 110 pass / 0 fail、`evals/compare` の unit 78 pass。実機再実行は未実施。
