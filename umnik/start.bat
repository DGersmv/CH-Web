@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. From this folder: python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)
title Умник архив 7861
echo Umnik indexer/query API: http://127.0.0.1:7861/crm/health
echo Keep this window open. CRM search talks to the cloud query umnik, not this PC when UMNIK_ROLE=indexer.
echo Search UI is in CRM: http://localhost:8001/archive/
echo.
set PYTHONUTF8=1
set MCP_NO_OPENROUTER=1
curl -s -m 2 http://127.0.0.1:11434/api/tags >nul 2>&1
if errorlevel 1 (
  echo Ollama not running on :11434 — starting for local Qwen 14B
  start "Ollama Qwen" /MIN ollama serve
)
".venv\Scripts\python.exe" mcp_server.py --http --host 0.0.0.0 --port 7861
pause
