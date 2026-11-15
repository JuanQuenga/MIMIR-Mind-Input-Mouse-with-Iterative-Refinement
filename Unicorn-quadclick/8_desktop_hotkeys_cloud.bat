@echo off
title QuadClick desktop + cloud scan (hotkeys)
cd /d "%~dp0"
call "%~dp00_stop_all.bat" quiet
echo WARNING: the screen will flicker at 9-15 Hz. Do not run this near anyone with photosensitive epilepsy.
echo.
echo Same as launcher 5, plus the cloud scan: when Windows finds no buttons, a
echo picture of your screen is sent to YOUR Vultr server, which finds them by looking.
echo Ctrl+Alt+M switches between: real buttons / cloud scan every time / pixel grid.
echo It starts PAUSED: Ctrl+Alt+P to start. The clicks at the end are REAL.
echo.
pause
python overlay.py --keys-only --cloud auto
pause
