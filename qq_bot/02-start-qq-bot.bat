@echo off
setlocal EnableExtensions
title NIKKE QQ Bot - Start
set "SCRIPT_DIR=%~dp0"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

echo [NIKKE QQ Bot] Starting required local services...
echo Script: %SCRIPT_DIR%
echo.

"%POWERSHELL_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start-qq-bot.ps1"

echo.
echo Startup flow finished or stopped. Press any key to close this window.
pause >nul
