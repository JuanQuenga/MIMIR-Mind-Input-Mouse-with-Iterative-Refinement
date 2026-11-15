@echo off
cd /d "%~dp0"
echo Installing what QuadClick needs...
python -m pip install -r requirements.txt
echo.
echo Done. If you saw red error text above, send Claude a screenshot.
pause
