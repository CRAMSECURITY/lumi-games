@echo off
cd /d "%~dp001_BOT"
python -m unittest discover -p "test_*.py"
pause
