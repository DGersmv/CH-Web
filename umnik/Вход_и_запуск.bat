@echo off
setlocal EnableExtensions
REM ============================================================
REM  Вход в Claude по подписке + запуск сервера архива.
REM  Файл в кодировке cp866 и без chcp: смена кодовой страницы
REM  посреди batch-файла сбивает разбор строк.
REM
REM  Прокси НЕ прописан здесь намеренно: пароль лежит в .env
REM  (ключ OPENROUTER_PROXY), а .env закрыт .gitignore.
REM  Локальный мост снимает с прокси логин-пароль и отдаёт CLI
REM  чистый адрес 127.0.0.1:17880.
REM ============================================================
cd /d "%~dp0"

set "BRIDGE_PORT=17880"
set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo Нет окружения %PY%
  echo   python -m venv .venv
  echo   .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)

findstr /B /C:"OPENROUTER_PROXY=" .env >nul 2>&1
if errorlevel 1 (
  echo В .env нет строки OPENROUTER_PROXY - выхода через прокси не будет.
  echo Добавь строку вида:
  echo   OPENROUTER_PROXY=http://логин:пароль@адрес:порт
  pause
  exit /b 1
)

echo.
echo [1/4] Прокси-мост до Anthropic
call :bridge_up
if "%UP%"=="1" (
  echo       уже работает на 127.0.0.1:%BRIDGE_PORT%
) else (
  start "Прокси-мост" /B "%PY%" proxy_auth_bridge.py
  ping -n 4 127.0.0.1 >nul
  call :bridge_up
  if "%UP%"=="1" (
    echo       поднят на 127.0.0.1:%BRIDGE_PORT%
  ) else (
    echo       НЕ поднялся. Смотри data\claude_proxy.log
    pause
    exit /b 1
  )
)

REM Весь дальнейший трафик Claude идёт через мост, локальная сеть - мимо.
set "HTTPS_PROXY=http://127.0.0.1:%BRIDGE_PORT%"
set "HTTP_PROXY=http://127.0.0.1:%BRIDGE_PORT%"
set "NO_PROXY=localhost,127.0.0.1,::1,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12"
set "no_proxy=%NO_PROXY%"
REM Ключа быть не должно: работаем на подписке, а не на API.
set "ANTHROPIC_API_KEY="

call :find_claude
if not defined CLAUDE (
  echo.
  echo Claude CLI не найден. Установи:
  echo   npm install -g @anthropic-ai/claude-code
  pause
  exit /b 1
)

echo.
echo [2/4] Вход по подписке
echo       Откроется браузер. Введи логин и пароль своей учётной
echo       записи Anthropic. Если вход уже был - CLI сразу выйдет.
echo.
call "%CLAUDE%" login

echo.
echo [3/4] Проверка
call "%CLAUDE%" -p "ответь одним словом: готов" --output-format text --restricted --strict-mcp-config
echo.

echo [4/4] Запуск сервера архива
echo.
call start.bat
exit /b 0

:bridge_up
set "UP=0"
powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient; try { $r=$c.BeginConnect('127.0.0.1',%BRIDGE_PORT%,$null,$null); if ($r.AsyncWaitHandle.WaitOne(1500) -and $c.Connected) { exit 0 } else { exit 1 } } catch { exit 1 } finally { $c.Close() }" >nul 2>&1
if not errorlevel 1 set "UP=1"
exit /b 0

:find_claude
set "CLAUDE="
for /f "delims=" %%p in ('where claude 2^>nul') do if not defined CLAUDE set "CLAUDE=%%p"
if defined CLAUDE exit /b 0
if exist "%APPDATA%\npm\claude.cmd" set "CLAUDE=%APPDATA%\npm\claude.cmd"
exit /b 0
