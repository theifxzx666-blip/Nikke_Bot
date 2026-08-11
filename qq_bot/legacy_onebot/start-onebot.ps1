$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdmin)) {
    Write-Host "Requesting administrator permission for NIKKE control..."
    $arguments = @(
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "`"$PSCommandPath`""
    ) -join " "
    Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -Verb RunAs -WorkingDirectory $PSScriptRoot
    exit
}

$ProjectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")

$env:ONEBOT_API_URL = "http://127.0.0.1:3000"
$env:ADMIN_QQ_IDS = "1255348850"
$env:PYTHONUTF8 = "1"

$bundledPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if ($env:PYTHON_EXE -and (Test-Path -LiteralPath $env:PYTHON_EXE)) {
    $python = $env:PYTHON_EXE
} elseif (Test-Path -LiteralPath $bundledPython) {
    $python = $bundledPython
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $python = $pythonCommand.Source
    } else {
        throw "Python was not found. Run qq_bot\01-install-env.bat or set PYTHON_EXE."
    }
}

Set-Location -LiteralPath $ProjectRoot
$env:PYTHONPATH = $ProjectRoot
Write-Host "Guild War QQ Bot is running as administrator."
& $python -m guild_war_bot.onebot_http
