@echo off
setlocal EnableExtensions
title NIKKE QQ Bot - Install Environment
set "SCRIPT_DIR=%~dp0"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

echo [NIKKE QQ Bot] Installing local Python dependencies...
echo Script: %SCRIPT_DIR%
echo.

"%POWERSHELL_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%install-env.ps1"

echo.
echo Install step finished. Press any key to close this window.
pause >nul
