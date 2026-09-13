# token-shunt の配布

配布物は `plugin/` の内容をまとめた `token-shunt.zip` です。現在はv0.1.0の開発段階で、親コンテキストへの大きな本文の持ち込みを減らすことを目的としています。トークン・料金の削減効果は未確認です。

## ビルド

リポジトリのルートで実行します。

```bash
scripts/build-zip.sh
```

スクリプトは3つのフックに実行権限を付け、既存の `token-shunt.zip` を置き換えて `plugin/` を圧縮し、配置と実行権限を検証します。作成には `zip` または Python 3、検証には Python 3 または `zipinfo` が必要です。検証に失敗すると終了コードは非0になります。

生成するZIPの主な構成は次のとおりです。

```text
.claude-plugin/plugin.json
agents/bulk-reader.md
agents/code-writer.md
hooks/hooks.json
hooks/check-file-size
hooks/check-bash-read
hooks/check-jq
skills/bulk-reader/SKILL.md
skills/code-writer/SKILL.md
```

検証では `.claude-plugin/plugin.json` がアーカイブ直下または1階層下にあることと、3つのフックにUnixの実行権限があることを確認します。実際のビルドはアーカイブ直下に配置します。フックは直接実行されるため、展開後も実行権限が必要です。

リポジトリのルートにある `.claude-plugin/marketplace.json` はZIPに含みません。

## 読み込み

ZIPを任意の空ディレクトリに展開し、プラグインのルートを指定します。以下はリポジトリのルートで実行する例です（展開には `unzip` が必要です）。

```bash
mkdir -p /tmp/token-shunt-plugin
unzip token-shunt.zip -d /tmp/token-shunt-plugin
claude --plugin-dir /tmp/token-shunt-plugin
```

ソースから直接読み込む場合は次のとおりです。

```bash
claude --plugin-dir ./plugin
```

ローカルマーケットプレイスとして登録する場合はリポジトリのルートを指定します。マニフェストは `name`、`owner.name`、`plugins` を持ち、プラグインの参照先 `plugins[].source` は `./plugin` です。

## 配布前の確認

```bash
evals/run.sh
python3 -m unittest discover -s evals/compare -p 'test_*.py'
scripts/doctor.sh
evals/compare/run.sh
```

ZIPの検証や診断の成功だけではリリース可能とは判断しません。[設計書](../2026-09-12-token-shunt-design.md) §26.5・§26.6に沿って、スイートA・B、本文の分離、必須の親トークン計測と費用比較を確認します。実機比較評価の集計では `selected_run_valid` と `release_eligible` を区別してください。

利用方法、依存コマンド、フックの制限事項は[ルートREADME](../../README.md)を参照してください。
