# 普段はON/OFFだけ

依頼・資料の受け渡し・結果の受け取りはCodexの会話で行います。GUIの日常操作は、主画面の「ローカル分担」の切り替えだけです。初期状態はOFFです。

|切り替え|動作|
|---|---|
|ON|対応する作業で、必要に応じてPC内のGemmaへ分担する|
|OFF|新しいGemma作業を始めず、通常のCodexで処理する|

ONでも「今回は使わない」「この会話では使わない」という指示を優先します。CSV/JSONの整理・集計や短い報告文が対象で、雑談やプログラム開発まで自動分担する設定ではありません。

## 初回だけ設定する

1. [Windowsインストーラ](https://github.com/o0w0v/orchestrator-local/releases/download/v0.4.1/OrchestratorLocal-0.4.1-Setup.exe)を開きます。ZIPの手動展開は不要です。
2. セットアップの「次へ」で進み、検出したOllama・保存先を確認して「インストールする」を押します。
3. Codexを再起動し、新しい会話を開きます。
4. スタートメニューのOrchestrator Localを開き、使いたいときにONにしてください。

依頼例：「このJSONを集計して、一覧と短い報告文を作って」。資料と依頼はCodexの会話へ渡します。GUIへ作業内容を入力する必要はありません。

既存のOllamaと、この版のGemma4:26bを実行できるWindows x64 PCが必要です。Pythonは同梱し、Ollamaやモデルの自動ダウンロードはしません。自動接続先はCodexのMCP・Skillです。

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

新版のSetup.exeを開くだけで、現在のCodexに登録された旧版を検出します。旧版で登録解除する必要はありません。以前の成果物・履歴・モデル保存場所を引き継ぎ、接続と自動起動を新版に切り替えます。別の保存先へ自動移動はしません。

設定・Skill・自動起動のバックアップは、データ保存先のruntime/setup-backup-*へ残します。利用者が編集したSkillや独自の接続設定は上書きせず案内します。待機中・実行中の作業があれば、完了または中止してから更新してください。更新失敗時には変更した接続・設定・Skill・自動起動を復元します。

プログラムはLocalAppData/Programs/OrchestratorLocal/版番号へ、設定はLocalAppData/OrchestratorLocal/local-settings.jsonへ配置します。成果物と履歴は以前のデータ保存先に残ります。更新後はOFFから始まります。

ZIP版も利用できます。すべて展開してOrchestratorLocal.exeを開くと同じ案内が始まります。Runtime EXEと_internalを分離しないでください。

## ソースからの起動・配布版の検証

依存関係を導入した後、`.venv\Scripts\pythonw.exe start-gui.pyw`でGUIを起動できます。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.lock
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe packaging/build_windows.py
.\.venv\Scripts\python.exe packaging/smoke_windows.py dist/OrchestratorLocal --report validation-bundle.json
```

テストは一時設定・一時Startupフォルダと仮のHTTPモデルだけを使います。実際のユーザー登録や実モデルは使いません。配布版は未署名のWindows初期版です。
