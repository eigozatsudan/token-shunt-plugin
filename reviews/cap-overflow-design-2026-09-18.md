# worker の上限超過を、契約文だけで直せるか（事前登録、2026-09-18）

`reviews/child-msg-cap-2026-09-18.md` §5 が「次にやるなら」と書いた測定である。
**製品を直す側の測定であって、routing 4 ブロックの続きではない。**

## 0. 予算（先に書く）

上限 $200 に対し累計 **約 $172.0**。**残り 約 $28.0。**

**本ブロックの枠 $19.50（$9.75 × 2 腕）、reserve $0.75 / 腕、見込み $12〜15。**
**当初 $20。§7.1 の逸脱で $0.50 下げた。**
`drive.sh --cap 9.75 --reserve 0.75` を腕ごとに掛けて止める。
**これで残高はほぼ尽きる。上限を超える予定は無い。**

## 1. 直そうとしているもの

閾値下 regime で **22/77 = 0.286**、worker の返答が
契約の 4,000 字上限を超えている（Wilson [0.197, 0.395]）。

**漏れではない。** `child_no_body` は通り、accuracy も落ちていない。
**列挙が長いだけである。**

### 1.1 契約には、超えそうなときの逃げ道が無い

`plugin/agents/bulk-reader.md` は既に次を書いている。

- 「**4000 characters maximum per invocation**（the cap does not grow with path count）」
- 「Reserve room for them before writing facts」
- 「without an introduction or a second prose summary」

**それでも超える。**
実際、最長の 1 件（10,642 字）は**禁じられている前置きから始まっている**
（"Now I'll read each file to completion and extract all method/function
definitions..."）。

**契約が定義していないのは「全部書くと入りきらないとき何をするか」である。**
`partial` は**読めない範囲や未解決依存**のために定義されていて、
**分量超過のための `partial` は無い。**
課題が「各段の関数名と絶対パスを挙げよ」と言い、段が 40 ある場合、
**worker には合法な選択肢が存在しない。**

## 2. 介入 — 契約文に 1 つ規則を足すだけ

`plugin/agents/bulk-reader.md` に、分量超過の逃げ道を 1 つ追加する。
**それ以外は 1 バイトも変えない。**

- 上限を超えるくらいなら**切る**
- 切ったら `status: partial`、`stop_reason: cap_reached`
- 落とした分は `unconfirmed:` で名前だけ挙げる

**短くするために既存の文を削らない。**
（`reviews/` に「7000 B に収めるための短縮が規則を反転させた」という
前例があるため。足すだけにする。）

## 3. 設計

| | control | treated |
|---|---|---|
| plugin | 現行 HEAD | HEAD + §2 の 1 規則 |
| case | `django-subthreshold-bare` | 同一 |
| mode | `auto` | `auto` |
| ターン | turn 1 のみ | 同一 |

**case も prompt も corpus も変えない。** 変わるのは
`plugin/agents/bulk-reader.md` **1 ファイルだけ**である。
**preflight でその diff が 1 ファイルであることを機械的に確認する**（§8-3）。

turn 1 だけにする理由: 超過 5 件は**全て turn 1** であり、
multiturn の turn 5 は 5 件中 0 件だった。**多ターンは要らない。**

### 3.1 腕は worktree、順序は交互

2 つの worktree を **5 run ずつ交互**に回す
（control 5 → treated 5 → control 5 → …、計 16 チャンク）。
**片腕を全部回してからもう片腕、はやらない。**
時刻やサービス側の揺れが腕と相関しないようにするためである。

**対にはならない。** 同一 run ディレクトリ内の 2 腕ではないので、
**検定は対応の無い 2 標本**である（§4）。

## 4. 主要指標

**`child_msg_cap` が落ちた run の割合。** 判定は `judge.py` に任せる
（新しい採点器は書かない）。

- 検定 = **Fisher 正確検定（両側）**
- **n = 40 / 腕**（計 80 run）
- 帰無仮説: 2 腕の超過率は等しい

### 4.1 検出力

control を 0.286（22/77）と置いた模擬（`Random(20260918)`、3,000 反復）:

| treated の率 | n=30/腕 | n=40/腕 |
|---|---|---|
| 0.02 | 0.77 | **0.92** |
| 0.05 | 0.56 | **0.78** |
| 0.10 | 0.33 | **0.48** |
| 0.15 | 0.16 | 0.23 |
| 0.20 | 0.07 | 0.10 |

**「ほぼ直った」なら見える。「半分になった」は見えない。**
**0.10 以上に留まった場合、本ブロックでは決まらない。先に書いておく。**

## 5. 副次（すべて事前に決める）

1. **返答の長さの分布。** 腕ごとに中央値・最大・4,000 超の件数。
   **率が動かなくても長さが動いたなら、それはそれで書く。**
2. **`status: partial` の率。** 介入が効いているなら上がるはずである。
   **上がらずに超過だけ減ったなら、規則以外の何かが効いている。**
3. **accuracy。** `gold` 3 語が揃うか。**これが本ブロックの要である**（§6-1）。
4. **`parent_no_read`。** A・B・multiturn と合算して累計を出す。
5. **他の判定項目**（`child_no_body`, `child_reads_once`,
   `single_invocation`, `agent_type`, `agent_calls`, `child_status`）。
   **どれも control より悪化していないことを確認する。**
   悪化していたら §6-2 の通りに書く。

## 6. 予測を外したときにどう書くか（事前に決める）

1. **超過率は下がったが accuracy も下がった**場合:
   **改善ではない。** §0 にそう書く。
   「上限を守らせたら答えが痩せた」は**この介入の失敗**であって、
   上限の側を見直す材料である。**都合よく主要指標だけ報告しない。**
2. **超過率は下がったが他の判定が悪化した**場合:
   同じく改善ではない。**悪化した項目名を §0 に書く。**
3. **何も動かなかった**場合:
   **契約文では直らない**と書く。
   その場合、次は runtime 側（送り返し）の話になるが、
   **本ブロックはそこまで言わない。**
4. **control の率が 0.286 から大きく外れた**場合:
   §1 の前提（22/77）が別ブロックの寄せ集めであることが効いている。
   **その場合、本ブロックの control を唯一の control として読み直す。**

## 7. 打ち切り

1. `spend.py --cap 20 --reserve 1.50`。**exit 3 で止める。**
2. 各腕 40 run に達したら止める。
3. **腕ごとの run 数が揃わないまま打ち切られた**場合、
   **揃っているところまで**で Fisher を引き、**両腕の n を必ず併記する。**
   切り捨てて揃えない（捨てるほうが情報を失う）。
4. `errors` が空でない run は解析から除き、**除外数を報告する。**

## 7.1 逸脱 — 1 回目の起動は再起動で消えた（2026-09-19）

**1 回目は `/tmp` に worktree と run ディレクトリを置いて起動し、
マシンの再起動で全部消えた。** 2 本の worktree、run ディレクトリ、
ログ、交互実行のスクリプト、すべて残っていない。

- **走ったのは control 1 run まで**（消える直前の確認で control 1 / treated 0）。
- **その run の実費は分からない。** transcript が無いので数えられない。
  **$0.2 前後と見込まれるが、これは推定であって測定ではない。**
- **対処**: 枠を $20 から **$19.50** に下げる（$9.75 × 2 腕）。
  失った分を上限で吸収する。
- **再発防止**: worktree・run ディレクトリ・ログ・スクリプトを
  **すべて `/tmp` の外**（`~/wt/`, `~/measurements/token-shunt/`）に置いた。
- **preflight は張り直した。** `bc833e8`、両 worktree とも 3 件 deny 無し、
  `plugin/` 以下の diff は 1 ファイル、selftest 両方 pass。

**消えた 1 run は解析に入らない。** 新しい run ディレクトリは空から始まる。

## 8. 事前に認めている弱点

1. **対応が無い。** 同一 run ディレクトリの 2 腕ではないので、
   run ごとの揺れは誤差に入る。交互実行はそれを**相関させない**だけで、
   **消しはしない。**
2. **n=40/腕では「部分的な改善」は見えない**（§4.1）。
3. **1 つの case、1 つの prompt でしか測っていない。**
   「絶対パス付きの列挙」という、**上限に最も厳しい形**である。
   他の形の課題で同じ効果が出るかは分からない。
4. **契約文の書き方は 1 通りしか試さない。** 効かなかったとしても、
   **「契約文では直らない」の証拠としては 1 通り分しかない。**
5. **`--allowedTools` は工具を制限しない**という既知の性質はそのまま。
   変数を増やさないため `--disallowedTools` は足さない。

## 9. 残すもの

- `reviews/data/cap-overflow-2026-09-18.csv` — run ごと（腕・判定・返答長）
- `reviews/data/cap-overflow-2026-09-18-meta.tar.gz`
- `~/measurements/token-shunt/cap-overflow-2026-09-18-transcripts.tar.gz`
  （Django 本文を運ぶので repo の外。sha256 を記録する。）

## 10. preflight（走らせる前に $0 で）

1. **契約変更はテストを先に書く。** RED を確認してから
   `plugin/agents/bulk-reader.md` を編集する。
   その中で `evals/compare` 全件・外側 `evals` 全件・`evals/run.sh` 全件 pass、
   `judge.py --selftest` 全項目 pass。**両方の worktree で走らせる。**
   **実施済み。** treated（`362ef72`）で
   `evals/compare` 717 OK / 外側 `evals` 320 OK（skip 3）/
   `evals/run.sh` 240 pass 0 fail / selftest 全項目 pass。
   control（`3256947`）で `evals/compare` 717 OK / selftest 全項目 pass。
2. **既存の文を削っていないこと**を機械的に確認する
   （変更前の全行が変更後にも存在する）。
   **確認した。削除 0 行、6,653 → 7,025 B。**
3. **2 つの worktree の diff が `plugin/agents/bulk-reader.md` 1 ファイル**
   であることを `git diff --name-only` で確認する。
   **逸脱（走らせる前に記録）: diff は 2 ファイルである。**
   `plugin/agents/bulk-reader.md` と `evals/test_reader_call_contract.py`。
   契約変更をテスト先行でやると決めている以上、テストは変更と同じ commit に
   載る。**`plugin/` 以下の diff はちょうど 1 ファイル**であり、
   テストファイルは runtime に読み込まれないので測定には入らない。
   **設計の文言のほうが実際より厳しかった。そう書いておく。**
4. `DJANGO_ROOT` が `bc833e8`、3 パスが解決し `check-file-size` が deny しない
   ことを**両方の worktree で**引き直す。
   **引き直した。`bc833e8`、両 worktree とも 3 件すべて空出力・exit 0。**
5. **選択 jq を再現**し、planned が各 worktree でちょうど 1 スロット
   （`django-subthreshold-bare/auto`）、`unknown_slots` 空であることを確認する。
   **確認した。両 worktree とも planned は
   `django-subthreshold-bare/auto` 1 件、`unknown_slots` 空。**
6. **機構確認は 3 点だけ**: `errors` が空 / 実費が枠内 /
   verdict が両腕とも出ている。
   **どれも、どちらの腕が勝ったかを見ずに決まる。**
   **超過率も返答長も run 中に見ない。**
