@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. From this folder: python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)
title Umnik MCP 7861
echo Umnik CRM API: http://127.0.0.1:7861/crm/health
echo Keep this window open. Search UI is in CRM: http://localhost:8001/archive/
echo.
set PYTHONUTF8=1
set MCP_NO_OPENROUTER=1
".venv\Scripts\python.exe" mcp_server.py --http --host 0.0.0.0 --port 7861
pause
