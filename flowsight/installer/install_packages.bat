@echo off
title FlowSight - Installing packages
cd /d "%~dp0"

set "PYTHON=%~dp0python\python.exe"
set "GETPIP=%~dp0python\get-pip.py"
set "PIP=%~dp0python\Scripts\pip.exe"
set "SITEPACK=%~dp0python\Lib\site-packages"

echo.
echo ============================================
echo   FlowSight - Installing packages
echo   Please wait 3-10 minutes...
echo ============================================
echo.

echo [1/6] Python OK.

echo [2/6] Enabling site-packages...
powershell -NoProfile -Command "(Get-Content '%~dp0python\python312._pth') -replace '#import site','import site' | Set-Content '%~dp0python\python312._pth'"
echo       Done.

if not exist "%~dp0python\Lib"     mkdir "%~dp0python\Lib"
if not exist "%SITEPACK%"          mkdir "%SITEPACK%"
if not exist "%~dp0python\Scripts" mkdir "%~dp0python\Scripts"

echo [3/6] Installing pip...
"%PYTHON%" "%GETPIP%" --no-user --no-warn-script-location
echo       Done.

echo [4/6] Installing PyTorch (CPU)...
"%PYTHON%" -m pip install torch torchvision ^
    --index-url https://download.pytorch.org/whl/cpu ^
    --no-user --no-warn-script-location -q
echo       PyTorch CPU installed.

echo [5/6] Installing FlowSight packages...
"%PYTHON%" -m pip install opencv-python flask numpy ultralytics reportlab scipy ^
    --no-user --no-warn-script-location -q
echo       Done.

echo [6/6] Verifying YOLO model...
"%PYTHON%" -c "from ultralytics import YOLO; YOLO('yolov8n.pt')" >nul 2>&1
echo       Done.

echo.
echo ============================================
echo   Setup complete! FlowSight is ready.
echo ============================================
pause
