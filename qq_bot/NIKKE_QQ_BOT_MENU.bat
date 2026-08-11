@echo off
setlocal EnableExtensions

rem ASCII-only launcher. The Chinese menu is printed by the PowerShell script.
rem Keep this file ASCII + CRLF so cmd.exe will not misparse UTF-8 Chinese text.

set "SCRIPT_DIR=%~dp0"
set "MENU_PS1=%SCRIPT_DIR%NIKKE_QQ_BOT_MENU.ps1"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not exist "%MENU_PS1%" (
  echo Missing PowerShell menu script:
  echo   "%MENU_PS1%"
  pause
  exit /b 1
)

"%POWERSHELL_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%MENU_PS1%" %*
exit /b %errorlevel%
