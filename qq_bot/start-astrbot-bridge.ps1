$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
Set-Location -LiteralPath $ProjectRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = $ProjectRoot
$BundledPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

$hostName = if ($env:ASTRBOT_BRIDGE_HOST) { $env:ASTRBOT_BRIDGE_HOST } else { "127.0.0.1" }
$port = if ($env:ASTRBOT_BRIDGE_PORT) { $env:ASTRBOT_BRIDGE_PORT } else { "8793" }

Write-Host "Starting NIKKE guild-war AstrBot bridge..."
Write-Host "Project: $ProjectRoot"
Write-Host "URL: http://$hostName`:$port"

if ($env:PYTHON_EXE -and (Test-Path -LiteralPath $env:PYTHON_EXE)) {
    & $env:PYTHON_EXE -m guild_war_bot.service_http --host $hostName --port $port
    exit $LASTEXITCODE
}

if (Test-Path -LiteralPath $BundledPython) {
    & $BundledPython -m guild_war_bot.service_http --host $hostName --port $port
    exit $LASTEXITCODE
}

$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    & $python.Source -m guild_war_bot.service_http --host $hostName --port $port
    exit $LASTEXITCODE
}

$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pyLauncher) {
    & $pyLauncher.Source -3 -m guild_war_bot.service_http --host $hostName --port $port
    exit $LASTEXITCODE
}

throw "Python was not found. Set PYTHON_EXE to a Python interpreter path."
