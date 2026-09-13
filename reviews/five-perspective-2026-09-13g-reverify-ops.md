# 再検証: doctor はソースを confirmed とし、ユーザースコープキャッシュは見ない

日付: 2026-09-13
対象 HEAD: `cb1ab7c94952df128aa9d171217177390b4a151e`
視点: 運用（独立再検証）
ライブ marketplace install / `~/.claude` 改変: 未実施（禁止どおり）

## 分類

**Docs-only P3。メカニズムは真。FALSE POSITIVE ではない。doctor 本体のコード欠陥としての TRUE POSITIVE でもない。**

主張「doctor はソースツリーのエージェントを confirmed と記録しうる一方、通常の `claude` が使うユーザースコープキャッシュは欠落・陳腐化していても検知しない」は現行コードと公式ドキュメントで成立する。ただしこれは `--plugin-dir` 隔離プローブとしての doctor 実装が壊れているという意味ではない。欠陥は、README がユーザースコープ導入を継続利用の正規手順とした直後に、同じ文書が doctor を「インストール・モデル解決の診断」と案内し、キャッシュ正本・version バンプ・更新手順を書いていない点にある。

## 判定の理由（3 択の適用）

- **TRUE POSITIVE 条件の前半は満たす。** README はユーザースコープ導入のあとに doctor をインストール診断として出す。doctor は導入済みコピーを見ない。
- **FALSE POSITIVE 条件は満たさない。** doctor は「ソースツリー / `--plugin-dir` 専用の開発プローブ」と明記されていない。キャッシュ対ソースの一文と「終了コード 0 は全項目確認ではない」はあるが、後者は認証オフの `unconfirmed` 向けであり、導入済みキャッシュ未検査の注記ではない。
- **Docs-only P3 条件を採用する。** `--plugin-dir` ワークフロー向けのコードは設計 §7 / §13 / §14 と整合する。直すべきは README（と配布 README）の導入・更新・doctor の対象範囲である。

## 証拠

### 1. doctor は常にソースの `--plugin-dir` を使い、導入済みコピーを見ない

`scripts/doctor.sh` のライブプローブは 3 箇所とも `$ROOT/plugin`（または相対 `plugin/`）固定。

- プラグインロード: 46–48 行。`--setting-sources ""` と `--plugin-dir "$ROOT/plugin"`。
- モデル / effort / maxTurns: 99–100 行。同じく `--setting-sources ""` と `--plugin-dir "$ROOT/plugin"`。
- 手動 `agent_type` 案内: 237–239 行。`claude --plugin-dir plugin/`。

ロード成功時は 217 行で `plugin + agent registration: confirmed` を `docs/distribution/doctor-last-probe.txt` に書く。この confirmed はソースツリーの登録であり、`~/.claude/plugins/cache` の有無・版・実行ビットではない。

加えて、仮に `--plugin-dir` を外しても現行の `--setting-sources ""` は user / project / local 設定を読まない（設計 §13 の OAuth 代替）。ユーザースコープの `enabledPlugins` も載らない。元指摘の「`--plugin-dir` なしプローブを足せばキャッシュを見る」は、このフラグを同時に外さない限り成立しない。フラグを外すと隔離が壊れ、他プラグインのフックが混入する。設計 §13 が比較 eval で禁じている状態である。

### 2. README はユーザースコープ導入を正規手順とし、doctor をその診断として出す

`README.md`:

- 19–32 行: 「起動時に自動で読み込む」＝継続利用。`claude plugin marketplace add .` と `claude plugin install token-shunt@token-shunt --scope user`。以後は通常の `claude`。キャッシュにコピーされると明記。
- 34–48 行: `--plugin-dir` は「一時的に読み込む」。
- 192–193 行: `scripts/doctor.sh` を「インストール・モデル解決の診断」と案内。
- 208–210 行: doctor は jq / CLI / プラグインとエージェント登録 / モデルを確認すると書く。exit 0 を全項目確認と読むな、とある。`--plugin-dir` 固定であること、キャッシュ未検査であることは書かない。
- `claude plugin update` / `claude plugin marketplace update` / `plugin.json` の version バンプは導入節にも診断節にも無い。

`docs/distribution/README.md` 51–64 行も同じユーザースコープ手順とキャッシュコピーを書き、73 行で `scripts/doctor.sh` を配布前確認に並べる。更新手順は無い。

doctor 自身のヘッダ（`scripts/doctor.sh:1–13`）は design §14 の install-time sanity と `--plugin-dir` プローブを述べるが、ユーザ向け README はその限定を転写していない。

### 3. version は 0.1.0 ピン。公式どおりキャッシュ更新の信号になる

`plugin/.claude-plugin/plugin.json` の `"version": "0.1.0"`。marketplace エントリ側に version は無い。設計 §7 は「`version` は 0.1.0 で固定する（この仕様の初版）」と明示する。

現行公式（2026-09-13 取得）:

- [Create plugins](https://code.claude.com/docs/en/plugins): `--plugin-dir` はインストール不要の開発ロード。同名の marketplace 導入済みプラグインよりローカルコピーがセッション中優先する（managed の強制 enable/disable を除く）。
- [Plugin marketplaces](https://code.claude.com/docs/en/plugin-marketplaces): 導入時はプラグインディレクトリをキャッシュへコピーする（command ソースの link mode 以外）。相対パス `source: "./plugin"` はコピーであり in-place link ではない。`version` を置くと、その文字列を変えたときだけ利用者は更新を受ける。
- [Plugins reference — caching](https://code.claude.com/docs/en/plugins-reference#plugin-caching-and-file-resolution): marketplace プラグインは `~/.claude/plugins/cache` へバージョン別コピー。`--plugin-dir` はセッション限り。
- [Plugins reference — version management](https://code.claude.com/docs/en/plugins-reference#version-management): キャッシュキーは version。`plugin.json` の version が最優先。明示 version ではバンプなしのコミットは無効で、`/plugin update` は already latest と報告する。
- [Discover plugins](https://code.claude.com/docs/en/discover-plugins): 第三者・ローカル開発 marketplace の auto-update は既定オフ。

したがって、README どおり一度ユーザースコープ導入したあとソースだけ直しても、通常起動の正本は古いキャッシュのまま残る。doctor はソース側を confirmed としうる。ライブ install は未実行だが、コピーと version ピンは公式仕様で足り、リポジトリ上の事実と矛盾しない。

### 4. 設計 §§1–15 / §26 は doctor にキャッシュ検査を要求していない

- §7: doctor はフック stdin の `agent_type`、呼び出し時モデル、Haiku/Sonnet 実モデル、effort、maxTurns partial、実装時の最低対応版記録。対象は CLI / ソースプラグインの能力確認。
- §8 / 成功条件 8: marketplace は `name` / `owner.name` / `plugins` と add → install の対象になること。doctor が導入済みキャッシュを照合する契約はない。
- §13: 比較 eval の委譲は `--plugin-dir plugin/`。隔離は `--setting-sources ""` とクリーン cwd。ホスト marketplace の token-shunt を読まないことが要件。
- §14 README 必須の導入は「`claude --plugin-dir plugin/` または zip。marketplace add はリポジトリルート」。doctor 必須は jq / FORCE / `agent_type`。キャッシュ診断は必須リストに無い。
- §26.1: doctor は要求モデルと実モデル、FORCE 上書きの明示。インストール経路の正本確認ではない。

doctor が `--plugin-dir` + `--setting-sources ""` なのは、設計の隔離契約そのもの。ここを「導入済みコピーを見ないバグ」として直すと、§13 の隔離を崩す。

## コード変更は不要か

**不要。ドキュメントのみ。**

`--plugin-dir` ワークフロー（一時ロード、ZIP、比較 eval、設計どおりの隔離プローブ）に対して doctor のコードは正しい。導入済みキャッシュをライブで読む第二プローブは:

- `--setting-sources ""` を外す必要があり、他フック混入で診断が汚染される
- `~/.claude/plugins/cache` を読む場合でもユーザ環境に依存し、未導入を hard fail にすると jq 以外は fail しない現行契約（スクリプト先頭と README 208 行）と衝突する
- 設計 §7 / §14 の doctor 範囲外

任意の強化（キャッシュディレクトリの存在を `unconfirmed` 注記するだけ等）は運用の親切だが、本指摘の是正条件ではない。

## ドキュメントに書くべきこと

README 導入（および `docs/distribution/README.md` の自動読み込み）:

1. 継続利用の正本は `~/.claude/plugins/cache` のコピーである。登録元リポジトリの `plugin/` を直接は使わない。
2. `plugin.json` の `version`（現行 0.1.0）が更新信号である。ソースを直しただけではキャッシュは更新されない。バンプしたうえで `claude plugin marketplace update token-shunt` と `claude plugin update token-shunt@token-shunt`（または再インストール）。ローカル marketplace の auto-update は既定オフ。
3. `--plugin-dir` はセッション限定の開発ロードであり、同名の導入済みプラグインより優先する。doctor と eval はこの経路を使う。

README の doctor 節:

4. `scripts/doctor.sh` は `$ROOT/plugin` を `--plugin-dir` で隔離ロードするソースプローブである。ユーザースコープ導入の成否・キャッシュの新旧・フック実行ビットは確認しない。
5. `plugin + agent registration: confirmed` と exit 0 を、通常起動で使うコピーの確認と読まない。

以上で、主張の運用リスク（ソースを直しても現場の `claude` に届かない／doctor が誤った安心を出す）は手順として閉じる。ライブ marketplace install によるキャッシュ実体の突合は本再検証の範囲外。
