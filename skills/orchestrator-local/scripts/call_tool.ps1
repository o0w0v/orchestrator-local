param(
    [Parameter(Mandatory=$true)][string]$Tool,
    [string]$ArgumentsFile,
    [string]$Config
)
$ErrorActionPreference='Stop'
if (-not $Config) {
    $Config = if ($env:ORCHESTRATOR_LOCAL_CONFIG) { $env:ORCHESTRATOR_LOCAL_CONFIG } else { Join-Path $env:LOCALAPPDATA 'OrchestratorLocal\local-settings.json' }
}
$resolvedConfig = [IO.Path]::GetFullPath($Config)
$launchPath = Join-Path ([IO.Path]::GetDirectoryName($resolvedConfig)) 'tool-launch.json'
if (-not (Test-Path -LiteralPath $launchPath)) { throw 'Update Orchestrator Local and complete setup.' }
$launcher = Get-Content -LiteralPath $launchPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($launcher.application -ne 'orchestrator-local' -or [IO.Path]::GetFullPath($launcher.config_path) -ne $resolvedConfig) { throw 'Connection settings do not match. Check setup.' }
$commandParts = @($launcher.command)
if ($commandParts.Count -lt 2 -or -not (Test-Path -LiteralPath $commandParts[0] -PathType Leaf)) { throw 'Runtime not found. Update Orchestrator Local.' }
$callArguments = @($commandParts | Select-Object -Skip 1) + @('--tool',$Tool)
if ($ArgumentsFile) { $callArguments += @('--arguments-file',[IO.Path]::GetFullPath($ArgumentsFile)) }
& $commandParts[0] @callArguments
exit $LASTEXITCODE
