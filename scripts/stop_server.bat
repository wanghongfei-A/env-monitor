@echo off
REM Stop the backend listening on port 8000. ASCII only.
echo Stopping env-monitor backend on port 8000 ...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo   killing PID %%p
    taskkill /PID %%p /F
)
echo Done.
pause
