@echo off
REM One-shot dev launcher — spawns the FastAPI backend (port 8000) and
REM the Next.js frontend (port 3000) in their own console windows, then
REM opens the browser at the home page.
REM
REM Each server gets its own window so the logs stay readable; closing
REM either window (or Ctrl+C inside it) shuts that process down without
REM affecting the other. The browser tab is independent of both — refresh
REM if Next.js wasn't quite ready when it opened.
REM
REM This is purely a convenience wrapper around `api.bat` + `web.bat` —
REM use those individually if you only need to restart one half.

cd /d "%~dp0"

REM Self-heal: if a prior session crashed / was force-closed and left
REM stale processes on :3000 or :8000, clear them before launch.
REM Without this, the new uvicorn fails to bind and the new Next dev
REM connects to the stale uvicorn (silent stale-code bug). DEV_AUTOMATED
REM tells kill-stale.bat to skip its pause prompt so the chain proceeds.
set DEV_AUTOMATED=1
call kill-stale.bat
set DEV_AUTOMATED=

REM `start "Title" cmd /k script` opens a new cmd window that runs the
REM script and stays open afterward. The title shows in the taskbar so
REM the two windows are easy to tell apart.
start "Diamond API" cmd /k api.bat
start "Diamond Web" cmd /k web.bat

REM Give Next.js a moment to compile its first build before opening the
REM browser. ~6 seconds is plenty on a warm machine — uvicorn is faster
REM and will be up well before this.
timeout /t 6 /nobreak >nul

REM `start <url>` hands the URL to the default browser.
start http://localhost:3000
