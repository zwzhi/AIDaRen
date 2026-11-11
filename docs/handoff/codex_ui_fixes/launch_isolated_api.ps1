param(
  [int]$Port = 8100,
  [string]$DatabaseName = "printfilm_ui_fix_20261111_8a63de",
  [int]$RedisDb = 15
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$backend = Join-Path $repo "backend"
$envFile = Join-Path $backend ".env"
$mediaRoot = Join-Path $repo "artifacts\codex_ui_fixes\media"
$logRoot = Join-Path $repo "artifacts\codex_ui_fixes\logs"
New-Item -ItemType Directory -Force $mediaRoot, $logRoot | Out-Null

# Read local configuration in memory; never write credentials to this harness.
foreach ($line in Get-Content -LiteralPath $envFile) {
  if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
    [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim().Trim('"'), "Process")
  }
}

$env:DATABASE_URL = $env:DATABASE_URL -replace '/[^/]+$', "/$DatabaseName"
$env:DATABASE_URL_SYNC = $env:DATABASE_URL_SYNC -replace '/[^/]+$', "/$DatabaseName"
$env:REDIS_URL = $env:REDIS_URL -replace '/\d+$', "/$RedisDb"
$env:ARK_MOCK = "true"
$env:COMMERCIAL_MOCK_MODE = "true"
$env:COMMERCIAL_PAID_EXECUTION_ENABLED = "false"
$env:LOCAL_MEDIA_MOCK = "false"
$env:BILLING_ENABLED = "false"
$env:DATABASE_BOOTSTRAP_ENABLED = "true"
$env:COMMERCIAL_STORAGE_ROOT = $mediaRoot
$env:TASK_RUNTIME_ENABLED = "true"
$env:PYTHONPATH = $backend

Set-Location $backend
$stdout = Join-Path $logRoot "isolated_api_$Port.stdout.log"
$stderr = Join-Path $logRoot "isolated_api_$Port.stderr.log"
$python = Join-Path $backend ".venv\Scripts\python.exe"
$proc = Start-Process -FilePath $python -ArgumentList @("-m","uvicorn","app.main:app","--host","127.0.0.1","--port",$Port) -WorkingDirectory $backend -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
Write-Output "PID=$($proc.Id)"
Write-Output "API=http://127.0.0.1:$Port"
Write-Output "DATABASE=$DatabaseName"
Write-Output "REDIS_DB=$RedisDb"
Write-Output "MEDIA_ROOT=$mediaRoot"
