@echo off
title QuadClick desktop + cloud scan (live)
cd /d "%~dp0"
call "%~dp00_stop_all.bat" quiet
echo WARNING: the screen will flicker at 9-15 Hz. Do not run this near anyone with photosensitive epilepsy.
echo.
echo Same as launcher 6 (Unicorn on the real desktop), plus the cloud scan.
echo It starts PAUSED: press Ctrl+Alt+P once the calibration (40 s, red dot) is done.
echo.
pause
start "QuadClick overlay" python overlay.py --cloud auto
timeout /t 3 /nobreak >nul
python run_live_gpype.py
pause
