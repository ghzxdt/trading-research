@echo off
cd /d "%~dp0"
start "" http://localhost:8767/report.html
".venv\Scripts\python.exe" -m http.server 8767 --bind 127.0.0.1 --directory output\baseline
