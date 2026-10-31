$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
$npmPath = if ($npmCommand) { $npmCommand.Source } else { 'C:\Program Files\nodejs\npm.cmd' }

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create the environment first: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r server/requirements.txt'
}
if (-not (Test-Path -LiteralPath $npmPath)) {
    throw 'Install Node.js LTS and open a new terminal.'
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'client\node_modules'))) {
    throw 'Install client dependencies first: cd client; npm ci'
}
$env:Path = (Split-Path -Parent $npmPath) + ';' + $env:Path
Push-Location (Join-Path $projectRoot 'client')
try {
    & $npmPath run build
    if ($LASTEXITCODE -ne 0) { throw 'Client build failed.' }
} finally { Pop-Location }

Write-Host 'LAN scenario: http://localhost:8011/?scenario-lan=1' -ForegroundColor Green
Write-Host 'Other players: http://<host-ip>:8011/?scenario-lan=1'
Write-Host 'Use a single worker. Stop the server with Ctrl+C.'
Push-Location $projectRoot
try {
    & $pythonPath -m uvicorn server.scenarios.lan:app --host 0.0.0.0 --port 8011 --workers 1 --ws-max-size 16384
} finally { Pop-Location }
