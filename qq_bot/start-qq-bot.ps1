$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $PSCommandPath
$ProjectRoot = Resolve-Path -LiteralPath (Join-Path $ScriptDir "..")
$AstrBotPluginDir = Join-Path $ProjectRoot "supports\AstrBot\data\plugins"
$BundledPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PluginSource = Join-Path $ScriptDir "astrbot_plugin_nikke_guild_bridge"
$BridgePort = if ($env:ASTRBOT_BRIDGE_PORT) { [int]$env:ASTRBOT_BRIDGE_PORT } else { 8793 }
$BridgeHost = if ($env:ASTRBOT_BRIDGE_HOST) { $env:ASTRBOT_BRIDGE_HOST } else { "127.0.0.1" }
$BridgeUrl = "http://$BridgeHost`:$BridgePort"
$AdminPort = if ($env:GUILD_WAR_ADMIN_PORT) { [int]$env:GUILD_WAR_ADMIN_PORT } else { 8788 }

function Find-Python {
    if ($env:PYTHON_EXE -and (Test-Path -LiteralPath $env:PYTHON_EXE)) {
        return @($env:PYTHON_EXE)
    }
    if (Test-Path -LiteralPath $BundledPython) {
        return @($BundledPython)
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @($python.Source)
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @($py.Source, "-3")
    }
    throw "Python was not found. Run 01-install-env.bat after installing Python, or set PYTHON_EXE."
}

function Test-HttpOk($url) {
    try {
        $response = Invoke-RestMethod -Uri $url -TimeoutSec 3
        return [bool]$response.ok
    } catch {
        return $false
    }
}

function Wait-HttpOk($url, $seconds = 15) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpOk $url) {
            return $true
        }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

function Start-ServiceWindow($title, $module, $extraArgs) {
    $pythonParts = @(Find-Python)
    $exe = $pythonParts[0]
    $pythonArgs = @()
    if ($pythonParts.Count -gt 1) {
        $pythonArgs += $pythonParts[1..($pythonParts.Count - 1)]
    }
    $args = @(
        "-NoExit",
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "& { `$env:PYTHONUTF8='1'; `$env:PYTHONPATH='$ProjectRoot'; Set-Location -LiteralPath '$ProjectRoot'; & '$exe' $($pythonArgs -join ' ') -m $module $extraArgs }"
    )
    Start-Process -FilePath "powershell.exe" -ArgumentList $args -WorkingDirectory $ProjectRoot -WindowStyle Normal | Out-Null
    Write-Host "Started: $title"
}

Write-Host "=== NIKKE QQ Bot Startup ==="
Write-Host "Project root: $ProjectRoot"
Write-Host ""

Write-Host "[1/5] Start local bridge service"
if (Test-HttpOk "$BridgeUrl/health") {
    Write-Host "Bridge already running: $BridgeUrl"
} else {
    Start-ServiceWindow "AstrBot bridge" "guild_war_bot.service_http" "--host $BridgeHost --port $BridgePort"
    if (-not (Wait-HttpOk "$BridgeUrl/health" 20)) {
        Write-Warning "Bridge did not answer yet. Check the opened bridge window."
    } else {
        Write-Host "Bridge ready: $BridgeUrl"
    }
}

Write-Host ""
Write-Host "[2/5] Start member admin web"
$adminUrl = "http://127.0.0.1:$AdminPort"
try {
    Invoke-WebRequest -UseBasicParsing -Uri $adminUrl -TimeoutSec 2 | Out-Null
    Write-Host "Admin web already running: $adminUrl"
} catch {
    Start-ServiceWindow "Member admin web" "guild_war_bot.admin_web" "--host 127.0.0.1 --port $AdminPort"
    Start-Sleep -Seconds 3
}
Start-Process $adminUrl | Out-Null

Write-Host ""
Write-Host "[3/5] AstrBot plugin"
Write-Host "Copy this folder into supports/AstrBot/data/plugins if it is not installed yet:"
Write-Host $PluginSource
Write-Host "Target plugin directory:"
Write-Host $AstrBotPluginDir
Write-Host "After copying, reload plugins in AstrBot WebUI."

Write-Host ""
Write-Host "[4/5] AstrBot and NapCat"
Write-Host "Start AstrBot, then configure OneBot v11 reverse WebSocket:"
Write-Host "  ws://127.0.0.1:6199/ws"
Write-Host "In NapCat WebUI, add a WebSocket client with the same URL."

Write-Host ""
Write-Host "[5/5] Quick command test"
$testBody = '{"text":"/help","sender_name":"local-test","sender_qq":"0","is_admin":true,"session_id":"startup-test"}'
try {
    $result = Invoke-RestMethod -Uri "$BridgeUrl/command" -Method Post -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($testBody)) -TimeoutSec 5
    if ($result.ok -and $result.handled) {
        Write-Host "Bridge command test passed."
    } else {
        Write-Warning "Bridge command test returned ok=$($result.ok), handled=$($result.handled)."
    }
} catch {
    Write-Warning "Bridge command test failed: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "Ready for group test:"
Write-Host "  /帮助"
Write-Host "  /查刀"
Write-Host "  /会战进度查询"
Write-Host ""
Write-Host "Keep the opened service windows running while the QQ bot is online."
