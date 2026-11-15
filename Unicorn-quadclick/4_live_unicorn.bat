@echo off
title QuadClick live
cd /d "%~dp0"
call "%~dp00_stop_all.bat" quiet
echo WARNING: the screen will flicker at 9-15 Hz. Do not run this near anyone with photosensitive epilepsy.
echo Put the Unicorn on and switch it on first.
echo The first 40 seconds are calibration: relax your jaw and look at the red dot.
pause
start "QuadClick overlay" python overlay.py --demo
timeout /t 3 /nobreak >nul
python run_live_gpype.py
pause
