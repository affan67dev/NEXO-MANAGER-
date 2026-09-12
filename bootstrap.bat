@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (py scripts\bootstrap_nexo.py %* & exit /b %errorlevel%)
where python >nul 2>nul && (python scripts\bootstrap_nexo.py %* & exit /b %errorlevel%)
echo ERROR: Python 3 is required.
exit /b 2
