@echo off
setlocal EnableExtensions

rem One-click stop of all NIKKE bot services.

set "CTL_PS1=%~dp0nikke_ctl.ps1"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

"%POWERSHELL_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%CTL_PS1%" -Action stop
echo.
pause
exit /b %errorlevel%
