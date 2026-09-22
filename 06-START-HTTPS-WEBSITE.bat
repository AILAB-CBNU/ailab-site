@echo off
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"

if not exist "runtime\python\python.exe" (
  echo ERROR: runtime\python\python.exe was not found.
  echo Extract the complete portable ZIP before running this file.
  pause
  exit /b 1
)

if not exist "runtime\caddy\caddy.exe" (
  echo ERROR: runtime\caddy\caddy.exe was not found.
  echo Copy the HTTPS add-on or extract the latest complete portable ZIP.
  pause
  exit /b 1
)

"runtime\python\python.exe" "server\https_launcher.py"
if errorlevel 1 (
  echo.
  echo ERROR: HTTPS failed to start.
  echo Close the old website window and check whether ports 80, 443, or 8765 are already in use.
  pause
)
