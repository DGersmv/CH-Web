@echo off
cd /d "%~dp0"
echo CH-CRM + умник архива (поиск проектов на :7861)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
if errorlevel 1 pause
exit /b %ERRORLEVEL%
