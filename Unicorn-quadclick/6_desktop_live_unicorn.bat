@echo off
title QuadClick desktop (live)
cd /d "%~dp0"
call "%~dp00_stop_all.bat" quiet
echo WARNING: the screen will flicker at 9-15 Hz. Do not run this near anyone with photosensitive epilepsy.
echo.
echo REAL desktop, controlled by the Unicorn. Put it on and switch it on first.
echo It starts PAUSED: press Ctrl+Alt+P once the calibration (40 s, red dot) is done.
echo Looking at a box picks it. The last pick does a REAL mouse click.
echo Ctrl+Alt+P pauses again, Ctrl+Alt+Q quits. The hotkeys still work as a backup.
echo.
pause
start "QuadClick overlay" python overlay.py
timeout /t 3 /nobreak >nul
python run_live_gpype.py
pause
