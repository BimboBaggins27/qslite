@echo off
REM Nightly backup runner — invoked by Windows Task Scheduler.
REM Logs to %USERPROFILE%\.qslite-logs\backup.log so you can verify it ran.

setlocal
set QSDIR=C:\Users\Ruan\.craft-agent\workspaces\ru1\sessions\260501-neat-marble\qs-app
set LOGDIR=%USERPROFILE%\.qslite-logs
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
cd /d "%QSDIR%"

echo. >> "%LOGDIR%\backup.log"
echo ============================================ >> "%LOGDIR%\backup.log"
echo Backup run: %DATE% %TIME% >> "%LOGDIR%\backup.log"
echo ============================================ >> "%LOGDIR%\backup.log"

"C:\Users\Ruan\AppData\Local\Programs\Python\Python311\python.exe" backup_db.py >> "%LOGDIR%\backup.log" 2>&1

echo Exit: %ERRORLEVEL% >> "%LOGDIR%\backup.log"
endlocal
