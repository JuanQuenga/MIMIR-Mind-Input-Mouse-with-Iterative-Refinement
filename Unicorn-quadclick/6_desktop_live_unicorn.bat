@echo off
title MIMIR: real desktop (Unicorn headset)
cd /d "%~dp0"
call "%~dp00_stop_all.bat" quiet
echo WARNING: the screen flickers at 9-15 Hz. Do not run this near anyone with photosensitive epilepsy.
echo.
echo REAL DESKTOP controlled by the Unicorn. The clicks are REAL.
echo Put the headset on and switch it on first.
echo The first 40 seconds are calibration (red dot): relax your jaw.
echo It starts PAUSED: hold a long jaw clench (or press Ctrl+Alt+P) to start.
echo    Look at a box's checkered circle to pick it
echo    Short jaw clench = undo (on the first step: pixel grid on / off)
echo    Long jaw clench  = back to the first step, or pause / resume there
echo The toolbar along the bottom: Scroll up, Scroll down, Zones only, Keyboard.
echo The Ctrl+Alt hotkeys still work as a backup. Ctrl+Alt+Q quits.
echo.
pause
start "MIMIR overlay" python overlay.py --finder icons
timeout /t 3 /nobreak >nul
python run_live_gpype.py
pause
