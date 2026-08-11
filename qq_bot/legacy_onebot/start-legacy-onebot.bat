@echo off
setlocal EnableExtensions
title Guild War QQ Bot Legacy OneBot
set "PROJECT_DIR=%~dp0..\.."
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

cd /d "%PROJECT_DIR%"
echo Starting Guild War QQ Bot legacy OneBot endpoint...
echo Project: %CD%
echo.

"%POWERSHELL_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-onebot.ps1"

echo.
echo Bot stopped or failed to start.
echo Press any key to close this window.
pause >nul
