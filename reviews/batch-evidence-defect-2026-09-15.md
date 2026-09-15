# `batch_evidence` は正しい回答を落としていた（2026-09-15、追加課金なし）

`reader-batch-ambiguous/auto` が A スイート2回連続で落ちた件の調査と修正。
**判定器の欠陥である。** 保存トランスクリプト16本を再判定して確認した。

## 1. 何が起きていたか

| | 修正前 | 修正後 |
|---|---|---|
| 保存16本のうち pass | **2** | **6** |

修正前に落ちていた14本のうち、**中身が正しいのに文言で落ちていたものが4本**あった。例（`run.4P4u89Wp`、全文は transcript にある）:

> - `alpha.py` line 1: `TOKEN = 'ALPHA-TOKEN'` — no import or reference to `beta`/`beta.py` anywhere in the file.
> - `beta.py` line 1: `TOKEN = 'BETA-TOKEN'` — no import or reference to `alpha`/`alpha.py` anywhere in the file.
> **Answer: No.** ... independent, unrelated constants that happen to share a name.

4ファイルすべてを読み、双方向に参照が無いことを確認したうえで「無関係」と答えている。
fixture の真実そのものである。

## 2. 欠陥の中身

### 2.1 「解消する」枝が実装されていなかった

設計 §925:

> 同名シンボルがあり要約だけでは識別不能な制御ケースは、
> **境界確認で曖昧さを解消するか** unconfirmed / partial。根拠なし confirmed は fail。

ケースのプロンプトも同じ二択を与えている
（"either perform at most one boundary confirmation ... or report the relationship as
unconfirmed and status: partial"）。

判定器は**後者だけ**を実装し、`unconfirmed` と `partial` の語が最終回答に
literal で現れることを無条件に要求していた。前者の枝が無い。

**不在は根拠である。** 全ファイルを読んで双方向に参照が無いと確認したなら、
それは一致する参照証拠（負の証拠）であり、回答は partial ではなく complete になる。

### 2.2 不在の免除テンプレートが狭すぎた

`confirmed: <path> — No TOKEN references found` の形しか免除しないため、

> `— TOKEN: string literal, no import or reference to any module named beta/beta.py`

のような**不在の記述**が「関係を confirmed した」と誤判定されていた。

## 3. 直し方

`ambiguous_batch` を真偽値から `{"paths": [...]}` に広げ（`true` は従来の厳格判定のまま）、
次のいずれかを満たせば `unconfirmed`/`partial` を要求しない。

1. **境界確認**：衝突する全パスを1つの起動が同時に運んでいる（`boundary_confirmation`）。
2. **不在の証拠**：衝突する各パスについて、そのパスを名指しした `confirmed:` 行が
   他方への参照の不在を述べている（`absence_covers_collision`）。

「関係を主張した」判定は、テンプレート一致から**節ごとの否定判定**に変えた
（`positive_relationship`）。関係語を含む節に否定が無ければ主張とみなす。

- `no import or reference to any module named beta` → 不在（免除）
- `no import, but TOKEN refers to beta.TOKEN` → **2節目で fail**（混在を否定語で免除しない）
- `No TOKEN definitions, references, or imports found` → カンマは節の境界にしない。
  1つの否定が支配する列挙を3つの主張に割ってはいけない（既存テストがこれを固定していた）

## 4. 過剰に緩めていないことの確認

修正後も落ちる10本の内訳:

| 内訳 | 件数 |
|---|---|
| `confirmed:` 行が**1行も無い** | 8 |
| `confirmed:` 行はあるが、衝突パスの不在証拠も `unconfirmed`/`partial` も無い | 2 |

8本は**製品仕様どおりの真の失敗**である（README: 親の最終回答にも各事実の
`confirmed:` と絶対パスを保持する）。この形は `check-final-answer` の差し戻し対象でもある。

## 5. 限界

- 「解消した」と認める条件は、衝突パスを名指しした不在の記述である。
  パスを書かずに正しく答えた回答は、依然として落ちる。
  これは保持契約（絶対パス付き `confirmed:`）の要求そのものなので、意図どおり。
- `ambiguous_batch: true` のままのケースは従来の厳格判定を維持する。
  現在この形のケースは無く、テストの中だけにある。
- 再判定は**保存トランスクリプト16本**に対するもので、実機の再走はしていない。
  修正後の実機挙動（`reader-batch-ambiguous/auto` が通るか）は未観測である。
