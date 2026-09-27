@echo off
setlocal
rem Edit this example path or pass a canonical four-digit year folder.
set "TARGET=D:\Photos\2026"
if not "%~1"=="" set "TARGET=%~1"
py -3.12 -m geo_mapper "%TARGET%" --scope year
exit /b %errorlevel%
