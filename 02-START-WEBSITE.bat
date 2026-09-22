@echo off
cd /d "%~dp0"
set "PYTHONUTF8=1"

if not exist "runtime\python\python.exe" (
  echo ERROR: runtime\python\python.exe was not found.
  echo Extract the complete portable ZIP before running this file.
  pause
  exit /b 1
)

"runtime\python\python.exe" "server\website_only.py"
if errorlevel 1 (
  echo.
  echo ERROR: The website failed to start.
  echo Check whether port 80 is already in use:
  echo netstat -ano ^| findstr :80
  pause
)
