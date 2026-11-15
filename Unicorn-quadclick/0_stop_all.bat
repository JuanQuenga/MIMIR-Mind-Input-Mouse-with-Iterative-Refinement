@echo off
rem Closes every QuadClick program that is still running (overlay, replay, live).
rem Only Python processes started from these scripts are touched.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -match 'overlay\.py|replay_dataset\.py|run_live_gpype\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
if "%~1"=="" (
  echo All QuadClick programs are closed.
  pause
)
