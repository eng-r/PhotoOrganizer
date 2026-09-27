@echo off
setlocal
rem Edit this example path or pass your archive root as the first argument.
set "TARGET=D:\Photos"
if not "%~1"=="" set "TARGET=%~1"
py -3.12 -m geo_mapper "%TARGET%" --scope archive
exit /b %errorlevel%
