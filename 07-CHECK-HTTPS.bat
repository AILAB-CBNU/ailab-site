@echo off
echo [PORT 443]
netstat -ano | findstr LISTENING | findstr ":443 "
echo.
echo [HTTPS DOMAIN]
curl.exe -I --max-time 15 https://ailab.cbnu.ac.kr/
pause
