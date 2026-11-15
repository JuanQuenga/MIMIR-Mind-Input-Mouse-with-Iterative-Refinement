@echo off
title MIMIR: practice screen (recorded brain data)
cd /d "%~dp0"
call "%~dp00_stop_all.bat" quiet
echo WARNING: the screen flickers at 9-15 Hz. Do not run this near anyone with photosensitive epilepsy.
echo.
echo PRACTICE SCREEN driven by real recorded EEG from the g.tec dataset:
echo a simulated user "looks" at the green button and the same decoder the
echo headset uses picks the boxes. Nothing on your real desktop is clicked.
echo The first 20 seconds are calibration (red dot, no flicker).
echo Needs the subject_*.mat recordings in this folder or one above it.
echo Press Q on the flickering window to stop everything.
echo.
pause
start "MIMIR overlay" python overlay.py --demo
timeout /t 3 /nobreak >nul
python replay_dataset.py --speed 2
pause
