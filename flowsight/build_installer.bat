@echo off
title FlowSight Build
echo ============================================
echo   FlowSight - Build Desktop App
echo ============================================
cd /d "%~dp0"

echo [1/3] Installing tools...
pip install pyinstaller pywebview --quiet

echo [2/3] Building .exe...
pyinstaller ^
    --onedir ^
    --name FlowSight ^
    --windowed ^
    --icon "assets\icon.ico" ^
    --add-data "templates;templates" ^
    --add-data "assets;assets" ^
    --add-data "bytetrack.yaml;." ^
    --add-data "brand_config.json;." ^
    --add-data "behaviors_config.json;." ^
    --hidden-import ultralytics ^
    --hidden-import flask ^
    --hidden-import cv2 ^
    --hidden-import reportlab ^
    --hidden-import webview ^
    --hidden-import webview.platforms.winforms ^
    --collect-all ultralytics ^
    --collect-all webview ^
    --noconfirm ^
    app.py

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

echo [3/3] Copying required files...
call post_build.bat

echo ============================================
echo   Build complete!
echo   Run: dist\FlowSight\FlowSight.exe
echo ============================================
pause
