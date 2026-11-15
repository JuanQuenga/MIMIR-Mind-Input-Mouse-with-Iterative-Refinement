@echo off
title QuadClick keyboard demo
cd /d "%~dp0"
call "%~dp00_stop_all.bat" quiet
echo WARNING: the screen will flicker at 9-15 Hz. Do not run this near anyone with photosensitive epilepsy.
echo Press the number shown on a box to pick it. Nothing moves until you do.
echo Backspace = undo, Esc = start over, B = two / four choices
echo P = pause, [ and ] = softer / stronger flicker, Q = quit
pause
python overlay.py --demo --keys-only
pause
