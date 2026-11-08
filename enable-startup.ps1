param([switch]$Disable)
$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$startupDir = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupDir 'Orchestrator Local.lnk'
$pythonwExe = Join-Path $projectDir '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonwExe)) { throw 'Python仮想環境がありません。セットアップを先に実行してください。' }
$arguments = '"{0}" --config "{1}" --background' -f (Join-Path $projectDir 'service_entry.py'),(Join-Path $projectDir 'local-settings.json')
$shell = New-Object -ComObject WScript.Shell
if (Test-Path -LiteralPath $shortcutPath) {
  $existing = $shell.CreateShortcut($shortcutPath)
  if ($existing.TargetPath -ne $pythonwExe -or $existing.Arguments -ne $arguments) { throw '同名の別ショートカットが存在します。自動上書きしません。' }
}
if ($Disable) {
  if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath }
  Write-Output 'Login auto-start disabled.'
  exit 0
}
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonwExe
$shortcut.Arguments = $arguments
$shortcut.WorkingDirectory = $projectDir
$shortcut.WindowStyle = 7
$shortcut.Description = 'Orchestrator Local job service; generation only when requested'
$shortcut.Save()
Write-Output $shortcutPath
