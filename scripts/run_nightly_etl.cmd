@echo off
cd /d C:\smart_farm
C:\tools\python311\python.exe -m pipeline.nightly_db_etl
exit /b %ERRORLEVEL%
