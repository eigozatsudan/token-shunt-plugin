# reader プロトコル往復削減の実機比較（2026-09-14）

**訂正 (fix round 1):** 当初の Step 4 判定スクリプト（ブリーフに書かれていたもの）は
`gold_file` の有無だけで対象ケースを選んでおり、`expect.delegate.gold_confirmed` を
見ていなかった。このため `gold_confirmed` 契約が課されていない2ケース
（`auto-bulk-facts`、`auto-one-line`）にだけ誤ってチェックを適用し、実際に契約が
課されている唯一のケース `auto-explicit-multifile`（gold をインライン宣言、
`gold_file` 無し）を黙って対象外にしていた。最初の版はこの取り違えに気づかず、
「`missing_gold` は測定アーティファクト」と全ケース一律に結論づけていたが、これは
誤って適用した2ケースについてのみ正しい。訂正版は「gold_confirmed の内訳（訂正版）」
節と「確認できたこと / まだ未確認のこと」節にある。新規の実機実行は行っていない
（保存済み transcript の再判定のみ）。ゲート判定（`repeat.sh 3` に進まない）自体は
Skill 読み込み基準で既に不成立だったため変わらない。

## 条件

- ブランチ: `fix/design-impl-gaps-2026-09-13`、計測時 HEAD `1327bd3`
  （Task 2〜8 反映済み: `reader-call-contract` 0f99da5、`check-file-size` f9c2587、
  `check-bash-read` 2c99098、byte-budget/scan-failure テンプレ化 dd9b8e8、
  `bulk-reader/SKILL.md` 圧縮 9106001、design doc 更新 182a843、
  `cost_probe.py` の `skill_loads`/`deny_count`/`deny_bytes`/`hooklog` 追加
  328c897・1327bd3）。
- fixtures: `evals/compare/tmp/runs/run.th6y8F8y/work/fixtures`（既存の直近実行から複製、
  Step 1 で新規生成不要と確認済み）。
- 実行コマンド:

  ```
  python3 evals/compare/cost_probe.py 3 auto-bulk-facts auto-explicit-multifile auto-one-line
  ```

  出力: `evals/compare/tmp/cost-probe-postfix.log`、
  証跡: `evals/compare/tmp/cost-probe/20260914-204044/report.json`
  （`transcripts/` に 27 本の stream-json transcript と `.hooklog`）。
- ケース: `auto-bulk-facts`、`auto-explicit-multifile`、`auto-one-line`（reader 3ケース）。
  `auto-large-writer`（writer）は設計 §2 の対象外につき実行していない。
- 条件×回数: `direct` / `bare` / `skill` の3条件 × 3ケース × 3周 = 27実行。
  親モデルは全条件 sonnet、ワーカーモデルは `skill`/`bare` とも `haiku` 固定
  （`cost_probe.py` の `WM = "haiku"`）。
- 除外した実行: **なし**。27実行すべて `cli_exit=0` かつ `ok=True`。`hooklog` は
  `direct` の9実行が `not_applicable`（プラグイン非搭載のため未計測は想定どおり）、
  `bare`/`skill` 計18実行はすべて `hooklog="ok"`（計測できたログのみ集計、
  除外0件）。

## 結果

各周の生データ（`report.json` より、`cost_usd` は USD、`turns` は親ターン数）:

| ケース | 条件 | rep1 cost | rep2 cost | rep3 cost | 親ターン (rep1/2/3) | skill_loads | deny_count | deny_bytes |
|---|---|---|---|---|---|---|---|---|
| auto-bulk-facts | direct | 0.1364 | 0.1307 | 0.1134 | 5/6/4 | 0/0/0 | n/a | n/a |
| auto-bulk-facts | bare | 0.0778 | 0.0900 | 0.0866 | 3/4/4 | 0/0/0 | 0/0/0 | 0/0/0 |
| auto-bulk-facts | skill | 0.0985 | 0.1006 | 0.0975 | 6/6/7 | 0/0/0 | 1/1/1 | 1112/1112/1112 |
| auto-explicit-multifile | direct | 0.1132 | 0.1132 | 0.1132 | 5/5/5 | 0/0/0 | n/a | n/a |
| auto-explicit-multifile | bare | 0.0678 | 0.0772 | 0.0692 | 3/4/3 | 0/0/0 | 0/0/0 | 0/0/0 |
| auto-explicit-multifile | skill | 0.1314 | 0.0879 | 0.0898 | 10/4/4 | **1**/0/0 | 0/0/0 | 0/0/0 |
| auto-one-line | direct | 0.1747 | 0.1752 | 0.1752 | 3/3/3 | 0/0/0 | n/a | n/a |
| auto-one-line | bare | 0.1030 | 0.2660 | 0.5946 | 4/4/4 | 0/0/0 | 0/0/0 | 0/0/0 |
| auto-one-line | skill | 0.1201 | 0.1198 | 0.1098 | 6/7/6 | 0/0/0 | 1/1/1 | 1124/1124/1124 |

反復ごとの対応差（`skill − direct`、対象2ケース `auto-bulk-facts` + `auto-explicit-multifile` の
条件別合計、`evals/compare/cost_probe.py` の Step 3 集計スクリプトをそのまま実行した出力）:

```
rep1 direct=0.2496 bare=0.1457 skill=0.2298  skill-direct=-0.0198
rep2 direct=0.2439 bare=0.1673 skill=0.1885  skill-direct=-0.0554
rep3 direct=0.2266 bare=0.1559 skill=0.1873  skill-direct=-0.0393
complete reps: 3/3
median(skill-direct) = -0.0393
```

`auto-one-line`（別掲、合計に混ぜない）:

```
auto-one-line    direct n=3 vals=[0.1747, 0.1752, 0.1752]
auto-one-line    bare   n=3 vals=[0.103, 0.266, 0.5946]
auto-one-line    skill  n=3 vals=[0.1201, 0.1198, 0.1098]
```

| 指標 | 変更前 | 今回（中央値） | 各回 | 目標 | 判定 |
|---|---|---|---|---|---|
| 親ターン（読み取りケース、`skill`、対象2ケース平均） | skill 10.5〜11.5 | 6.5 | rep1: (6+10)/2=8.0, rep2: (6+4)/2=5.0, rep3: (7+4)/2=5.5 | 5前後（目標値） | **○**（平均6.5、目標近傍。rep1のみ8.0で目標超過、後述の異常実行が原因） |
| Skill 読み込みターン | 毎回1回 | 9回中1回 | rep1: auto-explicit-multifile skill で `Skill` ツール使用1回、他8回は0回 | 0回（初回定型・正常終了ケース限定） | **×** |
| コスト（読み取り2ケース計、各周の対応差 skill−direct） | skill $0.2986 / direct $0.2492 | 中央値 **-0.0393**（skill優位） | rep1 -0.0198／rep2 -0.0554／rep3 -0.0393 | 差の中央値がマイナス、かつ3周すべて成立 | **○** |
| コスト（`auto-one-line`、別掲） | skill ×2.98 | skill $0.1201/$0.1198/$0.1098、direct 一定 $0.175 前後、bare が $0.10〜$0.59 と不安定 | 上記 `vals=` 参照 | 参考値（合計に混ぜない） | 参考（今回は skill が direct より安い。bare の分散が著しい） |
| gold_confirmed（パス省略、`expect.delegate.gold_confirmed: true` のケースのみ適用） | 3周で15件 | **`auto-explicit-multifile` の `bare`/`skill` 計6実行中6実行（3周とも）で `gold_confirmed_ok` が3件（`Notifiable`/`after_create`/`WelcomeEmailJob`）すべて欠落と判定** | 下記「gold_confirmed の内訳（訂正版）」参照 | 0件 | **×**（実測の失敗。原因は後述、Task 2〜8 由来かは未確定） |
| モデル指定違反（reader 経路） | 3周で各11件 | **0件**（27実行すべて `requested` は `haiku` か空リスト、`unspecified_or_auto_model`/`first_call_not_haiku`/`sonnet_without_a_prior_attempt` いずれも検出なし） | `judge.agent_resolved_models` の resolved 値はすべて `claude-haiku-4-5-20251001` | 0件 | **○** |
| deny 回数 / 注入バイト数 | 未計測 | `bare`: 全18実行中9(bare分)は deny=0/0B。`skill`: `auto-bulk-facts` 全周 deny=1/1112B、`auto-explicit-multifile` 全周 deny=0/0B、`auto-one-line` 全周 deny=1/1124B。`hooklog="ok"` の18実行すべてで計測できた（除外0件） | 上表参照 | 記録して削減幅と突き合わせ | **○**（計測完了、除外なし） |

### gold_confirmed の内訳（訂正版）

**最初に提出した版の訂正について。** ブリーフ Step 4 のスクリプト（このタスクの
著者が書いたもの、私が書いたものではない）は `case.get('gold_file')` だけで
gold集合を組み立て、`case['gold']`（インライン宣言の gold）と
`expect.delegate.gold_confirmed` を一切見ていなかった。その結果、実際には
`gold_confirmed` 契約が課されていない2ケース（`auto-bulk-facts`、`auto-one-line`。
どちらも `gold_file` はあるが `expect.delegate.gold_confirmed` は未設定）にだけ
`gold_confirmed_ok` を適用し、契約が課されている唯一のケース
（`auto-explicit-multifile`。`gold_file` は無く、gold をインライン
`gold: ["Notifiable","after_create","WelcomeEmailJob"]` で宣言し、
`expect.delegate.gold_confirmed: true`）を `gold_file` が無いという理由で
黙って対象外にしていた。最初の版はこれに気づかず、全ケース一律「`confirmed:`
形式を要求しない測定アーティファクト」と結論づけていたが、これは
**チェック対象外だった2ケースについてのみ正しく、本来チェックすべきだった
`auto-explicit-multifile` の結果を隠してしまっていた。**

`evals/compare/run.sh` の spec 組み立て（run.sh:536-548 付近: `gold_file` が
あればその内容を `spec.gold` に追加、無ければインラインの `gold` をそのまま使う）
と `judge.py` の適用条件（`judge.py:1188`: `exp.get("gold_confirmed") and gold and
not unsupported` の場合のみ `gold_confirmed_ok` を呼ぶ。`exp` は
`spec["expect"].get(mode, spec["expect"].get("delegate", {}))`）を再現して、
保存済みの transcript（新規実行なし、`evals/compare/tmp/cost-probe/20260914-204044/`
の既存 transcript のみ）を再判定した。

- `auto-bulk-facts`・`auto-one-line`: `gold_file` はあるが
  `expect.delegate.gold_confirmed` は未設定 → `gold_confirmed_ok` は
  **適用対象外**（`judge.py` 自身もこの2ケースにはこのチェックを課さない）。
  よって最初の版が報告した「missing_gold 27実行中18実行」という数字は、
  そもそも判定器が要求していないチェックを誤って全実行に適用した結果であり、
  無効な測定である。
- `auto-explicit-multifile`: `gold_file` は無く `gold` をインライン宣言、
  `expect.delegate.gold_confirmed: true` → `direct` 以外の全実行が適用対象。
  結果は **`bare` 3周・`skill` 3周、計6実行すべてで `gold_confirmed_ok` が
  3件（`Notifiable`/`after_create`/`WelcomeEmailJob`）すべて欠落と判定
  （3/3 失敗、`bare`/`skill` とも）**。`direct` はこのチェックの対象外
  （`exp` が `expect.direct` にフォールバックし `gold_confirmed` を持たない）
  なので判定していない。

`skill` 条件3周の親最終回答（`judge.Transcript(...).final_text()`）を実際に
確認すると、いずれも事実としては正確（`Notifiable` concern、`after_create`
コールバック、`WelcomeEmailJob` の enqueue を正しく説明している）だが、
すべて散文の段落・箇条書きであり、`confirmed: <絶対パス> — <事実>` という
`judge.confirmed_items()` が要求する構造化形式を一度も使っていない
（例 rep2: `"**Concern:** Notifiable — **Job:** WelcomeEmailJob"` のような
太字強調はあるが `confirmed:` プレフィックスは無い）。`bare` 条件も同様。
これは実際に測定された失敗であり、確認できたことの1つとして扱う。

#### 変更前ベースラインによる決着（2026-09-14 追記）

前版ではこの失敗が Task 2〜8 由来の退行か既存の欠落かを未決としていた。
指定した次の一手をそのまま実行して決着した。**結論: 退行ではなく、
Task 2〜8 以前から存在した既存の欠落である。**

計測方法。`plugin/` を `1ad21b0`（`reader-call-contract` 導入コミット
`0f99da5` の直前）の状態に戻したツリーを作り、`--plugin-dir` だけをそれに
差し替えて `auto-explicit-multifile` を `bare`/`skill` × 3周＝6実行した。
fixtures は今回と同一のツリー
（`evals/compare/tmp/cost-probe/20260914-204044/fixtures`）をコピーして使用し、
プロンプト・親モデル（sonnet）・ワーカーモデル（haiku）は
`cost_probe.prompt_for` をそのまま import して生成したので差は無い。
Tasks 2〜8 に無関係な未コミット編集（`check-jq`、`check-reader-contract`、
code-writer 系）は元のプローブ実行時と同じ状態で保持し、
差分が Tasks 2〜8 の変更だけになるようにした。
判定は訂正版チェック（インライン `gold` + `gold_file` をマージし、
`expect.<mode>.gold_confirmed` が立つケースだけに適用）を
`judge.py` 本体に渡して行った（チェックを自作し直していない）。
成果物は `evals/compare/tmp/cost-probe-baseline/20260914-214327/`。

結果（6実行、CLI 終了コード0・`ok=True`、合計 $0.6797）:

| 条件 | 変更前 `gold_confirmed` | 変更後 `gold_confirmed` |
|---|---|---|
| `bare` 3周 | 3/3 失敗 | 3/3 失敗 |
| `skill` 3周 | 3/3 失敗 | 3/3 失敗 |

失敗理由も両者で同一（`gold not in confirmed: + matching path:
Notifiable, after_create, WelcomeEmailJob`）。よって
**`missing_gold` は本プランの変更とは独立した既存のギャップ**であり、
deny へ契約を載せた変更が壊したものではない。

#### 付随して見えた差（結論は変えない）

親最終回答に `confirmed:` 形式の項目が出た実行数を数えると:

| 条件 | 変更前 | 変更後 |
|---|---|---|
| `bare` | 0/3 周 | 0/3 周 |
| `skill` | 2/3 周（rep1=4項目, rep3=4項目） | 0/3 周 |

ただし**絶対パスを伴う `confirmed:` 項目は、変更前後あわせて12実行すべてで
0件**だった。変更前の `skill` が出した `confirmed:` 項目も引用元が
`user.rb` / `notifiable.rb` という相対ファイル名で、
`gold_confirmed_ok` が要求する絶対パス引用を満たしていない。
したがってこの差は判定結果を一切動かしておらず、
「変更前なら通っていた」ことを意味しない。
各条件3周ずつの小標本でもあるため、**観察であって知見ではない**。
形式保持そのものを問題にするなら、`confirmed:` 形式の出現率を
主目的にした別プローブが要る。

`routing_checks.has_confirmed_claim` は今回使わなかった。この関数は
「`confirmed:` 行に実質的な主張が一切無いこと」を検証する専用のヘルパーで
（`unreadable_line_partial` が「読めなかった行について `unconfirmed:` だけを
報告し、`confirmed:` に実質的な主張が無いこと」を確認するために使う否定的な
チェック）、gold の引用元パスを `confirmed:` 項目から抽出して照合する今回の
用途とは目的が逆であり、かつ `auto-explicit-multifile` は
`allow_unreadable_line_partial` を宣言していないため `unreadable_line_partial`
の対象でもない。gold 照合には `judge.confirmed_items()` /
`judge.gold_confirmed_ok()` が正しいヘルパーであり、これを使った。

### モデル解決の3形状の確認

- **初回 haiku**: 18実行（`bare`+`skill`）すべてで `requested=['haiku']`、
  `judge.agent_resolved_models` の解決結果は全て `['claude-haiku-4-5-20251001']`。
- **未指定 / `auto`**: 27実行中どの `Agent`/`Task` 呼び出しにも `model` が
  `None`/`''`/`'auto'` のものは無かった（`unspecified_or_auto_model` 検出0件）。
  ただし本プローブは `--worker-model haiku` 固定で回しており、`direct` 条件では
  そもそも `Agent` を呼ばない。「未指定/`auto` が来たら haiku に解決される」という
  経路自体を積極的に踏んだわけではなく、「今回の設定では未指定/`auto` が一度も
  送られなかった」ことのみを確認できた。
- **再試行 sonnet**: 本プローブは固定モデルで1回だけ `Agent` を呼ぶ設計であり、
  リトライ（2回目呼び出し）は27実行中一度も発生しなかった。`sonnet_without_a_prior_attempt`
  検出も0件だが、これは「違反が無かった」のではなく「再試行シナリオ自体が
  このプローブでは踏まれていない」ことを意味する。

### 異常実行の詳細: `auto-explicit-multifile` skill rep1 の Skill 読み込み

`auto-explicit-multifile.skill.1.jsonl` を確認すると、親エージェントは
まず `Skill` ツール（`token-shunt:bulk-reader --worker-model haiku <3paths>`）を
直接呼び出し、続けて `wc -c` でサイズ確認、`plugin/hooks/reader-call-contract`
の直接 Read、最後に `Agent`（`model=haiku`）呼び出し、という経路を辿った
（親ターン10、他の同条件実行は4〜7）。他の8実行（同ケース2回、
`auto-bulk-facts` 3回、`auto-one-line` 3回）はいずれも `Skill` ツールを
使わずに直接 `Agent` を呼んでいる。deny によるプロトコル埋め込みが機能しない
初回ターンでモデルが自発的に `Skill` を叩くケースが、9回中1回発生した。

## writer 経路（対象外）

`auto-large-writer` は今回回していない。設計 §2 の範囲外として最初から除外。
参考として `reviews/cost-structure-2026-09-14.md`（18:04 実行、Task 2〜8 反映前）の
数値のみ既存記録として存在するが、本変更の評価には含めない。

## 確認できたこと / まだ未確認のこと

**確認できたこと**

- 27実行すべて完了（`cli_exit=0`、`ok=True`）。3周とも欠測なし。
- 読み取り2ケース合計のコスト差（skill − direct）は3周とも負値で、中央値
  `-0.0393`（skill が direct よりも安い）。
- `deny_count`/`deny_bytes` は `hooklog="ok"` の18実行すべてで計測でき、
  未計測扱いの実行は0件。`skill` 条件では `auto-bulk-facts`/`auto-one-line` で
  毎回1回・1112〜1124バイトの deny（＝契約テンプレート注入）が発生し、
  `auto-explicit-multifile` では deny が発生しない周が多かった。
- reader 経路のモデル指定違反（未指定・`auto`・初回 sonnet）は0件。
- 親ターン数は `skill` 条件平均6.5で、変更前の10.5〜11.5から明確に減少した
  （ただし後述の異常実行1件を除くと平均はさらに小さい）。

**まだ未確認のこと**

- **Skill 読み込み0回の headline claim が成立していない**: 9回の `skill` 実行中
  1回（`auto-explicit-multifile` rep1）で親が `Skill` ツールを直接使用した。
  これは deny によるプロトコル埋め込みが「毎回確実に」初回ターンでの
  Skill 読み込みを防ぐわけではないことを示す。モデルの非決定性による
  ばらつきか、`auto-explicit-multifile` のプロンプト（4ファイル境界確認を伴う
  ケースと異なり単純な3ファイル明示ケース）固有の何かが原因かは今回の
  データだけでは切り分けられない。
- `auto-bulk-facts`・`auto-one-line` の `missing_gold`（最初の版が報告した
  18実行分）は `expect.delegate.gold_confirmed` が未設定のケースに誤って
  チェックを適用した結果であり、無効な測定だったと訂正した。この2ケースに
  ついては「`cost_probe.py` のプロンプトが `confirmed:` フォーマットを要求
  していないため、そもそも判定器もこの契約を課していない」という説明で
  正しい（上記「gold_confirmed の内訳（訂正版）」参照）。
- **`auto-explicit-multifile`（`gold_confirmed: true` が実際に課されている
  唯一のケース）は `bare`/`skill` 計6実行すべてで実際に失敗した。**
  **これは Task 2〜8 による退行ではなく、変更前から存在した既存の欠落である。**
  `plugin/` を `1ad21b0`（変更前）に戻して同じ fixtures・同じプロンプトで
  `bare`/`skill` × 3周を回し、同じ訂正版チェックを適用したところ、
  6実行すべてが同じ理由で失敗した（上記「変更前ベースラインによる決着」）。
  失敗の構造は、親が子の `confirmed:` 契約付き回答を受け取った後、
  自分の最終回答では引用元を絶対パスで書かない（変更前後12実行で
  絶対パス付き `confirmed:` 項目は0件）というもの。
- 「未指定/`auto` → haiku に解決される」経路と「sonnet は再試行時のみ」の経路は、
  今回のプローブ設定（`--worker-model haiku` 固定・単発呼び出し）では
  一度も実際に踏まれておらず、「違反が0件だった」以上のことは言えない。

## 全体再評価に進むか

**進まない。**

設計 §8.3 のゲート条件を1つずつ照合する:

1. 3周すべてが成立（欠測なし）: **満たす**（27/27 実行が `ok=True`、`hooklog` 未計測もなし）。
2. 読み取り2ケース合計の各周差（skill−direct）中央値がマイナス: **満たす**
   （`-0.0393`、3周とも負値）。
3. `missing_gold` 0件かつ reader 経路のモデル指定違反0件: **満たさない**。
   モデル指定違反は0件で満たす。`missing_gold` は、`expect.delegate.gold_confirmed`
   が実際に課されている唯一のケース `auto-explicit-multifile` で
   `bare`/`skill` 計6実行すべて（3周とも）が失敗しており、非0。
   （`auto-bulk-facts`・`auto-one-line` にはこのチェックはそもそも適用されない
   ため対象外。訂正前の版はこの2ケースに誤って適用し、本来チェックすべき
   `auto-explicit-multifile` を見落としていた。）変更前ベースラインとの比較で
   この失敗は Task 2〜8 由来の退行ではなく既存の欠落と判明したが、
   ゲート条件の文言（`missing_gold` 0件）は既存の欠落であっても満たさない。
4. 初回の定型・正常終了ケースで Skill 読み込み0回: **満たさない**。
   `skill` 条件9実行中1実行（`auto-explicit-multifile` rep1）で `Skill` ツールが
   使用された。
5. deny 回数と注入バイト数が `hooklog="ok"` の実行で計測できている（除外なし）:
   **満たす**（18/18 実行が `hooklog="ok"`、除外0件）。

5項目中3項目は満たすが、**項目3と項目4を満たさない**ため、`repeat.sh 3` には
進まない。項目4（Skill 読み込み0回）は本タスクの最重要主張（headline claim）
そのものであり、単発の逸脱とはいえ実機で観測された以上、無視して先へ進む
べきではない。項目3は測定手法起因の可能性が高いとはいえ、機械判定の文言上は
非0であり、同じ理由で保留する。

### 次に調べること

- `auto-explicit-multifile` の `skill` 条件を追加で数回（例: 5〜10回）回し、
  `Skill` ツール直接使用の頻度を確認する。単発の非決定的ばらつき（モデルが
  たまたま `Skill` を選んだ）なのか、このケース固有のプロンプト構造
  （4パス境界確認ケースと異なる単純な3パス明示だが、他の2ケースより
  ファイルサイズが大きい `user.rb` を含む点など）に起因するのかを切り分ける。
- deny によるプロトコル埋め込み（`reader-call-contract`）が「初回ターンで
  Skill を読む前に十分な情報を親に見せられているか」を、`auto-explicit-multifile`
  で `Skill` が使われた回の transcript（`plugin/hooks/reader-call-contract` を
  親が直接 Read している）と突き合わせて確認する。親がなぜ deny 経由の
  埋め込みテンプレートより先に `Skill` ツールや hooks ファイルを直接読みに
  行ったのか、プロンプトの誘導が不足していないかを調べる。
- ~~`auto-explicit-multifile` の `gold_confirmed` 失敗が Task 2〜8 由来の
  退行か既存の欠落かを切り分ける。~~ **完了（上記「変更前ベースラインによる
  決着」）: 既存の欠落と判明。**
- 親が `confirmed:` 項目を出すとき引用元を相対ファイル名で書く
  （絶対パスを伴う項目が12実行で0件）という、より根の深い問題を調べる。
  `gold_confirmed_ok` は同一項目内の絶対パス引用を要求するので、
  形式を出せても相対パスのままでは通らない。子の実行契約が
  「絶対パスを省略せずに」と指示している経路で、親が要約時に
  相対名へ落としているのか、子の時点で既に相対なのかを
  transcript の子発話まで遡って切り分ける。
- `cost_probe.py` のスクリプト自体を、run.sh と同じ spec 組み立て
  （`gold_file` とインライン `gold` の両方をマージし、
  `expect.delegate.gold_confirmed` を見て適用要否を判定する）に修正し、
  今後同じ取り違えが起きないようにする。
- `auto-explicit-multifile` に限らず、親が子エージェントの `confirmed:`
  形式の回答を要約する際に構造化フォーマットを保持できていない（今回は
  3/3 とも散文化していた）ことが、他の `gold_confirmed: true` ケース
  （`evals/compare/cases.json` の他のケースや `evals/run.sh` の実行）でも
  再現するか確認する。
- 上記を解消し、必要なら追加の実機周を回したうえで、ゲート条件5項目が
  すべて満たされることを確認してから `repeat.sh 3` の判断を再度行う。
