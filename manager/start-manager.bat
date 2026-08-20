@echo off
setlocal EnableExtensions

rem Start the NIKKE bot manager. Keep this launcher ASCII-only to avoid cmd encoding issues.

set "MANAGER_DIR=%~dp0"
set "PYTHON_EXE=%MANAGER_DIR%..\.venv\Scripts\python.exe"

if exist "%PYTHON_EXE%" goto run
where py >nul 2>nul
if not errorlevel 1 set "PYTHON_EXE=py -3"& goto run
where python >nul 2>nul
if not errorlevel 1 set "PYTHON_EXE=python"& goto run

echo Python 3 was not found. Run qq_bot\01-install-env.bat first.
pause
exit /b 1

:run
cd /d "%MANAGER_DIR%"
%PYTHON_EXE% manager.py
exit /b %errorlevel%
