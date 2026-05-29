@echo off
cd /d C:\smart_farm
C:\tools\python311\python.exe -m pipeline.retrain_trigger
exit /b %ERRORLEVEL%
