@echo off
echo [PORT 80]
netstat -ano | findstr LISTENING | findstr ":80 "
echo.
echo [LOCAL HTTP]
curl.exe -I --max-time 5 http://localhost/
echo.
echo [DOMAIN HTTP]
curl.exe -I --max-time 10 http://ailab.cbnu.ac.kr/
pause
