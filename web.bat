@echo off
REM Run the Diamond Next.js dev server on http://localhost:3000.
REM
REM This is the Windows-friendly equivalent of `make web` — double-click
REM the file or run `web.bat` from any cmd/PowerShell prompt. The script
REM cd's into the web/ subfolder so pnpm sees the right package.json.
REM
REM Requires Node 20+ and pnpm. If `pnpm` isn't found, install it via
REM `npm install -g pnpm` (or follow https://pnpm.io/installation), then
REM run `pnpm install` in the web/ folder once.
REM
REM Stop the server with Ctrl+C in this window.

cd /d "%~dp0web"

pnpm dev

if errorlevel 1 pause
