# 専用ツールが見えないWindows会話からの呼び出し

セットアップ済みなら、同梱Runtimeの同じツールを補助スクリプトから呼べる。利用者がコマンド操作するための画面ではなく、会話側のツール実行に使う。

このSkillの`scripts/call_tool.ps1`を、シェルから次の形式で呼ぶ。引数は作業フォルダのUTF-8 JSONファイルへ保存し、文字列をコマンドへ埋め込まない。

```powershell
& "<このSkillのパス>/scripts/call_tool.ps1" -Tool local_status
& "<このSkillのパス>/scripts/call_tool.ps1" -Tool route_task -ArgumentsFile "<元依頼と資料のJSONファイル>"
& "<このSkillのパス>/scripts/call_tool.ps1" -Tool start_code_job -ArgumentsFile "<引数JSONファイル>"
```

インストーラ版の設定は自動検出する。別の設定やソース版には`-Config "<local-settings.jsonの実パス>"`を渡す。スクリプト実行が制限される環境では、承認された通常のシェル実行方針に従い、PC全体の実行ポリシーは変更しない。

標準出力はJSON、失敗時は終了コード1。失敗を空の成功として扱わない。`start_code_job`の引数例：

```json
{"request_key":"依頼固有のキー","request":"合意した作業内容","file_paths":["index.html"],"inputs":{}}
```

`get_job`には`job_id`と`wait_seconds:25`を渡して待つ。候補を確認後に`finalize_job`を呼び、保存先の`source/`を会話側が反映・実行・テストする。補助経路も同じON/OFFとジョブDBを参照し、生成を開始し直さない。
