# Orchestrator Local 0.6.0 — Windows向け初期版

> いつものAIへの頼み方はそのまま。作業の一部をPC内のAIに分担させ、クラウドAIの消費を抑えることを目指します。

[English](README_EN.md)

## 使うと何がよいか

ユーザーにとっての本来の狙いは、**今までと同じように依頼して、必要な品質の結果を受け取り、そのためのコストを下げること**です。

表の整理や集計などの実作業をPC内のAIにも分担させ、いつもの会話で結果を受け取ります。受け渡し・差分修正・保存は、この使い方を支える裏側の仕組みです。

### 関連する検証結果

設計の参考にした100件比較では、Solの確認・部分修正込みの既知Credits小計が約32.78％減り、採用データは両方式100/100件正解でした。一方、平均active時間は63.10秒から247.32秒に増えました（RTX 3080 10GBでの実測）。

[検証結果の要約と元記録](docs/EVALUATION_JA.md)を参照してください。これは合成業務データでの比較であり、公開アプリの会話側Creditsはまだ計測していません。

### 内部では何をしているか

相談・設計と最終確認を会話側のAIが担当し、実作業の一部をGemmaへ渡します。使える結果はそのまま採用し、必要な箇所だけ直して保存します。詳しい説明は、下の[処理と確認](#処理と確認)と[内部の構成図](DESIGN_JA.md)に残しています。

## この版でできること

対象は、条件がはっきりしているCSV/JSONの整理・集計、一覧と短い報告文、小規模アプリのコード案です。元資料と作成結果を会話で確認し、ファイルとして保存できます。

例えば「電卓アプリを作って」と依頼すると、Codexが必要な範囲を決め、Gemmaにコード案を分担させます。Codexが確認して作業フォルダへ反映し、起動・テストまで行います。小さく直接処理した方がよい仕事はCodexが処理します。ONは、すべての開発作業を自動で分担する設定ではありません。

Windowsで、既存Ollamaの`gemma4:26b`を実行できるPCが対象。GUI配布版はPythonを同梱し、ソース版にはPython 3.11以降が必要。RTX 3080 10GBを搭載したWindows PCで実機確認したが、別PC・全GPUでの動作を確認したものではない。モデルの重みとOllamaは配布に含まない。macOS/Linux、ブラウザだけの利用はこの版の動作確認対象外。

## Windowsで始める

[インストーラをダウンロード](https://github.com/o0w0v/orchestrator-local/releases/download/v0.6.0/OrchestratorLocal-0.6.0-Setup.exe)して開き、案内に沿って「次へ」で進めてください。管理者権限やPythonの手動導入は不要です。既存のOllamaとGemma4:26bは必要です。

1. 検出した保存先・Ollamaを確認し、「インストールする」を押します。
2. Codexを再起動して、新しい会話を開きます。
3. スタートメニューからOrchestrator Localを開き、使いたいときにONにします。

以前の導入があれば、設定・モデルの場所・成果物・自動起動を引き継ぎます。登録解除やフォルダ移動は不要です。設定はバックアップし、利用者が変更したSkillや作業中の依頼がある場合は上書きせず案内します。

|切り替え|動作|
|---|---|
|ON|対応する作業で、必要に応じてGemmaへ分担する|
|OFF|新しいGemma作業を開始せず、通常のCodexで処理する|

依頼と結果の受け取りはCodexの会話で行います。中央の電源ボタンで切り替えます。ONは緑のリング、OFFはグレーで表示し、文字でも状態を確認できます。初期状態はOFF。ONでも「今回は使わない」という指示を優先します。設定・履歴は「詳細」にあります。

ON/OFFは再起動なしで反映します。進行中の作業は継続し、待機中は次にONにするまで保留します。同じ保存先を使う会話で共通です。Skill登録は残ります。

詳しい[使い方と更新](docs/GUI_JA.md)、[リリースとSHA-256](https://github.com/o0w0v/orchestrator-local/releases/tag/v0.6.0)も参照してください。手動配置向けのZIPも残しています。Windows版は未署名の初期版です。

## ソースから導入する

このリポジトリをcloneまたはZIPで展開し、`pyproject.toml`のあるルートフォルダをPowerShellで開く。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe setup_local.py
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe setup_local.py --register
.\.venv\Scripts\pythonw.exe start-gui.pyw
```

既存OllamaがPATHで見つからなければ、最初の`setup_local.py`に`--ollama-exe`で実ファイルを指定する。標準的な配置例は`--ollama-exe "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"`。モデルを別フォルダに置いている場合だけ`--ollama-models "既存のモデルフォルダ"`も指定する。モデルの自動ダウンロードは行わない。

接続登録後、デスクトップアプリの設定からMCPを再起動し、新しい会話を開く。必要ならアプリを再起動する。接続の仕組みは[公式のデスクトップMCP説明](https://learn.chatgpt.com/docs/extend/mcp)を参照。アカウントやクライアントでLocal MCPが使えることが前提となる。

PowerShellがスクリプト実行を制限する環境では、そのPCの方針に従って実行する。MCP接続登録だけでは独立実行サービスは起動しない。

## 最初の依頼

新しい会話で次を入力する。サンプルはセットアップ時に利用者のinboxへコピーされる。

```text
$orchestrator-local
inboxのinventory-example.jsonを使って、注文ID順に在庫を引き当て、一覧CSVと短い共有文を作ってください。
取消はEXCLUDEDで引当・不足0。対象は引当=min(注文数,残在庫)//lot*lot、不足=注文数-引当とし、引当数だけ在庫を減らします。
数量と件数を区別し、不足がある場合は資料に基づく実際の原因を書いてください。使える成果物はそのまま採用し、必要な箇所だけ直してください。
```

普段の入力は、許可したinboxに置くCSV/JSON/TXT/MD、または会話で読める添付の内容。添付からローカルファイルを自動取得できることは前提にしない。読める内容をinputsへ渡すか、inboxを使う。既存コードの必要箇所はCodexが読んでinputsに渡します。Office GUI操作やWeb調査はこのアプリの対象外です。

出力はジョブごとに`artifact.json`、`data.json`、`report.md`、指定したCSV。追加修正は新しいresult版へ保存されるので前のファイルも残る。保存先は`local_status`や完了した保存ツールの結果から分かる。

コード案は、確認後の`source/`に指定した相対パスで保存します。このアプリ自体はリポジトリの編集やコード実行を行いません。Codexが内容を確認して、依頼された作業先へコピーし、必要なテストをします。[コード作業の流れと対象範囲](docs/CODE_JA.md)を参照してください。

会話に専用MCPツールが表示されず、シェルを利用できる場合は、Skillに同梱した補助経路をCodexが使用できます。利用者がコマンドを入力する必要はありません。どちらの経路も同じON/OFF・依頼キー・確認と保存処理を使います。

## 保存先・起動・接続設定

既定の入力フォルダは利用者の`Documents/Codex/OrchestratorLocal/inbox`、結果は同じデータフォルダの`jobs`。厳密な場所はセットアップ結果と`local_status`に表示される。PC固有のパスは`local-settings.json`に作り、GitHubには送らない。

`--register`はこのMCPと同名Skillだけを追加し、既存config.tomlはバックアップする。同名の異なる接続/Skillを上書きしない。`local-settings.json`を変更すると保存先や許可入力フォルダを調整できる。接続設定はstdio、コマンドはこのvenvのPython、引数は`serve.py --config local-settings.json`の絶対パス。登録後はアプリのMCP接続を再起動する。

`start-service.ps1`は独立した実行サービスを非表示で起動する。待機中はモデル生成をしない。MCP接続を閉じてもこのサービスが作業を続ける。手動起動設定ではPC再起動後にこのスクリプトを実行する。停止は`.venv\Scripts\python.exe service_entry.py --stop`。アプリを閉じることと、作業を中止することは別であり、中止したいジョブには`cancel_job`を使う。

ログイン時の自動起動を選ぶ場合は`enable-startup.ps1`、解除は`enable-startup.ps1 -Disable`。自分のユーザーのStartupに専用ショートカットを作る。他の自動起動項目は変更しない。

自動起動は既定では登録しない。登録後はコード・venvのフォルダを移動しないこと。絶対パスが変わる場合は、元の場所で登録解除してから新しい場所で登録する。

`plugin.json`と`mcp.json`は同じ部品の配布用manifest。この初期版のWindowsパッケージはvenvとローカル設定を作成してから使う。ディレクトリへ公開・審査済みのプラグインとは別である。

## 処理と確認

- `start_job`は元依頼・合意条件、inputs/input_paths、任意data_schema/csv_exportsを受け取る。同じrequest_keyと入力を再送しても二重生成しない。別の依頼には別key。
- `start_code_job`は元依頼・inputs・作成する相対ファイル名を受け取り、`data.files`のpath/contentでコード案を返す。ファイル名の逸脱や重複を拒否し、採用時だけ結果フォルダへ出力する。
- 生成中は`get_job(wait_seconds=25)`。workerは会話のstdio接続から独立して動作し、ジョブはSQLiteへ保存する。アプリやOSがworkerも終了した場合はINTERRUPTEDとし、自動再生成しない。
- 候補は`CANDIDATE_READY`。会話側が元資料で確認して`finalize_job`へACCEPTまたはPATCHを返すまで成果物として採用しない。
- PATCHはJSON Pointer、厳密なbefore/after、利用への影響を指定。重複・親子の重なり・古いhash・形式違反を拒否し、全差分が有効な時だけ保存する。
- ユーザー指定の追加修正は`amend_result`で対象だけ変更。新しい版を作り、Local生成を増やさない。
- `cancel_job`はそのジョブのHTTP接続を閉じる。他のOllama processは止めない。GPU上の実処理停止時刻はOllama側にも依存する。

保存時のCSVはUTF-8 BOM付き。数式として解釈され得る文字列には先頭アポストロフィを付ける。元の値はJSONに保持する。CSVの数値文字列を入力時に推測変換しない。

## 費用・実験との違い

会話側のモデルはアプリで選択したモデル。プログラムはSol/Luna/Terraを別に呼ばないため、会話側のモデル・effortを固定した実験の再現ではない。会話側の消費Creditsはnull、Local実測tokensと時間だけを記録し、節約額を推測しない。

Gemmaは既存digest・native thinking・ctx65536/output32768・seed/samplingを使用。業務版は既存Ollamaを再利用し、必要な場合だけ所有serverを起動、モデルを5分保持する。100件実験の「毎回fresh load/停止」と条件が異なる。過去の実験成績を業務の品質保証とは扱わない。

既定のdigestは`08ae7ec1744bd7f451c4a530afb39d2673ad9d07a8369b8a33a3613b41212a68`。同じtagでも手元のモデルが別digestなら生成せず停止する。別モデル版を使う場合は利用者が`local-settings.json`を明示変更する必要があり、その構成はこの版の実機確認とは別になる。

入力は許可フォルダ内のファイルに限り、サイズ/形式とLocal入力上限を確認する。候補にshell/tool権限を与えない。形式検証は意味の正しさの証明ではない。会話側による確認が必要。

入力資料と候補は、確認のため会話側にも返る。完全オフラインの構成ではない。設定、入力、SQLite、生成物、ログ、認証情報を公開リポジトリへ追加しない。この公開ソースに利用者のデータや認証情報は含めていない。

## 更新・登録解除

以前の`OrchestratorMD/apps/orchestrator-local`版を導入済みの場合は、旧フォルダで下記の登録解除を行ってから、新リポジトリのルートで導入手順を実行してください。独自の保存先を引き継ぐ場合は、その場所を`setup_local.py --data-dir`で指定します。

更新前に`service_entry.py --stop`で実行サービスを正常停止し、以下の方法で現在の版の登録を解除する。更新後に依存関係の導入・テスト・登録・起動を行う。自動アップデーターはない。

```powershell
.\.venv\Scripts\python.exe service_entry.py --stop
.\enable-startup.ps1 -Disable
.\.venv\Scripts\python.exe setup_local.py --unregister
```

この導入先と一致するMCPだけを外し、同梱版と一致するSkillをデータフォルダのruntimeへ保全移動する。既存configはバックアップする。別の導入先や利用者が変更したSkillは自動削除せず停止するので、表示内容を確認して手動で整理する。保存済み成果物・inbox・Ollama・モデルは削除しない。解除後はアプリのMCP接続も再起動する。

## 実装と確認

`orchestrator_local/core.py`がジョブ・入力・差分・保存、`service.py`が独立した実行サービス、`worker.py`がOllama生成と中止、`server.py`がMCPの9ツール、`tool_bridge.py`が同じハンドラを呼ぶ補助経路。Skillは`skills/orchestrator-local/SKILL.md`。

テストは偽Ollamaを用いたstdio MCP→worker→確認・保存、再接続、二重依頼、中止、失敗、パス制限、差分原子性を確認する。実モデルの接続確認は別に小さい1件を使い、実験用100件は再実行しない。

公式仕様：[デスクトップMCP](https://learn.chatgpt.com/docs/extend/mcp)、[SkillとMCP](https://developers.openai.com/plugins/concepts/skills)、[Ollama chat API](https://docs.ollama.com/api/chat)。

公開ソースのライセンスは[MIT](LICENSE)。動作確認の範囲は[VALIDATION.md](VALIDATION.md)、構成図は[DESIGN_JA.md](DESIGN_JA.md)を参照。

開発・実験資料は[OrchestratorMD](https://github.com/o0w0v/OrchestratorMD)へ分離しています。このアプリは[分離元のソース](https://github.com/o0w0v/OrchestratorMD/tree/d95881af188056933886d148f0bc0a5ea7c2e664/apps/orchestrator-local)をもとにしています。
