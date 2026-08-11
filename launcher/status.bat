@echo off
setlocal EnableExtensions

rem Health check: ports, processes, bridge and OneBot connection.

set "CTL_PS1=%~dp0nikke_ctl.ps1"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

"%POWERSHELL_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%CTL_PS1%" -Action status
echo.
pause
exit /b %errorlevel%
