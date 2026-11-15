@echo off
title QuadClick desktop (hotkeys)
cd /d "%~dp0"
call "%~dp00_stop_all.bat" quiet
echo WARNING: the screen will flicker at 9-15 Hz. Do not run this near anyone with photosensitive epilepsy.
echo.
echo This puts a see-through layer over your REAL desktop. It starts PAUSED.
echo Click the window you want to control first, then hold Ctrl+Alt and press:
echo    P = start / pause      1 2 3 4 = pick the box with that number
echo    Backspace = undo       Home = start over      Q = quit
echo    B = two / four choices       M = real buttons / pixel grid
echo At the end you choose Left click, Double click, Right click or Cancel.
echo Those clicks are REAL.
echo.
pause
python overlay.py --keys-only
pause
