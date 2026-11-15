@echo off
title MIMIR: practice screen (Unicorn headset)
cd /d "%~dp0"
call "%~dp00_stop_all.bat" quiet
echo WARNING: the screen flickers at 9-15 Hz. Do not run this near anyone with photosensitive epilepsy.
echo.
echo PRACTICE SCREEN with the real headset: try it out before the real desktop.
echo Nothing on your real desktop is clicked.
echo Put the Unicorn on and switch it on first.
echo The first 40 seconds are calibration: relax your jaw and look at the red dot.
echo Then look at the checkered circle of the box that holds the green button.
echo    Short jaw clench = undo (on the first step: pixel grid on / off)
echo    Long jaw clench  = back to the first step, or pause / resume there
echo.
pause
start "MIMIR overlay" python overlay.py --demo
timeout /t 3 /nobreak >nul
python run_live_gpype.py
pause
