param(
    [Parameter(Position = 0)]
    [string]$Action = "menu",
    [string]$Mode = "background"
)

# ============================================================
# NIKKE QQ Bot 统一控制脚本 (nikke_ctl.ps1)
# 用法:
#   .\launcher\nikke_ctl.ps1 start         一键启动(后台模式,默认)
#   .\launcher\nikke_ctl.ps1 start -Mode fg 前台模式(弹窗,便于调试)
#   .\launcher\nikke_ctl.ps1 stop          一键停止
#   .\launcher\nikke_ctl.ps1 restart       一键重启
#   .\launcher\nikke_ctl.ps1 status        健康检查
#   .\launcher\nikke_ctl.ps1 logs          打开日志目录
#   .\launcher\nikke_ctl.ps1 menu          交互菜单
# 中文注释：本文件保存为 UTF-8 with BOM，供 Windows PowerShell 5.1 读取。
# ============================================================

$ErrorActionPreference = "Continue"

try {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [Console]::InputEncoding = $utf8NoBom
    [Console]::OutputEncoding = $utf8NoBom
    $OutputEncoding = $utf8NoBom
} catch {
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# ---------- 路径 ----------
$Script:ScriptDir = Split-Path -Parent $PSCommandPath
$Script:ProjectRoot = Resolve-Path -LiteralPath (Join-Path $Script:ScriptDir "..")
$Script:SupportsDir = Join-Path $Script:ProjectRoot "supports"
$Script:AstrBotDir = Join-Path $Script:SupportsDir "AstrBot"
$Script:AstrBotExe = Join-Path $Script:SupportsDir "astrbot-uv-env\Scripts\astrbot.exe"
$Script:TextProxyPy = Join-Path $Script:AstrBotDir "ollama_text_proxy.py"
$Script:BundledPython = Join-Path $Script:ProjectRoot ".venv\Scripts\python.exe"
$Script:LogsDir = Join-Path $Script:ProjectRoot "data\logs"
$Script:QqBotInstallBat = Join-Path $Script:ProjectRoot "qq_bot\01-install-env.bat"
$Script:QqBotDir = Join-Path $Script:ProjectRoot "qq_bot"

# ---------- 端口 ----------
$Script:PortAstrBot = 6185
$Script:PortNapCat = 6099
$Script:PortTextProxy = 11435
$Script:PortOneBot = 6199
$Script:PortBridge = 8793
$Script:PortAdmin = 8788
$Script:PortOllama = 11434

$Script:UrlAstrBot = "http://127.0.0.1:$($Script:PortAstrBot)"
$Script:UrlNapCat = "http://127.0.0.1:$($Script:PortNapCat)"
$Script:UrlBridge = "http://127.0.0.1:$($Script:PortBridge)"
$Script:UrlAdmin = "http://127.0.0.1:$($Script:PortAdmin)"
$Script:OneBotWs = "ws://127.0.0.1:$($Script:PortOneBot)/ws"

# 启动时用到的环境变量(桥接/后台默认端口)
$env:PYTHONPATH = $Script:ProjectRoot

# 便携版支持：项目内存在 wiki_data/wiki_cache 时优先使用（移动整个文件夹即可换数据源）
$Script:WikiDataDir = Join-Path $Script:ProjectRoot "wiki_data"
if (Test-Path -LiteralPath $Script:WikiDataDir) { $env:NIKKE_WIKI_DATA_DIR = $Script:WikiDataDir }
$Script:WikiCacheDir = Join-Path $Script:ProjectRoot "wiki_cache"
if (Test-Path -LiteralPath $Script:WikiCacheDir) { $env:NIKKE_WIKI_CACHE_DIR = $Script:WikiCacheDir }

$Host.UI.RawUI.WindowTitle = "NIKKE QQ Bot 控制台"

# ---------- 工具函数 ----------
function Write-Header {
    param([string]$Title)
    Clear-Host
    Write-Host ""
    Write-Host "============================================================"
    Write-Host "  $Title"
    Write-Host "============================================================"
    Write-Host ""
}

function Write-Step {
    param([string]$Text)
    Write-Host ""
    Write-Host "------------------------------------------------------------"
    Write-Host $Text
    Write-Host "------------------------------------------------------------"
}

function Pause-Menu {
    Write-Host ""
    [void](Read-Host "按 Enter 返回")
}

function Read-MenuChoice {
    param(
        [string]$Prompt,
        [string[]]$Allowed
    )
    while ($true) {
        $value = (Read-Host $Prompt).Trim().ToUpperInvariant()
        if ($Allowed -contains $value) {
            return $value
        }
        Write-Host "无效选择，请重新输入。" -ForegroundColor Yellow
    }
}

function Test-PortListening {
    param([int]$Port)
    try {
        return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    } catch {
        return $false
    }
}

function Wait-Port {
    param(
        [int]$Port,
        [int]$Seconds = 15
    )
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortListening $Port) {
            return $true
        }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

function Test-ProcessName {
    param([string]$Name)
    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($Name)
    return [bool](Get-Process -Name $baseName -ErrorAction SilentlyContinue)
}

function Find-NapCatExe {
    if ($env:NAPCAT_EXE -and (Test-Path -LiteralPath $env:NAPCAT_EXE)) {
        return $env:NAPCAT_EXE
    }
    $roots = @(
        (Join-Path $Script:SupportsDir "NapCat.Shell.Windows.OneKey"),
        $Script:SupportsDir
    )
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) {
            continue
        }
        try {
            $hit = Get-ChildItem -LiteralPath $root -Recurse -Filter "NapCatWinBootMain.exe" -ErrorAction SilentlyContinue |
                Select-Object -First 1 -ExpandProperty FullName
            if ($hit) {
                return $hit
            }
        } catch {
        }
    }
    return $null
}

function Find-PythonExe {
    if ($env:PYTHON_EXE -and (Test-Path -LiteralPath $env:PYTHON_EXE)) {
        return @($env:PYTHON_EXE)
    }
    if (Test-Path -LiteralPath $Script:BundledPython) {
        return @($Script:BundledPython)
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @($python.Source)
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @($py.Source, "-3")
    }
    return $null
}

function Test-HttpOk {
    param([string]$Url)
    try {
        $response = Invoke-RestMethod -Uri $Url -TimeoutSec 3
        if ($null -ne $response.ok) {
            return [bool]$response.ok
        }
        return $true
    } catch {
        return $false
    }
}

function Wait-HttpOk {
    param(
        [string]$Url,
        [int]$Seconds = 15
    )
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpOk $Url) {
            return $true
        }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

function Open-Url {
    param([string]$Url)
    try {
        Start-Process $Url | Out-Null
    } catch {
        Write-Host "WARN: 无法打开 $Url ：$($_.Exception.Message)" -ForegroundColor Yellow
    }
}

function Get-LogFilePath {
    param([string]$Name)
    if (-not (Test-Path -LiteralPath $Script:LogsDir)) {
        New-Item -ItemType Directory -Force -Path $Script:LogsDir | Out-Null
    }
    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    return Join-Path $Script:LogsDir "$Name`_$ts.log"
}

function Write-LogLine {
    param([string]$Text)
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Text"
    Write-Host $line
    if (-not (Test-Path -LiteralPath $Script:LogsDir)) {
        New-Item -ItemType Directory -Force -Path $Script:LogsDir | Out-Null
    }
    Add-Content -LiteralPath (Join-Path $Script:LogsDir "launcher.log") -Value $line -Encoding UTF8
}

# ---------- 停止函数 ----------
function Stop-PortProcess {
    param(
        [int]$Port,
        [string]$Name
    )
    if (-not (Test-PortListening $Port)) {
        Write-Host "SKIP  $Name ($Port) 未在运行"
        return
    }
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
        foreach ($c in $conns) {
            $procId = $c.OwningProcess
            if ($procId -gt 0) {
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                Write-Host "STOP  $Name ($Port) PID=$procId"
            }
        }
    } catch {
        Write-Host "WARN  $Name ($Port) 停止失败: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

function Stop-NapCatProcess {
    if (-not (Test-ProcessName "NapCatWinBootMain.exe")) {
        Write-Host "SKIP  NapCat 未在运行"
        return
    }
    Get-Process -Name "NapCatWinBootMain" -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        Write-Host "STOP  NapCat PID=$($_.Id)"
    }
}

function Invoke-Stop {
    Write-Step "停止全部服务"
    Stop-PortProcess $Script:PortAdmin "成员后台"
    Stop-PortProcess $Script:PortBridge "会战桥接"
    Stop-PortProcess $Script:PortTextProxy "文本代理"
    Stop-PortProcess $Script:PortAstrBot "AstrBot"
    Stop-NapCatProcess
    Write-Host ""
    Write-Host "全部停止完成。"
}

# ---------- 启动函数 ----------
function Find-OllamaExe {
    # 1) 环境变量显式指定
    if ($env:OLLAMA_EXE -and (Test-Path -LiteralPath $env:OLLAMA_EXE)) {
        return $env:OLLAMA_EXE
    }
    # 2) PATH 中的 ollama 命令
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
        return $cmd.Source
    }
    # 3) 常见安装路径
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
        (Join-Path $env:ProgramFiles "Ollama\ollama.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Ollama\ollama.exe"),
        (Join-Path $env:USERPROFILE "AppData\Local\Ollama\ollama.exe")
    )
    foreach ($p in $candidates) {
        if ($p -and (Test-Path -LiteralPath $p)) {
            return $p
        }
    }
    return $null
}

function Start-OllamaCheck {
    if (Test-PortListening $Script:PortOllama) {
        Write-Host "OK    Ollama 已在运行 (11434)"
        return $true
    }

    $auto = $env:NIKKE_BOT_AUTO_OLLAMA
    if ($auto -eq "0") {
        Write-Host "WARN  Ollama 未运行 (11434)，且已通过 NIKKE_BOT_AUTO_OLLAMA=0 关闭自动拉起。" -ForegroundColor Yellow
        Write-Host "      请手动启动 Ollama。" -ForegroundColor Yellow
        return $false
    }

    $ollamaExe = Find-OllamaExe
    if (-not $ollamaExe) {
        Write-Host "WARN  Ollama 未运行 (11434)，且未找到 ollama.exe。" -ForegroundColor Yellow
        Write-Host "      请手动启动 Ollama（可设置环境变量 OLLAMA_EXE 指向 ollama.exe 以启用自动拉起）。" -ForegroundColor Yellow
        return $false
    }

    Write-Host "START Ollama: $ollamaExe"
    try {
        Start-Process -FilePath $ollamaExe -WorkingDirectory (Split-Path -Parent $ollamaExe) | Out-Null
    } catch {
        Write-Host "WARN  Ollama 自动拉起失败: $($_.Exception.Message)" -ForegroundColor Yellow
        return $false
    }
    if (-not (Test-PortListening $Script:PortOllama)) {
        [void](Wait-Port $Script:PortOllama 20)
    }
    if (Test-PortListening $Script:PortOllama) {
        Write-Host "OK    Ollama 已自动拉起 (11434)"
        return $true
    }
    Write-Host "WARN  Ollama 自动拉起后仍未监听 11434，请检查其窗口或日志。" -ForegroundColor Yellow
    return $false
}

function Start-NapCat {
    if (Test-ProcessName "NapCatWinBootMain.exe") {
        Write-Host "OK    NapCat 已在运行"
        return
    }
    $napcatDir = Join-Path $Script:SupportsDir "NapCat.Shell.Windows.OneKey"
    $launcher = Join-Path $napcatDir "launcher-win10.bat"
    if (Test-Path -LiteralPath $launcher) {
        Write-Host "START NapCat 使用 launcher-win10.bat："
        Write-Host "      $launcher"
        Write-Host "      如弹出管理员授权请点“是”；QQ 登录窗口出现后请扫码。"
        Start-Process -FilePath $launcher -WorkingDirectory $napcatDir | Out-Null
        Start-QrCodeWatch
    } else {
        $napcat = Find-NapCatExe
        if (-not $napcat) {
            Write-Host "WARN  未找到 NapCatWinBootMain.exe" -ForegroundColor Yellow
            return
        }
        Start-Process -FilePath $napcat -WorkingDirectory (Split-Path -Parent $napcat) | Out-Null
        Write-Host "START NapCat: $napcat"
    }
    if (-not (Test-PortListening $Script:PortNapCat)) {
        [void](Wait-Port $Script:PortNapCat 25)
    }
    if (Test-PortListening $Script:PortNapCat) {
        Write-Host "OK    NapCat WebUI: $Script:UrlNapCat"
    } else {
        Write-Host "WARN  NapCat WebUI 未就绪，可能还在启动" -ForegroundColor Yellow
    }
}

function Start-QrCodeWatch {
    # 后台监控 NapCat 登录二维码：cache\qrcode.png 更新时自动打开，方便手机扫码
    if ($Mode -eq "fg") { return }
    $watchPy = Join-Path $Script:ScriptDir "qrcode_watch.py"
    if (-not (Test-Path -LiteralPath $watchPy)) {
        Write-Host "WARN  未找到二维码监控脚本: $watchPy" -ForegroundColor Yellow
        return
    }
    $pythonParts = @(Find-PythonExe)
    if (-not $pythonParts) {
        Write-Host "WARN  Python 未找到，跳过二维码监控" -ForegroundColor Yellow
        return
    }
    $exe = $pythonParts[0]
    $args = @()
    if ($pythonParts.Count -gt 1) {
        $args += $pythonParts[1..($pythonParts.Count - 1)]
    }
    $args += @($watchPy)
    Start-Process -FilePath $exe -ArgumentList $args -WorkingDirectory $Script:ScriptDir -WindowStyle Hidden | Out-Null
    Write-Host "START 二维码监控（qrcode.png 刷新时自动打开）"
}

function Start-TextProxy {
    if (Test-PortListening $Script:PortTextProxy) {
        Write-Host "OK    文本代理已在运行 (11435)"
        return
    }
    if (-not (Test-Path -LiteralPath $Script:TextProxyPy)) {
        Write-Host "WARN  未找到文本代理脚本: $Script:TextProxyPy" -ForegroundColor Yellow
        return
    }
    $pythonParts = @(Find-PythonExe)
    if (-not $pythonParts) {
        Write-Host "WARN  Python 未找到" -ForegroundColor Yellow
        return
    }
    $logOut = Get-LogFilePath "text_proxy"
    $logErr = $logOut -replace '\.log$', '.err.log'
    $exe = $pythonParts[0]
    $args = @()
    if ($pythonParts.Count -gt 1) {
        $args += $pythonParts[1..($pythonParts.Count - 1)]
    }
    $args += @($Script:TextProxyPy)
    if ($Mode -eq "fg") {
        $psArgs = @(
            "-NoExit", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-Command", "& { `$env:PYTHONUTF8='1'; & '$exe' $($args -join ' ') }"
        )
        Start-Process -FilePath "powershell.exe" -ArgumentList $psArgs -WorkingDirectory $Script:ProjectRoot -WindowStyle Normal | Out-Null
    } else {
        Start-Process -FilePath $exe -ArgumentList $args -WorkingDirectory $Script:ProjectRoot -WindowStyle Hidden -RedirectStandardOutput $logOut -RedirectStandardError $logErr | Out-Null
    }
    Write-Host "START 文本代理 (日志: $logOut)"
}

function Start-AstrBot {
    if (Test-PortListening $Script:PortAstrBot) {
        Write-Host "OK    AstrBot WebUI 已在运行: $Script:UrlAstrBot"
        return
    }
    # 优先便携版 .venv 内的 astrbot，其次独立的 astrbot-uv-env
    $astrbotExe = $Script:AstrBotExe
    $venvAstrbot = Join-Path $Script:ProjectRoot ".venv\Scripts\astrbot.exe"
    if (Test-Path -LiteralPath $venvAstrbot) {
        $astrbotExe = $venvAstrbot
    }
    if (-not (Test-Path -LiteralPath $astrbotExe)) {
        Write-Host "WARN  未找到 AstrBot: $astrbotExe" -ForegroundColor Yellow
        Write-Host "      请先执行 setup.bat 安装依赖（便携版）或安装 AstrBot。"
        return
    }
    $logOut = Get-LogFilePath "astrbot"
    $logErr = $logOut -replace '\.log$', '.err.log'
    if ($Mode -eq "fg") {
        $psArgs = @(
            "-NoExit", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-Command", "& { `$env:PYTHONUTF8='1'; & '$astrbotExe' run -p $($Script:PortAstrBot) }"
        )
        Start-Process -FilePath "powershell.exe" -ArgumentList $psArgs -WorkingDirectory $Script:AstrBotDir -WindowStyle Normal | Out-Null
    } else {
        Start-Process -FilePath $astrbotExe -ArgumentList @("run", "-p", "$($Script:PortAstrBot)") -WorkingDirectory $Script:AstrBotDir -WindowStyle Hidden -RedirectStandardOutput $logOut -RedirectStandardError $logErr | Out-Null
    }
    Write-Host "START AstrBot (日志: $logOut)"
    if (-not (Test-PortListening $Script:PortAstrBot)) {
        [void](Wait-Port $Script:PortAstrBot 40)
    }
    if (Test-PortListening $Script:PortAstrBot) {
        Write-Host "OK    AstrBot WebUI: $Script:UrlAstrBot"
    } else {
        Write-Host "WARN  AstrBot 暂未监听 6185，请查看日志" -ForegroundColor Yellow
    }
}

function Start-Bridge {
    if (Test-PortListening $Script:PortBridge) {
        Write-Host "OK    会战桥接已在运行: $Script:UrlBridge"
        return
    }
    $pythonParts = @(Find-PythonExe)
    if (-not $pythonParts) {
        Write-Host "WARN  Python 未找到" -ForegroundColor Yellow
        return
    }
    $logOut = Get-LogFilePath "bridge"
    $logErr = $logOut -replace '\.log$', '.err.log'
    $exe = $pythonParts[0]
    $args = @()
    if ($pythonParts.Count -gt 1) {
        $args += $pythonParts[1..($pythonParts.Count - 1)]
    }
    $args += @("-m", "guild_war_bot.service_http", "--host", "127.0.0.1", "--port", "$($Script:PortBridge)")
    if ($Mode -eq "fg") {
        $psArgs = @(
            "-NoExit", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-Command", "& { `$env:PYTHONUTF8='1'; `$env:PYTHONPATH='$Script:ProjectRoot'; Set-Location '$Script:ProjectRoot'; & '$exe' $($args -join ' ') }"
        )
        Start-Process -FilePath "powershell.exe" -ArgumentList $psArgs -WorkingDirectory $Script:ProjectRoot -WindowStyle Normal | Out-Null
    } else {
        Start-Process -FilePath $exe -ArgumentList $args -WorkingDirectory $Script:ProjectRoot -WindowStyle Hidden -RedirectStandardOutput $logOut -RedirectStandardError $logErr | Out-Null
    }
    Write-Host "START 会战桥接 (日志: $logOut)"
    [void](Wait-HttpOk "$Script:UrlBridge/health" 20)
    if (Test-HttpOk "$Script:UrlBridge/health") {
        Write-Host "OK    桥接健康: $Script:UrlBridge/health"
    } else {
        Write-Host "WARN  桥接未就绪，请查看日志" -ForegroundColor Yellow
    }
}

function Start-Admin {
    if (Test-PortListening $Script:PortAdmin) {
        Write-Host "OK    成员后台已在运行: $Script:UrlAdmin"
        return
    }
    $pythonParts = @(Find-PythonExe)
    if (-not $pythonParts) {
        Write-Host "WARN  Python 未找到" -ForegroundColor Yellow
        return
    }
    $logOut = Get-LogFilePath "admin"
    $logErr = $logOut -replace '\.log$', '.err.log'
    $exe = $pythonParts[0]
    $args = @()
    if ($pythonParts.Count -gt 1) {
        $args += $pythonParts[1..($pythonParts.Count - 1)]
    }
    $args += @("-m", "guild_war_bot.admin_web", "--host", "127.0.0.1", "--port", "$($Script:PortAdmin)")
    if ($Mode -eq "fg") {
        $psArgs = @(
            "-NoExit", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-Command", "& { `$env:PYTHONUTF8='1'; `$env:PYTHONPATH='$Script:ProjectRoot'; Set-Location '$Script:ProjectRoot'; & '$exe' $($args -join ' ') }"
        )
        Start-Process -FilePath "powershell.exe" -ArgumentList $psArgs -WorkingDirectory $Script:ProjectRoot -WindowStyle Normal | Out-Null
    } else {
        Start-Process -FilePath $exe -ArgumentList $args -WorkingDirectory $Script:ProjectRoot -WindowStyle Hidden -RedirectStandardOutput $logOut -RedirectStandardError $logErr | Out-Null
    }
    Write-Host "START 成员后台 (日志: $logOut)"
    Start-Sleep -Seconds 3
    if (Test-PortListening $Script:PortAdmin) {
        Write-Host "OK    成员后台: $Script:UrlAdmin"
    } else {
        Write-Host "WARN  成员后台未就绪" -ForegroundColor Yellow
    }
}

function Start-Watchdog {
    # 链路守护：掉线检测 / 自动重连 / 钉钉告警（pythonw 后台无窗口运行）
    $watchPy = Join-Path $Script:ProjectRoot "watchdog.py"
    if (-not (Test-Path -LiteralPath $watchPy)) {
        Write-Host "WARN  未找到 watchdog: $watchPy" -ForegroundColor Yellow
        return
    }
    try {
        $procs = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue
        if ($procs | Where-Object { $_.CommandLine -and $_.CommandLine.Contains("watchdog.py") }) {
            Write-Host "OK    watchdog 已在运行"
            return
        }
    } catch {
    }
    $pythonw = Join-Path $Script:ProjectRoot ".venv\Scripts\pythonw.exe"
    if (-not (Test-Path -LiteralPath $pythonw)) {
        Write-Host "WARN  未找到 pythonw.exe: $pythonw" -ForegroundColor Yellow
        return
    }
    Start-Process -FilePath $pythonw -ArgumentList $watchPy -WorkingDirectory $Script:ProjectRoot -WindowStyle Hidden | Out-Null
    Write-Host "START watchdog（后台守护，日志: $(Join-Path $Script:ProjectRoot 'watchdog.log')）"
}

function Invoke-Start {
    Write-Step "一键启动 (模式: $Mode)"
    Write-LogLine "=== 启动流程开始 (mode=$Mode) ==="
    Write-Step "1/5 启动 NapCat（launcher-win10，扫码登录）"
    Start-NapCat
    Write-Step "2/5 启动 AstrBot"
    Start-AstrBot
    Write-Step "3/5 启动会战本地服务"
    Start-Bridge
    Start-Admin
    Write-Step "4/5 启动链路守护 watchdog"
    Start-Watchdog
    Write-Step "5/5 健康检查"
    Invoke-Health
    Write-Host ""
    Write-Host "自动打开管理后台：AstrBot / 成员后台 / 桥接健康页"
    Open-Url $Script:UrlAstrBot
    Open-Url $Script:UrlAdmin
    Open-Url "$Script:UrlBridge/health"
    Write-LogLine "=== 启动流程结束 ==="
}

function Invoke-Restart {
    Write-Step "重启全部服务"
    Invoke-Stop
    Start-Sleep -Seconds 2
    $script:Mode = "background"
    Invoke-Start
}

# ---------- 健康检查 ----------
function Write-PortStatus {
    param(
        [int]$Port,
        [string]$Name
    )
    if (Test-PortListening $Port) {
        Write-Host "OK   $Name ($Port)"
    } else {
        Write-Host "WARN $Name ($Port) 未监听" -ForegroundColor Yellow
    }
}

function Write-ProcessStatus {
    param(
        [string]$ProcessName,
        [string]$Name
    )
    if (Test-ProcessName $ProcessName) {
        Write-Host "OK   $Name 进程已运行"
    } else {
        Write-Host "WARN $Name 未检测到进程" -ForegroundColor Yellow
    }
}

function Invoke-Health {
    Write-Host ""
    Write-Host "[端口状态]"
    Write-PortStatus $Script:PortAstrBot "AstrBot WebUI"
    Write-PortStatus $Script:PortOneBot "OneBot 反向 WS"
    Write-PortStatus $Script:PortNapCat "NapCat WebUI"
    Write-PortStatus $Script:PortBridge "会战桥接服务"
    Write-PortStatus $Script:PortAdmin "成员后台"

    Write-Host ""
    Write-Host "[进程状态]"
    Write-ProcessStatus "NapCatWinBootMain.exe" "NapCat"

    Write-Host ""
    Write-Host "[桥接服务健康检查]"
    try {
        $result = Invoke-RestMethod -Uri "$Script:UrlBridge/health" -TimeoutSec 3
        if ($result.ok) {
            Write-Host "OK   $Script:UrlBridge/health"
        } else {
            Write-Host "WARN bridge 返回异常" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "WARN bridge health 失败: $($_.Exception.Message)" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "[OneBot 连接提示]"
    try {
        $connection = Get-NetTCPConnection -LocalPort $Script:PortOneBot -State Established -ErrorAction SilentlyContinue
        if ($connection) {
            Write-Host "OK   NapCat/AstrBot 已有 WebSocket 连接。"
        } else {
            Write-Host "WARN 6199 暂无 Established 连接，请检查 NapCat WebSocket 客户端。" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "WARN 无法读取 OneBot 连接状态" -ForegroundColor Yellow
    }
}

# ---------- 后台页面 ----------
function Invoke-OpenAdmin {
    Write-Host "打开后台页面..."
    Open-Url $Script:UrlAstrBot
    Open-Url $Script:UrlNapCat
    Open-Url "$Script:UrlBridge/health"
    Open-Url $Script:UrlAdmin
    Write-Host "已打开："
    Write-Host "  AstrBot WebUI：$Script:UrlAstrBot"
    Write-Host "  NapCat WebUI：$Script:UrlNapCat"
    Write-Host "  桥接健康检查：$Script:UrlBridge/health"
    Write-Host "  成员后台：$Script:UrlAdmin"
}

function Invoke-OpenLogs {
    if (-not (Test-Path -LiteralPath $Script:LogsDir)) {
        New-Item -ItemType Directory -Force -Path $Script:LogsDir | Out-Null
    }
    Start-Process explorer.exe -ArgumentList $Script:LogsDir | Out-Null
    Write-Host "已打开日志目录：$Script:LogsDir"
}

# ---------- 交互菜单 ----------
function Show-Menu {
    while ($true) {
        Write-Header "NIKKE QQ Bot 控制台"
        Write-Host "OneBot 反向 WebSocket 地址：$Script:OneBotWs"
        Write-Host ""
        Write-Host "日常操作："
        Write-Host "  [1] 一键启动（后台模式，窗口最小化，日志进 data/logs）"
        Write-Host "  [2] 一键启动（前台模式，弹窗便于调试）"
        Write-Host "  [3] 一键停止全部服务"
        Write-Host "  [4] 一键重启"
        Write-Host "  [5] 健康检查"
        Write-Host ""
        Write-Host "辅助："
        Write-Host "  [6] 打开后台页面（AstrBot/NapCat/桥接/成员后台）"
        Write-Host "  [7] 打开日志目录"
        Write-Host "  [8] 安装/修复 Python 依赖"
        Write-Host ""
        Write-Host "  [0] 退出"
        Write-Host ""
        $choice = Read-MenuChoice "请选择功能" @("0", "1", "2", "3", "4", "5", "6", "7", "8")

        switch ($choice) {
            "0" {
                Write-Host "已退出控制台。"
                return
            }
            "1" {
                $script:Mode = "background"
                Invoke-Start
                Pause-Menu
            }
            "2" {
                $script:Mode = "fg"
                Invoke-Start
                Write-Host "前台模式：相关服务窗口已弹出，请保持窗口打开。"
                Pause-Menu
            }
            "3" {
                Invoke-Stop
                Pause-Menu
            }
            "4" {
                Invoke-Restart
                Pause-Menu
            }
            "5" {
                Write-Step "健康检查"
                Invoke-Health
                Pause-Menu
            }
            "6" {
                Invoke-OpenAdmin
                Pause-Menu
            }
            "7" {
                Invoke-OpenLogs
                Pause-Menu
            }
            "8" {
                Write-Step "安装/修复 Python 依赖"
                if (Test-Path -LiteralPath $Script:QqBotInstallBat) {
                    Start-Process -FilePath $Script:QqBotInstallBat -WorkingDirectory $Script:QqBotDir -Wait
                } else {
                    Write-Host "未找到安装脚本：$Script:QqBotInstallBat" -ForegroundColor Yellow
                }
                Pause-Menu
            }
        }
    }
}

# ---------- 入口 ----------
switch ($Action.ToLowerInvariant()) {
    "start" {
        if ($Mode -eq "fg") { $script:Mode = "fg" } else { $script:Mode = "background" }
        Invoke-Start
    }
    "stop" { Invoke-Stop }
    "restart" { Invoke-Restart }
    "status" {
        Write-Step "健康检查"
        Invoke-Health
    }
    "logs" { Invoke-OpenLogs }
    "admin" { Invoke-OpenAdmin }
    "menu" { Show-Menu }
    default {
        Write-Host "未知动作: $Action"
        Write-Host "可用: start | stop | restart | status | logs | admin | menu"
    }
}
