@echo off
setlocal
if "%~1"=="" (
  py -3.12 -m geo_mapper "%CD%"
) else (
  py -3.12 -m geo_mapper %*
)
exit /b %errorlevel%
