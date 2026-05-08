@echo off
REM Start QSLite locally + open the stable ngrok tunnel.
REM Tunnel URL never changes: https://laxative-confining-eskimo.ngrok-free.dev
REM Bookmark that URL on your iPad. Site password lives in agent-brain credentials.

setlocal
set QSDIR=C:\Users\Ruan\.craft-agent\workspaces\ru1\sessions\260501-neat-marble\qs-app
set LOGDIR=%USERPROFILE%\.qslite-logs
set NGROK_DOMAIN=laxative-confining-eskimo.ngrok-free.dev
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
cd /d "%QSDIR%"

echo ================================================================
echo  QSLite — booting Streamlit + ngrok tunnel
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
REM 2) Ngrok with reserved static domain (URL never changes)
del "%LOGDIR%\tunnel.log" 2>nul
start "QSLite Tunnel" /MIN cmd /c "ngrok http --domain=%NGROK_DOMAIN% 8520 --log=stdout --log-format=logfmt > %LOGDIR%\tunnel.log 2>&1"

echo  - Tunnel launching... (logs: %LOGDIR%\tunnel.log)

REM Wait for the started tunnel line to appear
set /a tries=0
:waittunnel
findstr "started tunnel" "%LOGDIR%\tunnel.log" >nul 2>&1
if %errorlevel%==0 goto tunnel_ready
findstr "ERROR" "%LOGDIR%\tunnel.log" >nul 2>&1
if %errorlevel%==0 goto tunnel_failed
set /a tries+=1
if %tries% geq 15 goto tunnel_timeout
timeout /t 2 /nobreak >nul
goto waittunnel
:tunnel_timeout
echo  - WARN: Tunnel didn't come up in 30s. Check %LOGDIR%\tunnel.log
goto :show
:tunnel_failed
echo  - ERROR: ngrok startup failed. Check %LOGDIR%\tunnel.log
goto :show
:tunnel_ready
echo  - Tunnel is up

:show
echo.
echo ================================================================
echo  QSLite is running.
echo ================================================================
echo  Local URL:    http://localhost:8520
echo  Public URL:   https://%NGROK_DOMAIN%
echo  (Bookmark the public URL on iPad — it never changes.)
echo.
echo  Site password: see agent-brain\99-meta\credentials.md
echo  Logs:          %LOGDIR%
echo ================================================================
echo.
echo  Both processes keep running in the background. Use stop-qslite.bat
echo  to terminate them.
echo.
pause
