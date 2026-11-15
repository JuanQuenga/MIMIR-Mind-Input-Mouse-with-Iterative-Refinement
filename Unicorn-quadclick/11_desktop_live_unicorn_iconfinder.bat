@echo off
title MIMIR desktop, icon finder (live)
cd /d "%~dp0"
call "%~dp00_stop_all.bat" quiet
echo WARNING: the screen will flicker at 9-15 Hz. Do not run this near anyone with photosensitive epilepsy.
echo.
echo Same as launcher 6 (Unicorn). Put the headset on and switch it on first, but clickable things are found with the icon
echo selection from the BCI-Project build: Windows' list plus a look at the
echo pixels of windows that Windows knows little about (games, custom programs).
echo Everything stays on this PC. No names are drawn on the boxes.
echo It starts PAUSED: Ctrl+Alt+P starts, Ctrl+Alt+Q quits. Clicks are REAL.
echo.
pause
start "MIMIR overlay" python overlay.py --finder icons
timeout /t 3 /nobreak >nul
python run_live_gpype.py
pause
