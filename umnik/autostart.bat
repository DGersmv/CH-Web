@echo off
setlocal EnableExtensions
REM Файл в кодировке cp866 и без chcp.
cd /d "%~dp0"
REM ============================================================
REM  Автозапуск сервера архива при входе в Windows.
REM  Запускать от имени администратора, один раз.
REM
REM  Режим ONLOGON, а не ONSTART: токен подписки Claude лежит в
REM  профиле пользователя, а задача до входа в систему работает
REM  без загруженного профиля и Claude оказался бы "не залогинен".
REM ============================================================

net session >nul 2>&1
if errorlevel 1 (
  echo Нужны права администратора: правой кнопкой - Запуск от имени администратора.
  pause
  exit /b 1
)

schtasks /Query /TN "ScanPdf Archive" >nul 2>&1
if not errorlevel 1 (
  echo Задача уже есть, пересоздаю.
  schtasks /Delete /TN "ScanPdf Archive" /F >nul
)

schtasks /Create /TN "ScanPdf Archive" /SC ONLOGON /RU "%USERNAME%" /RL HIGHEST /TR "\"%~dp0start.bat\"" /F
if errorlevel 1 (
  echo Не получилось создать задачу.
  pause
  exit /b 1
)

echo.
echo Готово. Сервер будет подниматься сам при входе в Windows
echo под пользователем %USERNAME%.
echo.
echo Проверить состав:  schtasks /Query /TN "ScanPdf Archive" /V /FO LIST
echo Запустить сейчас:  schtasks /Run /TN "ScanPdf Archive"
echo Убрать автозапуск: schtasks /Delete /TN "ScanPdf Archive" /F
echo.
echo Важно: после перезагрузки надо войти в Windows под этим
echo пользователем - иначе задача не сработает.
echo.
pause
