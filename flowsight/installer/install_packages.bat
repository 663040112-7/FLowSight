@echo off
title FlowSight — Installing packages
cd /d "%~dp0"

set PYTHON=%~dp0python\python.exe
if not exist "%PYTHON%" set PYTHON=python

echo.
echo ============================================
echo   FlowSight — Installing packages
echo   Please wait 3-5 minutes...
echo ============================================
echo.

REM Install pip for embedded Python
"%PYTHON%" -m ensurepip --upgrade >nul 2>&1
"%PYTHON%" -m pip install --upgrade pip >nul 2>&1

REM Install PyTorch CPU
echo [1/3] Installing PyTorch (CPU)...
"%PYTHON%" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu -q

REM Install other packages
echo [2/3] Installing packages...
"%PYTHON%" -m pip install ultralytics flask reportlab opencv-python scipy -q

REM Download YOLO model
echo [3/3] Downloading YOLO model...
"%PYTHON%" -c "from ultralytics import YOLO; YOLO('yolov8n.pt')" >nul 2>&1

echo.
echo ============================================
echo   Done! FlowSight is ready.
echo ============================================
