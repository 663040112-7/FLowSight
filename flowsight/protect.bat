@echo off
title FlowSight Code Protection
echo ============================================
echo   FlowSight - Code Protection (PyArmor)
echo ============================================
echo.

pip install pyarmor --quiet

REM Obfuscate ไฟล์สำคัญ
pyarmor gen ^
    server.py ^
    behavior_engine.py ^
    zones.py ^
    dashboard.py ^
    alert.py ^
    logger.py ^
    tracker.py ^
    license.py ^
    ai_insight.py ^
    report.py ^
    report_pdf.py

echo.
echo Done! Protected files saved to: dist\
echo Use files in dist\ instead of originals
echo.
pause
