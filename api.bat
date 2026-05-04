@echo off
REM Run the Diamond FastAPI backend on http://localhost:8000.
REM
REM This is the Windows-friendly equivalent of `make api` — double-click
REM the file or run `api.bat` from any cmd/PowerShell prompt. The script
REM cd's into its own directory so it works regardless of where it was
REM invoked from.
REM
REM Stop the server with Ctrl+C in this window. Closing the window also
REM kills uvicorn cleanly.

cd /d "%~dp0"

REM Force UTF-8 stdio so Rich box-drawing + the dictionary's unicode
REM glyphs render in cmd. Per docs/DEV.md troubleshooting note.
set PYTHONIOENCODING=utf-8

REM --reload picks up Python changes without a restart; --host 127.0.0.1
REM keeps the API local-only (no LAN exposure).
.venv\Scripts\python.exe -m uvicorn diamond.api:app --reload --host 127.0.0.1 --port 8000

REM If uvicorn exits with an error, keep the window open so the message
REM is readable. (Successful Ctrl+C exits cleanly without pause.)
if errorlevel 1 pause
