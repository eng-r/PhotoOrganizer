@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Photo Archive Organizer
set "PYTHONUTF8=1"

echo.
echo ============================================================
echo  PHOTO ARCHIVE ORGANIZER
echo ============================================================
echo.

if not exist "config.json" (
  echo ERROR: config.json is missing beside start.bat.
  goto failed
)

findstr /C:"CHANGE_ME" "config.json" >nul
if not errorlevel 1 (
  echo First setup: edit the two paths in config.json, save it,
  echo then double-click start.bat again.
  echo.
  start "" notepad.exe "%~dp0config.json"
  goto failed
)

set "ORGANIZER_USE_VENV="
if exist ".venv\Scripts\python.exe" set "ORGANIZER_USE_VENV=1"
if not defined ORGANIZER_USE_VENV (
  where py >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Python 3.12 or newer was not found.
    echo See docs\INSTALLATION.md.
    goto failed
  )
)

if defined ORGANIZER_USE_VENV (
  "%~dp0.venv\Scripts\python.exe" -c "import sys; raise SystemExit(int(sys.version_info < (3,12)))"
) else (
  py -3 -c "import sys; raise SystemExit(int(sys.version_info < (3,12)))"
)
if errorlevel 1 (
  echo ERROR: Python 3.12 or newer is required.
  goto failed
)

echo Configuration: %~dp0config.json
echo The source is read-only. The destination must be empty.
echo.
if defined ORGANIZER_USE_VENV (
  "%~dp0.venv\Scripts\python.exe" "%~dp0photo_organizer.py" --config "%~dp0config.json" run
) else (
  py -3 "%~dp0photo_organizer.py" --config "%~dp0config.json" run
)
set "ORGANIZER_EXIT=%errorlevel%"

echo.
if "%ORGANIZER_EXIT%"=="0" (
  echo Finished. Open DESTINATION\_process\reports\report.html
) else (
  echo The organizer stopped with exit code %ORGANIZER_EXIT%.
  echo Read the message above and docs\OPERATIONS.md.
)
echo.
pause
exit /b %ORGANIZER_EXIT%

:failed
echo.
pause
exit /b 2
