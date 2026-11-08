@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Local runtime missing. Run py -3.12 -m venv .venv then .venv\Scripts\python -m pip install -r requirements.txt
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -B "%~dp0desktop_app.pyw"
exit /b 0
