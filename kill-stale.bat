@echo off
REM Kill anything still listening on the Diamond dev ports (3000 + 8000).
REM
REM When to run this: a prior `dev.bat` was killed unceremoniously
REM (machine sleep, console window force-closed, OS update reboot)
REM and left a stale uvicorn / next dev server holding the port. The
REM next `dev.bat` then fails to bind, OR — worse — Next.js dev
REM connects to the OLD uvicorn while you think you're running the
REM current code, and you spend an afternoon debugging a fix that
REM "isn't working" because the API serving you is from yesterday.
REM
REM This script is also the recovery path when the Quit button in
REM the UI can't help — Quit needs a reachable API to receive the
REM POST, but if the stale process is unreachable for any reason
REM (different code, port conflict, etc.) you need a side-channel.
REM
REM Symmetric with the 5-stage shutdown in `src/diamond/api/routes/
REM admin.py` but lighter — just port-based, since by the time you
REM run this script you don't know what process tree to walk.
REM
REM Double-click from Explorer or run from any cmd/PowerShell prompt.
REM `dev.bat` calls this as its first step so the normal launch
REM workflow self-heals.

cd /d "%~dp0"

setlocal enabledelayedexpansion

set KILLED_ANY=0

REM Iterate the Diamond ports. The for-loop bodies parse netstat -ano
REM output; column 5 is the PID. We dedupe via the !PIDS_<port>!
REM accumulator since netstat lists the same PID once per IPv4/IPv6
REM binding.
for %%P in (3000 8000) do (
  echo --- Port %%P ---
  set PIDS_%%P=
  for /f "tokens=5" %%I in ('netstat -ano ^| findstr /R /C:":%%P  *.*LISTENING"') do (
    echo "!PIDS_%%P!" | findstr /C:" %%I " >nul
    if errorlevel 1 (
      set "PIDS_%%P=!PIDS_%%P! %%I "
      echo   PID %%I listening on :%%P, killing...
      taskkill /F /PID %%I /T
      set KILLED_ANY=1
    )
  )
  if "!PIDS_%%P!"=="" echo   (nothing listening^)
)

echo.
if "%KILLED_ANY%"=="1" (
  echo Stale processes cleared. Safe to run dev.bat now.
) else (
  echo Ports 3000 and 8000 are already free.
)

REM When run standalone (double-click), pause so the output is
REM readable. When called from dev.bat the caller sets DEV_AUTOMATED=1
REM so we exit immediately and don't block the launch chain.
if not defined DEV_AUTOMATED (
  echo.
  pause
)

endlocal
