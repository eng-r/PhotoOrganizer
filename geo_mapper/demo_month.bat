@echo off
setlocal
rem Edit this example path or pass a canonical month folder.
set "TARGET=D:\Photos\2026\03-Mar.Ecuador"
if not "%~1"=="" set "TARGET=%~1"
py -3.12 -m geo_mapper "%TARGET%" --scope month
exit /b %errorlevel%
