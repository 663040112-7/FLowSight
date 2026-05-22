@echo off
echo ============================================
echo   FlowSight - Copy files to dist
echo ============================================
cd /d "%~dp0"

set DIST=dist\FlowSight

if not exist "%DIST%\templates" mkdir "%DIST%\templates"
if not exist "%DIST%\assets"    mkdir "%DIST%\assets"
if not exist "%DIST%\static"    mkdir "%DIST%\static"

echo Copying config files...
copy /Y "bytetrack.yaml"          "%DIST%\" >nul
copy /Y "brand_config.json"       "%DIST%\" >nul
copy /Y "behaviors_config.json"   "%DIST%\" >nul
copy /Y "activate.py"             "%DIST%\" >nul
copy /Y "assets\icon.ico"         "%DIST%\assets\" >nul
copy /Y "assets\icon.png"         "%DIST%\assets\" >nul

echo Copying templates...
xcopy /Y /E /I "templates" "%DIST%\templates" >nul

if exist "static" (
    xcopy /Y /E /I "static" "%DIST%\static" >nul
)

if exist "zones_config.json" (
    copy /Y "zones_config.json" "%DIST%\" >nul
    echo Copied zones_config.json
)

REM Copy yolov8n.pt if exists — critical for .exe
if exist "yolov8n.pt" (
    copy /Y "yolov8n.pt" "%DIST%\" >nul
    echo Copied yolov8n.pt
) else (
    echo WARNING: yolov8n.pt not found!
    echo Run: python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
    echo to download it first, then run post_build.bat again.
)

echo.
echo ============================================
echo   Done! Files in %DIST%
echo   Test: dist\FlowSight\FlowSight.exe
echo ============================================
pause
