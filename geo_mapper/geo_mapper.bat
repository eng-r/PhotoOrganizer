@echo off
setlocal
if "%~1"=="" (
  echo Usage: geo_mapper.bat ^<month-year-or-archive-path^> [options]
  exit /b 2
)
py -3.12 -m geo_mapper %*
exit /b %errorlevel%
