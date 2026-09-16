# 製品が解決した宣言集合を走行中に記録する（2026-09-16）

`reviews/scope-prevention-stage1-2026-09-16.md` §7.2 で保留にした A6（抽出の
食い違い）を、事後採点で扱えるようにするための計装。**課金なし。**

## 1. なぜ事後には測れないのか

`reader_scope.declared_paths` は **ファイルが実在することを要求する**
（存在しないパスは読まれ得ないので、集合に入れても決定が変わらないため）。
一方 `evals/compare/run.sh` の `gen_fixtures` は mode ごとに `$TMP` を消す。

したがって run が終わった後に transcript を採点すると、
**製品が見ていた宣言集合は必ず空になる。**
stage 1 の再採点で食い違いが 15/15 になったのはこれが理由で、
A6 は「測れない」として項目ごと取り下げた。

**製品が何を宣言集合だと思ったかは、その場でしか残せない。**

## 2. 足したもの

`plugin/hooks/reader_scope.log(rec, path=None)`。
`SCOPE_TRIAL_LOG` が指すファイルに JSON を 1 行 append するだけ。
先例は `sendback_stop.log`（`SENDBACK_TRIAL_LOG`）と
`plugin/hooks/write-hook-log`（`TOKEN_SHUNT_HOOK_LOG`）。

`check-reader-contract` 側は 2 箇所:

- スコープを**初めて解決したとき** → `{"event":"scope", session_id, agent_id, scope}`
- **拒否したとき** → `{"event":"refused", ..., "path": <拒否したパス>}`

`state['scope']` のキャッシュに乗せてあるので、**invocation ごとに 1 行**。

## 3. 計器が製品を壊さないための線引き

**拒否が製品で、記録は製品ではない。**

- `log()` は全体が `try/except Exception: pass`。
- 呼び出し側の `record()` も**独立に** `try/except` で包んである。
  `log` 自体が差し替えられて raise する場合でも決定は変わらない
  （テストで `patch('reader_scope.log', side_effect=RuntimeError)` を固定）。
- **環境変数が無ければ何も書かない**（既定は完全に無効）。

## 4. テスト（9 件、実装より先に書いた）

`evals/test_reader_scope.py` `TrialLogTests`（5 件）:
1 レコード 1 行の JSON / 宛先が無ければ何も書かない /
`LOG_ENV` が宛先を決める / 書けない宛先でも例外を出さない /
JSON にできないレコードでも例外を出さない。

`evals/test_reader_contract.py` `DeclaredScopeTests`（4 件）:
invocation ごとに scope が 1 行だけ出る（`session_id`/`agent_id` つき）/
拒否がパスつきで残る / `SCOPE_TRIAL_LOG` が無ければ何も出ない /
**`log` が raise しても拒否の判定と文言が変わらない。**

記録されるパスは realpath（フックがそう保持しているため）で照合している。

## 5. これで何ができるようになるか

以後のスコープ測定は、run を買い直さずに

- 製品が見た宣言集合（A6 の分母そのもの）
- 拒否の発生（`scope_probe` の推定ではなく実物）

を事後に突き合わせられる。**走行中の 50 run はこの計装より前なので対象外。**

## 6. 確認

`unittest discover -s evals` **288 OK**（+9）、`-s evals/compare` 532 OK、
`judge.py --selftest` 全項目 pass、`evals/run.sh` 240 pass / 0 fail。
`token-shunt.zip` は戻した。
