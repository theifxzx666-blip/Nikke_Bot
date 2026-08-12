@echo off
chcp 65001 >nul
REM ============================================
REM  NIKKE 机器人 - NapCat 一键启动（快速登录小号）
REM  双击运行即可：停掉旧实例 -> 自动快速登录 1255348850
REM  若登录态失效会弹二维码窗口，扫码一次即可
REM ============================================

set NAPCAT_DIR=F:\Codex\Nikke\Nikke_Bot\supports\NapCat.Shell.Windows.OneKey
set QQ_ACCOUNT=1255348850

echo [1/3] 正在停止旧的 NapCat / QQ 进程...

REM 停止所有 NapCat 主进程
taskkill /IM NapCatWinBootMain.exe /F >nul 2>&1

REM 停止被注入的 QQ 进程（NapCat 注入实例）
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":6099" ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
)

timeout /t 3 /nobreak >nul

echo [2/3] 正在启动 NapCat 并快速登录小号 %QQ_ACCOUNT% ...
cd /d "%NAPCAT_DIR%"

REM 使用官方 launcher 启动（自动快速登录 autoLoginAccount）
call launcher-win10-user.bat %QQ_ACCOUNT%

echo [3/3] 启动指令已执行，等待 NapCat 自动登录并连接 AstrBot...
echo.
echo 提示：登录成功后 6099/6199 端口恢复监听，机器人即可使用。
echo 若弹出 QQ 登录窗口，请用手机 QQ 扫码登录小号 %QQ_ACCOUNT%（仅首次或登录态失效时需要）。
echo.
pause
