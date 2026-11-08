# 普段はON/OFFだけ

依頼・資料の受け渡し・結果の受け取りはCodexの会話で行います。GUIの日常操作は、主画面の「ローカル分担」の切り替えだけです。初期状態はOFFです。

|切り替え|動作|
|---|---|
|ON|対応する作業で、必要に応じてPC内のGemmaへ分担する|
|OFF|新しいGemma作業を始めず、通常のCodexで処理する|

ONでも「今回は使わない」「この会話では使わない」という指示を優先します。CSV/JSONの整理・集計や短い報告文が対象で、雑談やプログラム開発まで自動分担する設定ではありません。

## 初回だけ設定する

1. [Windows配布版](https://github.com/o0w0v/orchestrator-local/releases/tag/v0.3.0)のZIPを固定の場所へすべて展開し、OrchestratorLocal.exeを開きます。
2. 「初回設定」または「詳細」の設定で、保存先と既存のollama.exeを選び、「初期設定・接続登録」を押します。モデルを標準の場所に置いている場合、「モデルの場所」は空欄で構いません。
3. Codex側でMCP接続を再起動し、新しい会話を開きます。普段の画面に戻り、使いたいときにONにしてください。

Pythonは配布版に同梱しています。既存のOllamaと、この版のGemma4:26bを実行できるWindows x64 PCは必要です。Ollamaやモデルの自動ダウンロードはしません。自動接続登録先はCodexのMCP・Skillです。Runtime EXEと_internalも必要なので、起動ファイルだけ移動しないでください。

## 切り替えの効き方

ON/OFFは、その保存先を使う全会話で共通です。切り替えのたびにCodexを再起動する必要はありません。OFFは接続済みMCPにも反映し、新規受付と実行開始の両方でGemmaへの分担を止めます。開始済みの作業は継続し、待機中の作業はONに戻すまで保留します。進行中・待機中の件数がある場合は主画面に表示します。過去の結果の確認・保存はOFFでもできます。

この切り替えはGemmaへの分担許可で、Skill登録やMCP接続を削除する操作ではありません。CodexのSkill一覧からの無効化とは別です。Codex標準のSkill無効化設定は再起動後に反映します。[公式のSkill設定](https://learn.chatgpt.com/docs/build-skills#enable-or-disable-local-codex-skills)を参照してください。

画面を閉じても、実行サービスは待機します。ON/OFFの状態は保存されます。ログイン時のサービス自動起動を設定していても、OFFでは新しいGemma作業をしません。ON/OFFだけではOllamaや他のモデルを強制終了・解放しません。

## 必要なときだけ「詳細」

- 設定：初回接続、ログイン時の待機サービス起動、サービス起動・停止、接続登録解除、ログ表示。
- 履歴：最近200件、必要な作業の中止、確認・保存済み成果物の表示。
- 任意の入力補助：CSV/JSON/TXT/MDをinboxへコピーできます。同名の別内容は別名にし、既存資料を上書きしません。通常は会話で読める資料をそのまま依頼できます。

「AIの確認待ち」は候補の状態です。会話側が元資料で確認して保存すると「完了」になります。GUIに別の採点や自動採用は追加しません。

## 旧版からの更新

旧版でサービスを停止し、自動起動を解除し、接続登録を解除してから、新版を固定の場所へ展開します。ソース版では旧フォルダのREADMEの登録解除手順を使ってください。新版で同じ保存先を選ぶと、以前のジョブ・成果物を引き継げます。既存のSkillに利用者の変更がある場合は自動上書きしません。

0.3.0への初回移行時も、ローカル分担はOFFで始まります。旧版サービスが起動中の場合はONにせず、「詳細」で停止してから切り替えてください。設定や成果物を自動削除する操作はありません。

EXE版の設定は利用者のLocalAppData/OrchestratorLocal/local-settings.json、データは初回設定で選んだ場所に保存します。既存の保存先は自動変更しません。

## ソースからの起動・配布版の検証

依存関係を導入した後、`.venv\Scripts\pythonw.exe start-gui.pyw`でGUIを起動できます。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.lock
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe packaging/build_windows.py
.\.venv\Scripts\python.exe packaging/smoke_windows.py dist/OrchestratorLocal --report validation-bundle.json
```

テストは一時設定・一時Startupフォルダと仮のHTTPモデルだけを使います。実際のユーザー登録や実モデルは使いません。配布ZIPは未署名のWindows初期版です。
