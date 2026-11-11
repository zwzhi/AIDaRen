param(
  [int]$Port = 5180,
  [int]$ApiPort = 8100
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$frontend = Join-Path $repo "frontend"
$logRoot = Join-Path $repo "artifacts\codex_ui_fixes\logs"
New-Item -ItemType Directory -Force $logRoot | Out-Null
$env:VITE_API_BASE = "http://127.0.0.1:$ApiPort"
Set-Location $frontend
$stdout = Join-Path $logRoot "isolated_frontend_$Port.stdout.log"
$stderr = Join-Path $logRoot "isolated_frontend_$Port.stderr.log"
$proc = Start-Process -FilePath "npm.cmd" -ArgumentList @("run","dev","--","--host","127.0.0.1","--port",$Port) -WorkingDirectory $frontend -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
Write-Output "PID=$($proc.Id)"
Write-Output "UI=http://127.0.0.1:$Port"
Write-Output "API=$env:VITE_API_BASE"
