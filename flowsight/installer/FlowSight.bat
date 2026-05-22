@echo off
title FlowSight — Retail Intelligence
cd /d "%~dp0"

REM Use embedded Python if available, otherwise use system Python
set PYTHON=%~dp0python\python.exe
if not exist "%PYTHON%" set PYTHON=python

REM Open browser after 4 seconds
start "" /b cmd /c "timeout /t 4 /nobreak >nul && (start chrome --app=http://localhost:5000 --window-size=1360,820 2>nul || start msedge --app=http://localhost:5000 2>nul || start http://localhost:5000)"

REM Run FlowSight — use full path to app.py
"%PYTHON%" "%~dp0app.py"
