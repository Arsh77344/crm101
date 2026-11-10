@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>nul
  if %errorlevel%==0 (py -3.12 app\team_start.py & exit /b %errorlevel%)
)
where python >nul 2>nul
if %errorlevel%==0 (
  python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>nul
  if %errorlevel%==0 (python app\team_start.py & exit /b %errorlevel%)
)
echo Python 3.12 or newer is required. Install Python from python.org and run START_APP.bat again.
pause
exit /b 1
