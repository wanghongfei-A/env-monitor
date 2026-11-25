@echo off
REM Run backend in foreground. Keep this file ASCII-only (cmd misparses UTF-8 Chinese).
REM -u = unbuffered stdout, otherwise print() is block-buffered when redirected to a log file.
cd /d "%~dp0.."
if not exist logs mkdir logs
set PYTHONUNBUFFERED=1
echo [%DATE% %TIME%] start server >> logs\server.log
".venv\Scripts\python.exe" -u -m uvicorn main:app --app-dir server --host 127.0.0.1 --port 8000 >> logs\server.log 2>&1
