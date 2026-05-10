@echo off
REM One-shot dev launcher (D34 — consolidated 2026-05-16).
REM
REM Spawns the FastAPI backend (port 8000) and the Next.js frontend
REM (port 3000) in their own console windows, then opens the browser
REM at the home page. Each server gets its own window so the logs stay
REM readable; closing either window (or Ctrl+C inside it) shuts that
REM process down without affecting the other.
REM
REM History: D34 collapsed the prior `dev.bat` + `api.bat` + `web.bat`
REM + `kill-stale.bat` four-file dance into this single launcher that
REM calls the Makefile targets directly. Saves three files at the root
REM and ~85 LOC. The kill-stale loop is now inline at the top.
REM
REM For production (single native window, no consoles), use Diamond.vbs.

cd /d "%~dp0"

REM ─── Self-heal: kill any processes left listening on :3000 / :8000 ───
REM
REM Pre-D32 this lived in a separate kill-stale.bat. Now inlined: 8
REM lines of netstat/findstr/taskkill is small enough that a separate
REM file was overkill. The Job Object in Diamond.vbs eliminates this
REM failure mode for the desktop path; this self-heal is dev-only.
echo === Clearing any stale processes on :3000 / :8000 ===
for %%P in (3000 8000) do (
  for /f "tokens=5" %%I in ('netstat -ano ^| findstr /R /C:":%%P  *.*LISTENING"') do (
    echo   killing PID %%I on :%%P
    taskkill /F /PID %%I /T >nul 2>&1
  )
)

REM ─── Auto-ingest: pick up any new dumps OOTP wrote since last launch ───
REM
REM `diamond ingest --all` is a no-op when nothing's new (~2-3s open
REM the warehouse + check `_diamond_ingests`); when there are new
REM dumps it processes them in chronological order before uvicorn
REM binds. Has to run BEFORE the API starts because uvicorn holds an
REM RW lock on the DuckDB file that ingest also needs. Skip with
REM `set DIAMOND_SKIP_AUTO_INGEST=1` in the parent shell.
if not defined DIAMOND_SKIP_AUTO_INGEST (
  echo.
  echo === Auto-ingest: scanning for new dumps ===
  .venv\Scripts\diamond.exe ingest --all
  if errorlevel 1 (
    echo.
    echo [WARN] Auto-ingest exited with an error. Continuing with launch
    echo        anyway; rerun manually after fixing if needed.
    echo.
  )
)

REM ─── Spawn the two servers in their own windows ───
REM
REM `start "Title" cmd /k <command>` opens a new cmd window, runs the
REM command, and stays open afterward. The title shows in the taskbar
REM so the two windows are easy to tell apart.
REM
REM We call `make api` / `make web` directly — both targets handle
REM their own cd + env setup, replacing the deleted api.bat / web.bat.
start "Diamond API" cmd /k make api
start "Diamond Web" cmd /k make web

REM ─── Open the browser once Next.js has had time to compile ───
REM ~6 seconds is plenty on a warm machine — uvicorn is faster and
REM will be up well before this.
timeout /t 6 /nobreak >nul
start http://localhost:3000
