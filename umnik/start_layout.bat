@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv
  pause
  exit /b 1
)
echo OpenRouter layout sync
".venv\Scripts\python.exe" -u layout_sync.py --skip-pilot --batch 5000 --max-usd 8
echo.
echo Done. Exit code %ERRORLEVEL%
pause
