@echo off
REM Start QSLite locally + open a Cloudflare tunnel so it's reachable from anywhere.
REM Drop a shortcut to this file in shell:startup if you want it to launch on boot.

setlocal
set QSDIR=C:\Users\Ruan\.craft-agent\workspaces\ru1\sessions\260501-neat-marble\qs-app
set LOGDIR=%USERPROFILE%\.qslite-logs
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
cd /d "%QSDIR%"

echo ================================================================
echo  QSLite — booting Streamlit + Cloudflare tunnel
echo ================================================================

REM 1) Streamlit on port 8520, headless, logs to %LOGDIR%\streamlit.log
start "QSLite Streamlit" /MIN cmd /c "streamlit run app.py --server.port 8520 --server.headless true --browser.gatherUsageStats false > %LOGDIR%\streamlit.log 2>&1"

echo  - Streamlit launching... (logs: %LOGDIR%\streamlit.log)

REM Wait until port 8520 is listening (max ~30s)
set /a tries=0
:waitstreamlit
netstat -an | findstr ":8520" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 goto streamlit_ready
set /a tries+=1
if %tries% geq 15 goto streamlit_timeout
timeout /t 2 /nobreak >nul
goto waitstreamlit
:streamlit_timeout
echo  - WARN: Streamlit didn't bind to 8520 within 30s. Check %LOGDIR%\streamlit.log
goto :continue_tunnel
:streamlit_ready
echo  - Streamlit is listening on http://localhost:8520

:continue_tunnel
REM 2) Cloudflare quick tunnel (random URL, free, no signup)
del "%LOGDIR%\tunnel.log" 2>nul
start "QSLite Tunnel" /MIN cmd /c ""C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:8520 --no-autoupdate > %LOGDIR%\tunnel.log 2>&1"

echo  - Tunnel launching... (logs: %LOGDIR%\tunnel.log)

REM Wait for the trycloudflare.com URL to appear in the log
set /a tries=0
:waittunnel
findstr "trycloudflare.com" "%LOGDIR%\tunnel.log" >nul 2>&1
if %errorlevel%==0 goto tunnel_ready
set /a tries+=1
if %tries% geq 15 goto tunnel_timeout
timeout /t 2 /nobreak >nul
goto waittunnel
:tunnel_timeout
echo  - WARN: Tunnel didn't come up in 30s. Check %LOGDIR%\tunnel.log
goto :show
:tunnel_ready
echo  - Tunnel is up

:show
echo.
echo ================================================================
echo  QSLite is running.
echo ================================================================
echo  Local URL:    http://localhost:8520
echo.
echo  Public URL (write this on your iPad):
findstr /R "https://[a-z0-9-]*\.trycloudflare\.com" "%LOGDIR%\tunnel.log"
echo.
echo  Site password: RU1
echo  Logs:          %LOGDIR%
echo ================================================================
echo.
echo  This window can be closed — both processes keep running in the
echo  background (look in Task Manager for "streamlit" and
echo  "cloudflared" if you ever need to stop them).
echo.
pause
