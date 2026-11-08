$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$python = Join-Path $projectDir '.venv\Scripts\python.exe'
$config = Join-Path $projectDir 'local-settings.json'
if (-not (Test-Path -LiteralPath $config)) { throw 'setup_local.py を先に実行してください。' }
$settings = Get-Content -LiteralPath $config -Raw | ConvertFrom-Json
$runtimeDir = Join-Path $settings.data_dir 'runtime'
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
$serviceEntry = Join-Path $projectDir 'service_entry.py'
$state = & $python $serviceEntry --config $config --status
if (($state | ConvertFrom-Json).ready) { Write-Output 'Orchestrator Local is already running.'; exit 0 }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$proc = Start-Process -FilePath $python -ArgumentList @(('"' + $serviceEntry + '"'),'--config',('"' + $config + '"')) -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir "service-$stamp.stdout.log") -RedirectStandardError (Join-Path $runtimeDir "service-$stamp.stderr.log")
for ($attempt = 0; $attempt -lt 30; $attempt++) {
  Start-Sleep -Milliseconds 200
  $state = & $python $serviceEntry --config $config --status
  if (($state | ConvertFrom-Json).ready) { Write-Output $state; exit 0 }
  if ($proc.HasExited) { throw "サービスが終了しました。$runtimeDir のログを確認してください。" }
}
throw 'サービスの起動確認がタイムアウトしました。'
