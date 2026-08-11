@echo off
setlocal EnableExtensions
title NIKKE AstrBot Bridge
set "PROJECT_DIR=%~dp0.."
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

cd /d "%PROJECT_DIR%"
echo Starting NIKKE AstrBot bridge...
echo Project: %CD%
echo.

"%POWERSHELL_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-astrbot-bridge.ps1"

echo.
echo Bridge stopped or failed to start.
echo Press any key to close this window.
pause >nul
