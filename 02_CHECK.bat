@echo off
cd /d "%~dp0"
python "04_TOOLS\LUMI_FULL_CHECK.py" --root "%CD%" --online
pause
