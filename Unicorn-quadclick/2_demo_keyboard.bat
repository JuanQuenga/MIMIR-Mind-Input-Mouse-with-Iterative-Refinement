@echo off
title MIMIR: practice screen (keyboard)
cd /d "%~dp0"
call "%~dp00_stop_all.bat" quiet
echo WARNING: the screen flickers at 9-15 Hz. Do not run this near anyone with photosensitive epilepsy.
echo.
echo PRACTICE SCREEN: fake buttons, nothing on your real desktop is clicked.
echo Each box has its own colour, and so do the outlines of the things in it.
echo Look at a box's checkered circle (here: press its number) to pick it.
echo The last step puts a flickering box around each single button.
echo.
echo    1 2 3 4 = pick a box        Backspace = undo      Esc = start over
echo    B = two / four choices      C = circle style      [ ] = softer / stronger
echo    M = pixel grid on / off     T = keyboard          P = pause    Q = quit
echo The toolbar along the bottom (Scroll, Zones only, Keyboard) is picked
echo like any other button.
echo.
pause
python overlay.py --demo --keys-only
pause
