@echo off
setlocal EnableExtensions

rem ASCII-only shortcut to the unified NIKKE QQ Bot console.
rem Preferred entry: launcher\menu.bat (one-click control).
rem Fallback: qq_bot\NIKKE_QQ_BOT_MENU.bat (legacy menu).

set "LAUNCHER_MENU=%~dp0launcher\menu.bat"
set "LEGACY_MENU=%~dp0qq_bot\NIKKE_QQ_BOT_MENU.bat"

if exist "%LAUNCHER_MENU%" (
  call "%LAUNCHER_MENU%" %*
  exit /b %errorlevel%
)

if exist "%LEGACY_MENU%" (
  call "%LEGACY_MENU%" %*
  exit /b %errorlevel%
)

echo Missing launcher menu:
echo   "%LAUNCHER_MENU%"
echo   "%LEGACY_MENU%"
pause
exit /b 1
