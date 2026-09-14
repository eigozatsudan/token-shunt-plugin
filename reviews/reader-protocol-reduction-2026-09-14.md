# reader プロトコル往復削減の実機比較（2026-09-14）

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
| gold_confirmed（パス省略） | 3周で15件 | 今回 **27実行中18実行（うち reader 対象2ケースが9+0=9件、`auto-one-line` が9件）で missing_gold あり、個別 gold 欠落は合計36件** | 下記参照 | 0件 | **×**（後述: 条件非依存の測定上の要因） |
| モデル指定違反（reader 経路） | 3周で各11件 | **0件**（27実行すべて `requested` は `haiku` か空リスト、`unspecified_or_auto_model`/`first_call_not_haiku`/`sonnet_without_a_prior_attempt` いずれも検出なし） | `judge.agent_resolved_models` の resolved 値はすべて `claude-haiku-4-5-20251001` | 0件 | **○** |
| deny 回数 / 注入バイト数 | 未計測 | `bare`: 全18実行中9(bare分)は deny=0/0B。`skill`: `auto-bulk-facts` 全周 deny=1/1112B、`auto-explicit-multifile` 全周 deny=0/0B、`auto-one-line` 全周 deny=1/1124B。`hooklog="ok"` の18実行すべてで計測できた（除外0件） | 上表参照 | 記録して削減幅と突き合わせ | **○**（計測完了、除外なし） |

### gold_confirmed の内訳（Step 4、`judge.confirmed_items` / `judge.gold_confirmed_ok` を使用）

`evals/compare/cases.json` を確認すると、今回計測に使った3ケースはいずれも
`gold_confirmed` フィールドが未設定（`None`）で、`prompt_delegate`/`prompt_direct`
（`cost_probe.py` が使うプロンプト）も「`confirmed:` 形式で答えよ」という指示を含んでいない
（`confirmed:` 契約を明示するのは `skill` 条件でスキルが子エージェントに渡すワーカー向け
レスポンス契約のみで、親の最終回答フォーマットは規定していない）。実際、
`auto-bulk-facts` の transcript を見ると親の最終回答は箇条書きの平文で
`confirmed:` 行を一切含まない（例: `- report_token() returns the string **"mgt_..."**`）。
このため `judge.confirmed_items()` が0件を返し、`gold_confirmed_ok` は宣言された
gold（`auto-bulk-facts` 3件、`auto-one-line` 1件、`auto-explicit-multifile` は
`gold_file` 未設定のため0件）を **`direct`/`bare`/`skill` の3条件すべてで同一件数**
欠落として報告する。`direct` 条件は今回のプラグイン変更と無関係であるにもかかわらず
同じ欠落数を示しており、これは reader プロトコル往復削減（Task 2〜8）の副作用ではなく、
**`cost_probe.py` のプロンプトが `confirmed:` フォーマットを要求していないことに起因する
測定上のアーティファクト**と判断する。それでも Step 4 の指示どおり自前正規表現を使わず
`judge.py` のヘルパーで機械的に数えた結果として、額面どおり記録する。

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
- `gold_confirmed` の欠落は `direct`/`bare`/`skill` で同一件数発生しており、
  `cost_probe.py` のプロンプトが `confirmed:` フォーマットを要求していない
  ことに起因すると判断したが、これは本プローブの設計上の限界であって
  Task 2〜8 の変更を裏付ける/否定する証拠にはならない。プロトコル変更の
  「契約維持」を厳密に検証するには、`confirmed:` 形式を要求するプロンプトで
  再計測するか、`evals/run.sh`（`gold_confirmed: true` を持つケース）の
  結果を別途参照する必要がある。
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
   モデル指定違反は0件で満たすが、`missing_gold` は27実行中18実行で
   非0（合計36件の gold 欠落）。上記のとおり `direct`/`bare`/`skill` で
   同一件数であり、プロトコル変更由来ではなくプローブのプロンプト設計
   （`confirmed:` 形式を要求していない）に起因すると判断されるが、
   Step 4 のスクリプトを額面どおり実行した結果としては非0であり、
   ゲート条件の文言（`missing_gold`（パス省略）0件）を機械的には満たさない。
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
- `cost_probe.py` のプロンプトに `confirmed:` フォーマット要求を追加するか、
  `gold_confirmed_ok` を適用する対象を `cases.json` で `gold_confirmed: true`
  が明示されたケースに限定するかを検討し、`missing_gold` 指標が
  プロトコル変更を実際に反映するように計測方法を直す。
- 上記2点を解消したうえで、あらためて3周（またはそれ以上）を回し、
  ゲート条件5項目がすべて満たされることを確認してから `repeat.sh 3` の
  判断を再度行う。
