@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ============================================================
REM  Скопируй этот файл в D:\Общая_Рабочая - и его увидят все.
REM  Двойной клик: открывает чат архива в браузере.
REM  Если запущен на самом сервере - сначала поднимет сервер.
REM
REM  Файл сохранён в кодировке cp866 и без chcp - иначе cmd.exe
REM  сбивается и выполняет куски русского текста как команды.
REM
REM  Адрес сервера. Поменяй, если IP сменился. На сервере покажет:
REM  D:\Scan_Pdf\.venv\Scripts\python.exe net.py
REM ============================================================
set "SERVER=192.168.200.20"
set "PORT=7860"
set "PROJECT=D:\Scan_Pdf"

REM pushd подставляет букву диска для сетевого пути \\сервер\папка,
REM без этого cmd ругается "не поддерживает пути UNC".
pushd "%~dp0" 2>nul

set "URL=http://%SERVER%:%PORT%"

echo.
echo   Архив PDF
echo   Проверяю сервер %SERVER%:%PORT% ...
echo.

call :check
if "%UP%"=="1" goto open

REM Сервера нет. Может, мы сидим прямо за ним?
set "AMSERVER="
powershell -NoProfile -Command "if ((Get-NetIPAddress -AddressFamily IPv4).IPAddress -contains '%SERVER%') { exit 0 } else { exit 1 }" >nul 2>&1
if not errorlevel 1 set "AMSERVER=1"

if not defined AMSERVER goto offline
if not exist "%PROJECT%\start.bat" goto offline

echo   Это сам сервер - запускаю архив...
echo.
start "Архив PDF - сервер" "%PROJECT%\start.bat"

echo   Жду, пока сервер поднимется (до полутора минут)...
for /L %%i in (1,1,45) do (
  ping -n 3 127.0.0.1 >nul
  call :check
  if "!UP!"=="1" goto open
)

echo.
echo   Сервер не успел подняться. Загляни в открывшееся окно - там причина.
echo.
popd
pause
exit /b 1

:open
echo   Сервер на связи. Открываю %URL%
echo.
start "" "%URL%"
popd
exit /b 0

:offline
echo   Сервер %SERVER% не отвечает.
echo.
echo   Что делать:
echo     1. Включен ли компьютер-сервер?
echo     2. На сервере запустить D:\Scan_Pdf\start.bat
echo        (первый раз - от имени администратора).
echo     3. Если у сервера сменился IP - поправь строку SERVER
echo        в начале этого файла.
echo.
popd
pause
exit /b 1

:check
set "UP=0"
powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient; try { $r=$c.BeginConnect('%SERVER%',%PORT%,$null,$null); if ($r.AsyncWaitHandle.WaitOne(1500) -and $c.Connected) { exit 0 } else { exit 1 } } catch { exit 1 } finally { $c.Close() }" >nul 2>&1
if not errorlevel 1 set "UP=1"
exit /b 0
