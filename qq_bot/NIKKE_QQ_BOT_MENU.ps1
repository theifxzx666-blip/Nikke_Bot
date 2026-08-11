param(
    [string]$Mode = ""
)

# 中文注释：这个 PowerShell 脚本负责真正的中文菜单和启动逻辑。
# 中文注释：外层 .bat 只做 ASCII 启动壳，避免 cmd.exe 直接解析中文导致菜单行被当成命令执行。
# 中文注释：本文件建议保存为 UTF-8 with BOM，方便 Windows PowerShell 5.1 正确读取中文。

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

$Script:ScriptDir = Split-Path -Parent $PSCommandPath
$Script:ProjectRoot = Resolve-Path -LiteralPath (Join-Path $Script:ScriptDir "..")
$Script:BotRoot = $Script:ProjectRoot
$Script:SupportsDir = Join-Path $Script:BotRoot "supports"
$Script:AstrBotDir = Join-Path $Script:SupportsDir "AstrBot"
$Script:AstrBotBat = Join-Path $Script:AstrBotDir "start-astrbot.bat"
$Script:BridgeBat = Join-Path $Script:ScriptDir "start-astrbot-bridge.bat"
$Script:QqBotStartBat = Join-Path $Script:ScriptDir "02-start-qq-bot.bat"
$Script:QqBotInstallBat = Join-Path $Script:ScriptDir "01-install-env.bat"
$Script:DependenciesDir = $Script:SupportsDir

$Script:AstrBotUrl = "http://127.0.0.1:6185"
$Script:NapCatUrl = "http://127.0.0.1:6099"
$Script:BridgeUrl = "http://127.0.0.1:8793"
$Script:AdminUrl = "http://127.0.0.1:8788"
$Script:OneBotWs = "ws://127.0.0.1:6199/ws"

$Host.UI.RawUI.WindowTitle = "NIKKE QQ Bot 启动总控"

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

    Write-Host "等待端口 $Port 就绪，最多 $Seconds 秒..."
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortListening $Port) {
            Write-Host "OK: 端口 $Port 已监听"
            return $true
        }
        Start-Sleep -Milliseconds 700
    }
    Write-Host "WARN: 端口 $Port 暂未监听" -ForegroundColor Yellow
    return $false
}

function Test-ProcessName {
    param([string]$Name)
    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($Name)
    return [bool](Get-Process -Name $baseName -ErrorAction SilentlyContinue)
}

function Open-Url {
    param([string]$Url)
    try {
        Start-Process $Url | Out-Null
    } catch {
        Write-Host "WARN: 无法打开 $Url ：$($_.Exception.Message)" -ForegroundColor Yellow
    }
}

function Find-NapCatExe {
    if ($env:NAPCAT_EXE -and (Test-Path -LiteralPath $env:NAPCAT_EXE)) {
        return $env:NAPCAT_EXE
    }

    $roots = @(
        $Script:DependenciesDir,
        (Join-Path $env:USERPROFILE "Downloads")
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

function Start-AstrBotCore {
    if (-not (Test-Path -LiteralPath $Script:AstrBotBat)) {
        Write-Host "未找到 AstrBot 启动脚本：" -ForegroundColor Yellow
        Write-Host "  $Script:AstrBotBat"
        return
    }

    if (Test-PortListening 6185) {
        Write-Host "AstrBot WebUI 已在监听：$Script:AstrBotUrl"
    } else {
        Write-Host "正在启动 AstrBot，请等待 WebUI 出现..."
        Start-Process -FilePath $Script:AstrBotBat -WorkingDirectory $Script:AstrBotDir | Out-Null
        [void](Wait-Port 6185 35)
    }

    if (Test-PortListening 11435) {
        Write-Host "本地模型代理已在监听：http://127.0.0.1:11435"
    } else {
        Write-Host "提醒：11435 本地模型代理暂未监听。AstrBot 可启动，但 LLM 回复可能失败。" -ForegroundColor Yellow
    }

    if (Test-PortListening 6199) {
        Write-Host "OneBot 反向 WebSocket 端口已在监听：6199"
    } else {
        Write-Host "提醒：6199 尚未监听，稍后可重新做健康检查。" -ForegroundColor Yellow
    }
}

function Start-NapCatCore {
    if (Test-ProcessName "NapCatWinBootMain.exe") {
        Write-Host "NapCat 已在运行。"
    } else {
        $napcat = Find-NapCatExe
        if ($napcat) {
            Start-Process -FilePath $napcat -WorkingDirectory (Split-Path -Parent $napcat) | Out-Null
            Write-Host "已找到并启动 NapCat："
            Write-Host "  $napcat"
        } else {
            Write-Host "未自动找到 NapCatWinBootMain.exe。" -ForegroundColor Yellow
            Write-Host "请手动打开 NapCat，并确认 WebSocket 客户端地址："
            Write-Host "  $Script:OneBotWs"
            return
        }
    }

    if (-not (Test-PortListening 6099)) {
        [void](Wait-Port 6099 12)
    }
    if (Test-PortListening 6099) {
        Write-Host "NapCat WebUI 已在监听：$Script:NapCatUrl"
    } else {
        Write-Host "提醒：NapCat WebUI 6099 暂未监听，可能还在启动中。" -ForegroundColor Yellow
    }
}

function Start-BridgeCore {
    if (-not (Test-Path -LiteralPath $Script:BridgeBat)) {
        Write-Host "未找到桥接启动脚本：" -ForegroundColor Yellow
        Write-Host "  $Script:BridgeBat"
        return
    }

    if (Test-PortListening 8793) {
        Write-Host "桥接服务已经在监听：$Script:BridgeUrl"
    } else {
        Start-Process -FilePath $Script:BridgeBat -WorkingDirectory $Script:ScriptDir | Out-Null
        [void](Wait-Port 8793 15)
    }
}

function Start-LocalServicesCore {
    if (-not (Test-Path -LiteralPath $Script:QqBotStartBat)) {
        Write-Host "未找到本地服务启动脚本：" -ForegroundColor Yellow
        Write-Host "  $Script:QqBotStartBat"
        return
    }

    if (Test-PortListening 8793) {
        Write-Host "桥接服务已在监听：$Script:BridgeUrl"
    } else {
        Write-Host "正在启动桥接服务和成员后台..."
        Start-Process -FilePath $Script:QqBotStartBat -WorkingDirectory $Script:ScriptDir | Out-Null
        [void](Wait-Port 8793 25)
    }

    if (Test-PortListening 8788) {
        Write-Host "成员后台已在监听：$Script:AdminUrl"
    } else {
        Write-Host "提醒：8788 成员后台暂未监听。可查看新打开的本地服务窗口。" -ForegroundColor Yellow
    }
}

function Open-AllAdminPages {
    Open-Url $Script:AstrBotUrl
    Open-Url $Script:NapCatUrl
    Open-Url "$Script:BridgeUrl/health"
    Open-Url $Script:AdminUrl
    Write-Host "已打开："
    Write-Host "  AstrBot WebUI：$Script:AstrBotUrl"
    Write-Host "  NapCat WebUI：$Script:NapCatUrl"
    Write-Host "  桥接健康检查：$Script:BridgeUrl/health"
    Write-Host "  成员后台：$Script:AdminUrl"
}

function Write-PortStatus {
    param(
        [int]$Port,
        [string]$Name
    )
    if (Test-PortListening $Port) {
        Write-Host "OK   $Name：$Port 正在监听"
    } else {
        Write-Host "WARN $Name：$Port 未监听" -ForegroundColor Yellow
    }
}

function Write-ProcessStatus {
    param(
        [string]$ProcessName,
        [string]$Name
    )
    if (Test-ProcessName $ProcessName) {
        Write-Host "OK   $Name：进程已运行"
    } else {
        Write-Host "WARN $Name：未检测到进程" -ForegroundColor Yellow
    }
}

function Invoke-HealthCore {
    Write-Host ""
    Write-Host "[端口状态]"
    Write-PortStatus 6185 "AstrBot WebUI"
    Write-PortStatus 6199 "OneBot 反向 WebSocket"
    Write-PortStatus 11435 "本地模型代理"
    Write-PortStatus 6099 "NapCat WebUI"
    Write-PortStatus 8793 "会战桥接服务"
    Write-PortStatus 8788 "成员后台"

    Write-Host ""
    Write-Host "[进程状态]"
    Write-ProcessStatus "NapCatWinBootMain.exe" "NapCat"
    Write-ProcessStatus "ollama.exe" "Ollama"

    Write-Host ""
    Write-Host "[桥接服务健康检查]"
    try {
        $result = Invoke-RestMethod -Uri "$Script:BridgeUrl/health" -TimeoutSec 3
        if ($result.ok) {
            Write-Host "OK: $Script:BridgeUrl/health"
        } else {
            Write-Host "WARN: bridge returned but ok is not true" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "WARN: bridge health failed: $($_.Exception.Message)" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "[OneBot 连接提示]"
    try {
        $connection = Get-NetTCPConnection -LocalPort 6199 -State Established -ErrorAction SilentlyContinue
        if ($connection) {
            Write-Host "OK: NapCat/AstrBot 已有 WebSocket 连接。"
        } else {
            Write-Host "WARN: 6199 暂无 Established 连接，请检查 NapCat WebSocket 客户端。" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "WARN: 无法读取 OneBot 连接状态：$($_.Exception.Message)" -ForegroundColor Yellow
    }
}

function Invoke-FullStart {
    Write-Step "1/4 启动 AstrBot WebUI 和本地模型代理"
    Start-AstrBotCore

    Write-Step "2/4 启动 NapCat"
    Start-NapCatCore

    Write-Step "3/4 启动会战本地服务"
    Start-LocalServicesCore

    Write-Step "4/4 健康检查"
    Invoke-HealthCore
}

function Show-GuidedStart {
    Write-Header "NIKKE QQ Bot 分步引导启动"
    Write-Host "这个流程只负责启动，不安装依赖；首次部署或修复环境请回主菜单选 [5] 高级维护。"
    Write-Host "每一步可以选择跳过，适合你已经手动打开了某个服务的情况。"
    Write-Host ""

    if ((Read-MenuChoice "步骤 1：启动 AstrBot WebUI 和本地模型代理？[Y/N]" @("Y", "N")) -eq "Y") {
        Write-Step "1/4 启动 AstrBot WebUI 和本地模型代理"
        Start-AstrBotCore
    }
    if ((Read-MenuChoice "步骤 2：启动 NapCat？[Y/N]" @("Y", "N")) -eq "Y") {
        Write-Step "2/4 启动 NapCat"
        Start-NapCatCore
    }
    if ((Read-MenuChoice "步骤 3：启动会战桥接服务和成员后台？[Y/N]" @("Y", "N")) -eq "Y") {
        Write-Step "3/4 启动会战本地服务"
        Start-LocalServicesCore
    }
    if ((Read-MenuChoice "步骤 4：做一次健康检查？[Y/N]" @("Y", "N")) -eq "Y") {
        Write-Step "4/4 健康检查"
        Invoke-HealthCore
    }

    Write-Host ""
    Write-Host "分步启动流程已结束。请保持需要在线的服务窗口不要关闭。"
    Write-Host "如果 QQ 群没有响应，请在 NapCat WebUI 确认 WebSocket 客户端地址："
    Write-Host "  $Script:OneBotWs"
    Pause-Menu
}

function Show-AdminMenu {
    while ($true) {
        Write-Header "管理后台"
        Write-Host "这里优先解决“打开哪个后台”的问题；需要的本地服务会自动尝试拉起。"
        Write-Host ""
        Write-Host "  [1] AstrBot WebUI：人格 / LLM / 插件 / 平台配置"
        Write-Host "  [2] NapCat WebUI：QQ 登录 / OneBot WebSocket 配置"
        Write-Host "  [3] 会战成员后台：成员、出刀、数据管理"
        Write-Host "  [4] 会战桥接健康页：检查 AstrBot 插件桥接状态"
        Write-Host "  [5] 打开全部常用后台"
        Write-Host "  [0] 返回主菜单"
        Write-Host ""
        $choice = Read-MenuChoice "请选择后台" @("0", "1", "2", "3", "4", "5")

        switch ($choice) {
            "0" { return }
            "1" {
                Write-Step "启动并打开 AstrBot WebUI"
                Start-AstrBotCore
                Open-Url $Script:AstrBotUrl
                Write-Host "已打开 AstrBot WebUI：$Script:AstrBotUrl"
                Pause-Menu
            }
            "2" {
                Write-Step "启动并打开 NapCat WebUI"
                Start-NapCatCore
                Open-Url $Script:NapCatUrl
                Write-Host "NapCat WebUI：$Script:NapCatUrl"
                Write-Host "请确认 WebSocket 客户端地址为："
                Write-Host "  $Script:OneBotWs"
                Pause-Menu
            }
            "3" {
                Write-Step "启动并打开会战成员后台"
                Start-LocalServicesCore
                Open-Url $Script:AdminUrl
                Write-Host "已打开成员后台：$Script:AdminUrl"
                Pause-Menu
            }
            "4" {
                Write-Step "启动并打开会战桥接健康页"
                Start-BridgeCore
                Open-Url "$Script:BridgeUrl/health"
                Write-Host "已打开桥接健康页：$Script:BridgeUrl/health"
                Pause-Menu
            }
            "5" {
                Write-Step "启动并打开全部常用后台"
                Start-AstrBotCore
                Start-NapCatCore
                Start-LocalServicesCore
                Open-AllAdminPages
                Pause-Menu
            }
        }
    }
}

function Show-AdvancedMenu {
    while ($true) {
        Write-Header "高级维护"
        Write-Host "平时上线优先回主菜单选 [1]；这里放低频维护项，避免主菜单太挤。"
        Write-Host ""
        Write-Host "  [1] 只启动 AstrBot WebUI 和本地模型代理"
        Write-Host "  [2] 只启动 NapCat"
        Write-Host "  [3] 只启动会战本地服务：桥接服务 + 成员后台"
        Write-Host "  [4] 只启动 AstrBot 会战桥接服务"
        Write-Host "  [5] 首次安装/修复 Python 依赖"
        Write-Host "  [6] 查看启动提示"
        Write-Host "  [0] 返回主菜单"
        Write-Host ""
        $choice = Read-MenuChoice "请选择维护项" @("0", "1", "2", "3", "4", "5", "6")

        switch ($choice) {
            "0" { return }
            "1" {
                Write-Step "启动 AstrBot WebUI 和本地模型代理"
                Start-AstrBotCore
                Pause-Menu
            }
            "2" {
                Write-Step "启动 NapCat"
                Start-NapCatCore
                Pause-Menu
            }
            "3" {
                Write-Step "启动会战本地服务：桥接服务 + 成员后台"
                Start-LocalServicesCore
                Pause-Menu
            }
            "4" {
                Write-Step "启动 AstrBot 会战桥接服务"
                Start-BridgeCore
                Pause-Menu
            }
            "5" {
                Write-Step "首次安装/修复 Python 依赖"
                if (Test-Path -LiteralPath $Script:QqBotInstallBat) {
                    Start-Process -FilePath $Script:QqBotInstallBat -WorkingDirectory $Script:ScriptDir -Wait
                } else {
                    Write-Host "未找到安装脚本：" -ForegroundColor Yellow
                    Write-Host "  $Script:QqBotInstallBat"
                }
                Pause-Menu
            }
            "6" {
                Show-Help
            }
        }
    }
}

function Show-Help {
    Write-Header "启动提示"
    Write-Host "1. 日常上线：主菜单选 [1]，它会按顺序启动 AstrBot、NapCat、本地桥接和成员后台。"
    Write-Host "2. 想自己确认每一步：主菜单选 [2]，每一步都会询问是否继续。"
    Write-Host "3. 找后台：主菜单选 [3]，再选择 AstrBot、NapCat、成员后台或桥接健康页。"
    Write-Host "4. 首次部署或 Python 依赖坏了：主菜单选 [5]，再选 [5] 修复依赖。"
    Write-Host "5. NapCat 必须登录 QQ 小号，并配置 WebSocket 客户端："
    Write-Host "     $Script:OneBotWs"
    Write-Host "6. AstrBot WebUI："
    Write-Host "     $Script:AstrBotUrl"
    Write-Host "7. NapCat WebUI："
    Write-Host "     $Script:NapCatUrl"
    Write-Host "8. 本地会战桥接服务默认地址："
    Write-Host "     $Script:BridgeUrl"
    Write-Host ""
    Write-Host "乱码处理："
    Write-Host "  .bat 只保留 ASCII 启动壳，中文菜单由 PowerShell 打印。"
    Write-Host "  如果旧 cmd 窗口仍乱码，请关闭窗口后重新双击根目录启动入口。"
    Pause-Menu
}

function Show-MainMenu {
    while ($true) {
        Write-Header "NIKKE QQ Bot 启动总控"
        Write-Host "日常推荐：先确认 NapCat 已登录 QQ 小号，再选择 [1] 日常上线。"
        Write-Host ""
        Write-Host "OneBot 反向 WebSocket 地址："
        Write-Host "  $Script:OneBotWs"
        Write-Host ""
        Write-Host "核心启动："
        Write-Host "  [1] 日常上线：启动机器人完整链路"
        Write-Host "  [2] 分步启动：逐步确认 AstrBot / NapCat / 本地服务"
        Write-Host ""
        Write-Host "后台与维护："
        Write-Host "  [3] 管理后台：选择打开 AstrBot、NapCat、成员后台等"
        Write-Host "  [4] 健康检查：端口、进程、OneBot 连接"
        Write-Host "  [5] 高级维护：单服务启动、依赖修复、提示说明"
        Write-Host ""
        Write-Host "  [0] 退出"
        Write-Host ""
        $choice = Read-MenuChoice "请选择功能" @("0", "1", "2", "3", "4", "5")

        switch ($choice) {
            "0" {
                Write-Host ""
                Write-Host "已退出启动总控。"
                return
            }
            "1" {
                Invoke-FullStart
                Write-Host ""
                Write-Host "完整启动流程已执行。请保持新打开的服务窗口不要关闭。"
                Write-Host "如果 QQ 群没有响应，请在 NapCat WebUI 确认 WebSocket 客户端地址："
                Write-Host "  $Script:OneBotWs"
                Pause-Menu
            }
            "2" { Show-GuidedStart }
            "3" { Show-AdminMenu }
            "4" {
                Write-Step "健康检查"
                Invoke-HealthCore
                Pause-Menu
            }
            "5" { Show-AdvancedMenu }
        }
    }
}

switch ($Mode.ToLowerInvariant()) {
    "/health" {
        Invoke-HealthCore
        exit 0
    }
    "/full" {
        Invoke-FullStart
        exit 0
    }
    default {
        Show-MainMenu
    }
}
