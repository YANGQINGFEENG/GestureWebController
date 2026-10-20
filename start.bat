@echo off
rem ============================================================
rem  One-click launcher for Windows.
rem  All the real logic lives in scripts/bootstrap.py so that
rem  Windows and Unix behave exactly the same.
rem
rem  Double-click this file, or run:  start.bat
rem  Extra args are passed through, e.g.:  start.bat --api-port 8010
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0"

rem Prefer the project venv; fall back to a system python on PATH.
rem 注意不要用 `where %PY%` 判断：当 PY 是带反斜杠的相对路径时 where 会报无效模式，
rem 从而误判"没装 Python"。分两种情况判断才是可靠的。
set "PY=.venv\Scripts\python.exe"
if exist "%PY%" goto :run

set "PY=python"
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Install Python 3.10+ and make sure "python" is in PATH.
  pause
  exit /b 1
)

:run
"%PY%" scripts\bootstrap.py %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
  echo.
  echo [FAILED] bootstrap exited with code %CODE%. See the messages above.
  pause
)
exit /b %CODE%
