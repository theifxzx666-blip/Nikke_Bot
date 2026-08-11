@echo off
setlocal EnableExtensions

rem ASCII-only launcher for the NIKKE QQ Bot control console.
rem Chinese UI is printed by nikke_ctl.ps1.

set "CTL_PS1=%~dp0nikke_ctl.ps1"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not exist "%CTL_PS1%" (
  echo Missing control script:
  echo   "%CTL_PS1%"
  pause
  exit /b 1
)

"%POWERSHELL_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%CTL_PS1%" -Action menu
exit /b %errorlevel%
