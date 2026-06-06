@echo off
title FlowSight — Retail Intelligence
cd /d "%~dp0"

REM ── Always use bundled Python — never fall back to system Python ──────────────
set PYTHON=%~dp0python\python.exe

if not exist "%PYTHON%" (
    echo ERROR: Bundled Python not found.
    echo Please re-run the FlowSight installer.
    pause
    exit /b 1
)

REM ── Set environment ───────────────────────────────────────────────────────────
set PATH=%~dp0python;%~dp0python\Scripts;%PATH%
set PYTHONPATH=%~dp0python\Lib\site-packages
set KMP_DUPLICATE_LIB_OK=TRUE
set OPENCV_LOG_LEVEL=SILENT
set OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp

REM ── Launch app ────────────────────────────────────────────────────────────────
"%PYTHON%" "%~dp0app.py"
