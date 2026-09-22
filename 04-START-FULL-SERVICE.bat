@echo off
cd /d "%~dp0"
set "PYTHONUTF8=1"

if not exist "runtime\python\python.exe" (
  echo ERROR: runtime\python\python.exe was not found.
  echo Extract the complete portable ZIP before running this file.
  pause
  exit /b 1
)

"runtime\python\python.exe" "server\portable_launcher.py"
if errorlevel 1 (
  echo.
  echo ERROR: The full service failed to start. Check the logs directory.
  pause
)
