@echo off
setlocal
rem Safe discovery-only demo. With no argument, inspect the current directory.
set "TARGET=%CD%"
if not "%~1"=="" set "TARGET=%~1"
py -3.12 -m geo_mapper "%TARGET%" --offline --dry-run
exit /b %errorlevel%
