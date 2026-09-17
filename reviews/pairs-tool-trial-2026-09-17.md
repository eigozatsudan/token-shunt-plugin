# `pairs.py` を実機の run で通した（2026-09-17）

道具の試験であって、測定ではない。**事前登録は無い。結論は何も出していない。**

## 1. なぜ実機で試したか

`pairs.py`（`18d1fbf`）はテスト 15 件で裏付けてあるが、**フィクスチャは私が書いた
transcript** であり、実機の transcript の形に当たっていなかった。
本物の run ディレクトリは**この直前に私が全部削除している**ので、
試すには新しく回すしかなかった。**課金の許可を取った上で 4 対回した。**

## 2. preflight

専用チェックアウト `/tmp/ts-pairs` を `18d1fbf` に固定、生成物を除いて clean、
**その中で `judge.py --selftest` 全項目 pass**、`test_pairs.py` 15 件 OK を確認。

## 3. 費用

見積り **$1.0**、実測 **$1.0868**（**8.7% 超過**）。

**超過の理由は分かっている。** `spend.py` のガードは **run の前**に見るので、
3 本目の後の残高は $1.0 を下回っており、4 本目が枠を越えた。
**「実行前に確認する」ガードは、1 run 分の粒度で必ず行き過ぎる。**
今回は 4 本と分かっていたので止めていないが、
**枠を厳密に守るなら見積り 1 run 分を引いた値を `--cap` に渡す必要がある。**

## 4. 結果: 通った

```
run,case,direct_read_bytes,auto_read_bytes,direct_cost_usd,auto_cost_usd,...
run.1tNgbqAO,redmine-last-query,5690,0,0.0561,0.1468,1,1,1,1,
run.JY3Z2wgL,redmine-last-helper,78934,0,0.1785,0.1115,1,1,1,1,
run.Zh1Yx9Kj,redmine-last-user,39970,0,0.1033,0.0970,1,1,1,1,
run.z3pIlThS,redmine-last-journal,3694,0,0.0516,0.1019,1,1,1,1,
```

`reviews/data/pairs-tool-trial-2026-09-17.csv` にコミットした。

### 4.1 独立に検算した

**道具を道具自身で証明しない。** `run.z3pIlThS` の 1 行を別実装で確かめた:

- 費用は `jq -s '... | last | .total_cost_usd'` で **0.0515834 / 0.10194929**
  → CSV の `0.0516` / `0.1019` と一致。
- `direct_read_bytes` はその場で書いた別の walk で **3694** → 一致。

`redmine-last-helper` の `78934` は、block2 48 対の中央値 78,934 と同じ値である。

## 5. 分かったこと（道具について）

- **実機の transcript でそのまま動く。** 形の取り違えは無かった。
- `auto_read_bytes` は 4 対とも 0。フックの拒否文が出る run は今回は無かった
  （出れば 0 にならないのは `reviews/redmine-dose-2026-09-17.md` §4 のとおり）。
- **run ディレクトリ名でソートされるので、CSV の diff が読める。**

## 6. 数字を測定として読まないこと

- **N = 各 case 1 対。** 事前登録も無い。
- それでも `redmine-last-journal` の `direct_read_bytes` は **3,694** で、
  block2 12 対の中央値 **14,295** と大きく違う。
  **同じ問い・同じファイルでも親の飲む量は run ごとに動く。**
  用量を対ごとに実測する設計（`redmine-dose-design` §2.1）の必要性が、
  たまたまここでも見えている。
- 費用の向き（helper で auto が安い、journal/query で auto が高い）は
  `reviews/redmine-dose-2026-09-17.md` の結論と**矛盾しない**が、
  **4 点の便宜標本であり、裏付けではない。**
