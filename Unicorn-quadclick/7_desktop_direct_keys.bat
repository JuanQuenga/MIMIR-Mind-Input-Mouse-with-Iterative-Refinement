@echo off
title MIMIR: real desktop (direct 1-4 keys)
cd /d "%~dp0"
call "%~dp00_stop_all.bat" quiet
echo WARNING: the screen flickers at 9-15 Hz. Do not run this near anyone with photosensitive epilepsy.
echo.
echo REAL DESKTOP without a headset: a see-through layer over everything, and
echo the clicks are REAL. It starts PAUSED. Click the window you want first.
echo Clickable things are found from Windows' list plus a look at the pixels
echo (for games and custom programs). Everything stays on this PC.
echo.
echo Once started (Ctrl+Alt+P), press 1 2 3 4 directly (no Ctrl+Alt needed) to pick a box.
echo Pausing or quitting releases 1 2 3 4 back to Windows.
echo Hold Ctrl+Alt for the other controls:
echo    P = start / pause      Backspace = undo         Home = start over
echo    B = two / four choices M = pixel grid on / off  T = keyboard
echo    D = save a snapshot    Q = quit
echo The toolbar along the bottom: Scroll up, Scroll down, Zones only, Keyboard.
echo At the end: Left click, Double click, Right click or Cancel.
echo.
pause
python overlay.py --keys-only --finder icons --direct-keys
pause
