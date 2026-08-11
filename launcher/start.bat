@echo off
setlocal EnableExtensions

rem One-click start (background mode: windows hidden, logs to data\logs).
rem Usage: start.bat [fg]   (fg = foreground windows for debugging)

set "CTL_PS1=%~dp0nikke_ctl.ps1"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
set "MODE=background"
if /i "%~1"=="fg" set "MODE=fg"

"%POWERSHELL_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%CTL_PS1%" -Action start -Mode %MODE%
echo.
pause
exit /b %errorlevel%
