@echo off
title FlowSight
cd /d "%~dp0"

REM ลอง pywebview ก่อน (เปิดเป็นหน้าต่างแอป)
python app.py
if %ERRORLEVEL% NEQ 0 (
    REM fallback ใช้ browser
    python server.py
)
