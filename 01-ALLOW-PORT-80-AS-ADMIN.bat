@echo off
fltmc >nul 2>&1
if not "%errorlevel%"=="0" (
  echo ERROR: Right-click this file and select Run as administrator.
  pause
  exit /b 1
)

netsh advfirewall firewall delete rule name="CBNU AI Lab HTTP" >nul 2>&1
netsh advfirewall firewall add rule name="CBNU AI Lab HTTP" dir=in action=allow protocol=TCP localport=80 profile=any
if errorlevel 1 (
  echo ERROR: Failed to add the Windows Firewall rule.
  pause
  exit /b 1
)

echo OK: TCP port 80 is allowed through Windows Firewall.
pause
