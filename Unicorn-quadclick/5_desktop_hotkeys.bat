@echo off
title MIMIR: real desktop (hotkeys)
cd /d "%~dp0"
call "%~dp00_stop_all.bat" quiet
echo WARNING: the screen flickers at 9-15 Hz. Do not run this near anyone with photosensitive epilepsy.
echo.
echo REAL DESKTOP without a headset: a see-through layer over everything, and
echo the clicks are REAL. It starts PAUSED. Click the window you want first.
echo Clickable things are found from Windows' list plus a look at the pixels
echo (for games and custom programs). Everything stays on this PC.
echo Hold Ctrl+Alt and press:
echo    P = start / pause      1 2 3 4 = pick a box     Backspace = undo
echo    Home = start over      B = two / four choices   M = pixel grid on / off
echo    T = keyboard           D = save a snapshot      Q = quit
echo The toolbar along the bottom: Scroll up, Scroll down, Zones only, Keyboard.
echo At the end: Left click, Double click, Right click or Cancel.
echo.
pause
python overlay.py --keys-only --finder icons
pause
