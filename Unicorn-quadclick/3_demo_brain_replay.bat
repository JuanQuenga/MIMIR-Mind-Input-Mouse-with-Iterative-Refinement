@echo off
title QuadClick brain replay
cd /d "%~dp0"
call "%~dp00_stop_all.bat" quiet
echo WARNING: the screen will flicker at 9-15 Hz. Do not run this near anyone with photosensitive epilepsy.
echo Recorded brain data will click the green buttons by itself.
echo The first 20 seconds are calibration (red dot, no flicker).
echo Press Q on the flickering window to stop everything.
pause
start "QuadClick overlay" python overlay.py --demo
timeout /t 3 /nobreak >nul
python replay_dataset.py --speed 2
pause
