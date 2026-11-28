@echo off
cd /d "%~dp0"
python 04_TOOLS\dependency_gate.py
if errorlevel 1 (
  echo Dependency audit failed or incomplete. Do not deploy.
  pause
  exit /b 1
)
pause
