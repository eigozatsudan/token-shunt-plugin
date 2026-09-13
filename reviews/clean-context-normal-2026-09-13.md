# クリーンコンテキスト通常コードレビュー

対象: /home/dev/projects/skills/token-shunt の現行作業ツリー（未コミット修正込み）。初回発見では reviews/、docs/history/、過去実行ログを未参照。親ディレクトリを含め AGENTS.md は見つからなかった。外部API・認証済みモデル呼び出しなし。既存ソースへの編集なし。

検証: /tmp/ts-normal-9VjJgO にコピーして evals/run.sh を実行、110 pass / 0 fail（symlink 5、cd 6、scan budget 10、operational 22の回帰も成功）。compare の unittest 89件成功。以下は既存テストが通っていても再現する反例。

## 1. [P2] 空白を含むインストール先で全フックの起動が失敗する

- 場所: plugin/hooks/hooks.json:8、21、32。
- 条件: CLAUDE_PLUGIN_ROOT が空白を含むディレクトリを指す（空白のあるホームディレクトリ、任意の --plugin-dir 配置など）。command の `${CLAUDE_PLUGIN_ROOT}/hooks/...` に引用符がない。
- 再現: plugin を `/tmp/token shunt normal .../plugin` にコピーし、同環境変数を設定、hooks.json の command を `bash -c` で実行。exit 127、`bash: line 1: /tmp/token: No such file or directory`。フック本体に到達しない。
- 影響: jq診断、ReadとBashのサイズ判定が動作しない。具体的にClaude Codeが非ゼロ起動エラーをどのように提示・許可判定するかは今回のオフライン再現では未確認だが、プラグインの機能が実行されない点は確実。
- 修正案: JSON内のcommandを `\"${CLAUDE_PLUGIN_ROOT}/hooks/check-file-size\"` のようなシェル引用付きにする。3フック共通の空白ルート起動テストを追加。
- 確信度: 高（0.98）。反証候補: CLIがcommand文字列をシェルではなく特殊な単一パスとして扱うなら再評価。ただし任意command用設定の通常のシェル実行では再現する。空白禁止の仕様は見つからなかった。

## 2. [P2] 親コンテキスト量からAgentプロンプトやWrite本文が抜ける

- 場所: evals/compare/judge.py:94-111（assistantはtextブロックのみ保存）、168-178（parent_added_textが保存textだけを加算）。
- 条件: 親assistantのtool_use.inputに長い文字列がある。特にAgent(prompt=...)、Write(content=...)、Bash(command=...)など。
- 再現: 親assistantにAgentのtool_useブロックを1個作り、input.prompt=`'secret_reference_body_'*5000`とする。実際のpromptは110000 UTF-8 bytesだが、Transcript(events).metrics()['parent_added_utf8_bytes']は0。
- 影響: ツール引数も親が生成して会話に残す内容なのに、isolationの合否に使用する量から全て欠落する。大きな委譲プロンプトを生成した経路や親が生成本文を別toolに渡した経路で、コンテキスト削減を過大評価する。同じ関数を使うleakcheckもその経路を見ない。別途parent Write違反検査があるケースでも、Agentプロンプトの過少計上は残る。
- 修正案: 親assistant contentのtool_use.input文字列（少なくともprompt/content/command等）も一貫した形で一度だけ計上する。子tool_useは除外し、同一message idの重複回避は維持。Agent promptに長文があるsynthetic回帰を追加。
- 確信度: 高（0.96）。反証候補: 指標を意図的に「自然言語textブロックだけ」と定義していた場合。ただし設計§13のparent_added_charsは親トランスクリプトに新たに載ったuser/assistant/tool_resultを対象とし、親コンテキスト削減の必須判定に利用しているため、その限定とは整合しない。実トークンusageを別記録することもUTF-8 isolation判定の欠測を補わない。

## 3. [P2] 2KiB連続引用の検出に文字数・サンプリングによる見逃しがある

- 場所: evals/compare/judge.py:512-521、1436-1440。
- 条件と再現（いずれもquote_leakの結果は `(False, '')`）:
  1. body=`'漢'*1000`、返答がbodyそのもの。UTF-8で3000 bytesの全文引用だが、len(body)=1000で2048文字に達せず、1行なので行数検査も通過する。
  2. `random.Random(27).choices(string.ascii_letters,k=5000)`で一行bodyを作り、返答にbody[1:2050]を置く。2049-byte連続引用だが、512文字ごとに採った2048文字windowが完全には含まれないため通過する。
- 影響: 子返答の4000文字枠内でも、必須の「2KiB超の連続引用なし」契約違反がpassになる。writer_body_absentのleakcheckにも同じ文字数・stride方式があり、生成本文漏洩の検証を過信できない。
- 修正案: UTF-8 bytesで連続一致長>2048を判定し、任意開始位置をカバーする（rolling hash等か、fixture/返答の制限を利用した十分軽い連続一致探索）。2関数を共通化してUnicode、非整列開始、閾値ちょうど・1 byte超のテストを追加。
- 確信度: 高（0.99）。反証候補: KiBが実際には文字数か、近似サンプリングと意図的に定義されている場合。ただしdocstring・設計は2KiB連続引用を不合格とし、この見逃しは既知制限に見当たらない。

## 指摘にしなかった範囲

未知コマンド末尾パイプ、変数展開・stdin追跡・間接実行、限定外cd、逐次targeted Read、非テキスト拡張子、時間予算のブロックFS非中断、ワーカー契約のプロンプト依存は明示された制限として除外。agent/skillのbounded delegation・既存target Read・親検証手順を確認し、別途確実な欠陥は追加しなかった。配布ZIPの構成・権限検証はコピー上の基礎テストで成功。認証されたCLIの現行挙動は本レビューで実機検証していない。

# 統合後の偽陽性確認・訂正

## 初回指摘1は撤回（最終指摘から除外）

親からの反証を受け、[公式Hooks referenceのexec form](https://code.claude.com/docs/en/hooks#exec-form-and-shell-form)を確認した。`args`が存在すると（空配列でも）commandはプレースホルダー置換後に直接spawnされ、シェルの単語分割は起きない。現行hooks.jsonは全フックに`args: []`がある。初回の`bash -c`再現は実際のexec formを模倣しておらず、空白パス不具合の証拠にはならない。引用符追加の推奨も取り消す。初回の条件付き反証が成立したため、指摘1はFP。

## 4. [P2] writer漏洩検査は反復行を1文字の返答だけで21行引用と誤判定する

- 場所: evals/compare/judge.py:1441-1447（leakcheckの行引用ループ）。
- 再現: target本文=`'a\n'*21`（42 bytes）、親assistant text=`'a'`（1 byte）。leakcheck(transcript,target)は`leak: >20 consecutive lines`と表示し0（漏洩検知）を返す。同じデータをquote_leakへ渡すと`(False, '')`。
- 原因: targetの各行が親テキストのどこかに含まれるかを独立に調べてrunを加算している。同じ1文字を21回再利用しても連続21行が引用された扱いになる。行の順序・改行・隣接を調べないので、反復以外でも個別の行断片が散在すると同様にfalse positiveになりうる。
- 影響: 本文を漏らしていないwriter実行をrelease gateで不合格にできる。反復の多い定型生成ファイルはスキルの用途にも合致するため、人工的な文字列だけの問題ではない。
- 修正案: quote_leak側と同じく21行の連続window全体が親返答に含まれるかを検査し、共通化する。反復行1文字返答はclean、実際の21行連続引用はleakという両方向テストを追加。
- 確信度: 高（0.99）。反証候補: 「異なる位置の同じ1行を21回数える」のが意図された仕様の場合。ただしdocstringはconsecutive linesで、quote_leakの既存コメントも同じ誤判定を明示的に否定している。
- 指摘3との関係: **別根**。3は2KiB判定のUTF-8未変換・512strideによるfalse negative。4は行引用判定の隣接性欠落によるfalse positive。同一ファイル・関数に隣接するが、発生条件も修正点も独立であり、別指摘として扱える。共通の背景としてquote_leakとleakcheckの重複実装がある。
