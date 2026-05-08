@echo off
REM Stop QSLite — kills both Streamlit and the ngrok tunnel.
echo Stopping QSLite...
taskkill /F /IM ngrok.exe 2>nul
taskkill /F /IM cloudflared.exe 2>nul
taskkill /F /FI "WINDOWTITLE eq QSLite Streamlit*" 2>nul
taskkill /F /FI "WINDOWTITLE eq QSLite Tunnel*" 2>nul
REM Also kill any python.exe processes running streamlit (best-effort)
for /f "tokens=2 delims=," %%i in ('tasklist /v /fo csv /fi "imagename eq python.exe" ^| findstr /i "streamlit"') do (
    taskkill /F /PID %%~i 2>nul
)
echo Done.
pause
