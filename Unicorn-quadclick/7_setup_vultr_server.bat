@echo off
title QuadClick: set up the Vultr server
cd /d "%~dp0"
set SERVER=137.220.56.226
echo This installs the cloud scanner on your Vultr server %SERVER% (5-15 minutes).
echo.
echo You will be asked for the server's ROOT PASSWORD up to three times.
echo It is on the Vultr page for your server. Nothing shows while you type it.
echo The first time, answer "yes" when asked whether to continue connecting.
echo.
pause
echo.
echo --- Step 1 of 3: copying the scanner to the server
scp -r cloud root@%SERVER%:/root/
if errorlevel 1 goto failed
echo.
echo --- Step 2 of 3: installing (the long part)
ssh root@%SERVER% "sed -i 's/\r$//' /root/cloud/setup_server.sh && bash /root/cloud/setup_server.sh"
if errorlevel 1 goto failed
echo.
echo --- Step 3 of 3: fetching the settings for this laptop
scp root@%SERVER%:/opt/quadclick/laptop_settings.json cloud_settings.json
if errorlevel 1 goto failed
echo.
python cloud_check.py
echo.
echo cloud_settings.json holds your server's access key: do not share or upload it.
pause
exit /b
:failed
echo.
echo Something went wrong in the step above. Send Claude the text in this window.
pause
