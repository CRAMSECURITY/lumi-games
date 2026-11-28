@echo off
cd /d "%~dp0"
python 04_TOOLS\release_gate.py
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" echo RELEASE BLOCKED OR INCOMPLETE
pause
exit /b %RESULT%
