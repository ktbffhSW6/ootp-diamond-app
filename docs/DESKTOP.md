# Desktop shell (D32)

Diamond ships as a native Windows desktop app — one `Diamond.exe`,
no browser, no flapping consoles, clean shutdown. Architecture
decision in [DECISIONS.md D32](DECISIONS.md#d32--native-desktop-shell-PySide6--pyinstaller-no-browser-no-consoles).

## Run modes

| Command | What it does | When to use |
|---|---|---|
| `dev.bat` | Two visible cmd windows + browser tab. Hot-reload. | **Engineering** — iterating on backend / frontend code |
| `python -m diamond.desktop --dev` | Native window + tray; assumes `dev.bat` is already running on :3000 / :8000. Hot-reload still works because Next.js dev server is upstream. | Iterating on **launcher / tray / splash** code |
| `python -m diamond.desktop` | Native window + tray; spawns hidden uvicorn (in-thread) + hidden `node server.js` against the standalone build. No hot-reload. | Validating the production path locally |
| `Diamond.exe` (after `make desktop-package`) | Production bundle. Standalone, no Python or repo on disk needed. | End-user double-click |

## Quick start (engineering)

One-time setup:

```bash
make install-desktop      # pip install -e ".[desktop]"  (PySide6, pystray, Pillow, pyinstaller, psutil)
```

Daily development on launcher code (with `dev.bat` running):

```bash
python -m diamond.desktop --dev
```

Production-path validation (no dev.bat needed):

```bash
make desktop              # next build + asset copy + python -m diamond.desktop
```

Full bundle:

```bash
make desktop-package      # → dist/Diamond/Diamond.exe
```

## Architecture

The launcher follows a **single-window-morph** pattern (PySide6 + QtWebEngine
gives us one QApplication, one QMainWindow, one QWebEngineView; the
boot thread emits a Qt signal to swap content):

```
                 ┌─────────────────────────────────────────────────────┐
                 │ Diamond.exe (PyInstaller-frozen Python interpreter) │
                 │                                                     │
                 │  ┌─ main thread ─────────────────────────────────┐  │
                 │  │ Qt event loop (app.exec())                    │  │
                 │  │   QMainWindow + QWebEngineView (Chromium)     │  │
                 │  │   ▲                                           │  │
                 │  │   │ signal.urlReady → view.load(QUrl)         │  │
                 │  └───┼───────────────────────────────────────────┘  │
                 │      │                                              │
                 │  ┌───┴── boot daemon thread ─────────────────────┐  │
                 │  │ start_sidecars():                              │  │
                 │  │   uvicorn.Server.run() (in-thread, on :8000)   │  │
                 │  │   subprocess.Popen(node server.js, on :3000)  ─┼──┼──► node (hidden, joined to Job Object)
                 │  │   wait_for_port(api), wait_for_port(web)       │  │
                 │  └────────────────────────────────────────────────┘  │
                 │                                                     │
                 │  ┌── tray daemon thread ────────────────────────┐    │
                 │  │ pystray Icon.run() — Win32 message loop      │    │
                 │  └──────────────────────────────────────────────┘    │
                 └─────────────────────────────────────────────────────┘
                                            │
                                            ▼
                              Windows Job Object (KILL_ON_JOB_CLOSE)
                              ─ launcher PID
                              ─ node PID  ←  dies with launcher, always
```

### Lifecycle

1. **Single-instance lock** (`single_instance.acquire()`) — `CreateMutexW("Local\\Diamond.OOTP.Desktop.SingleInstance")`. Second double-click sees `ERROR_ALREADY_EXISTS`, calls `FindWindowW` + `SetForegroundWindow` on the existing window, exits with code 0.
2. **Job Object** (`win_jobobject.create_kill_on_close_job()`) — handle stays alive in module state for launcher lifetime.
3. **QApplication + QMainWindow + QWebEngineView** initialized with splash HTML at final size (1600×1000). User sees a polished loading screen within ~200ms. QtWebEngine ships its own Chromium so there's no "user must install WebView2" dependency.
4. **Boot thread** runs concurrently:
   - Starts uvicorn in another daemon thread.
   - Spawns `node server.js` with `CREATE_NO_WINDOW`, assigns its PID to the Job Object.
   - Waits up to 45s for both ports to accept TCP connections.
   - Emits a Qt signal (`signals.urlReady`) — slot runs on GUI thread, calls `view.load(QUrl(...))`. Atomic swap from splash to app.
5. **Tray thread** (optional, daemon) — pystray Icon with Show / Metabase / API docs / Quit menu.
6. **Qt event loop** (`app.exec()`) — blocks until window closes or `app.quit()` is called.
7. **On `aboutToQuit`** — `_cleanup` slot fires → `stop_sidecars` (terminate node, daemon uvicorn dies with process) → tray stops → exit.

### Files

```
src/diamond/desktop/
  __init__.py            module docstring
  __main__.py            python -m diamond.desktop entry
  launcher.py            argv parse + lifecycle orchestration (~260 LOC)
  paths.py               source-vs-frozen path resolution
  sidecar.py             uvicorn-thread + Next.js subprocess + port probes
  single_instance.py     Win32 named mutex + FindWindow/SetForeground
  win_jobobject.py       ctypes Job Object wrapper
  splash.py              loads assets/splash.html (single-window-morph)
  tray.py                pystray icon + menu
  diamond.spec           PyInstaller one-folder spec
  assets/
    splash.html          dark-themed loading screen (matches D18 theme)
    .gitkeep             documents the optional artwork files
                         (tray_icon.png, diamond.ico — runtime fallbacks
                         exist when missing)

scripts/build_desktop.py    next build + asset copy + (optional) PyInstaller
```

## Build pipeline

`scripts/build_desktop.py` orchestrates:

```
1. cd web && npm run build          (Next.js standalone output → web/.next/standalone/)
2. Copy web/.next/static  → web/.next/standalone/.next/static
3. Copy web/public        → web/.next/standalone/public
4. (with --package) pyinstaller src/diamond/desktop/diamond.spec
```

Step 2-3 is necessary because `next build` with `output: 'standalone'`
produces a tree that's *almost* self-contained but deliberately omits
`.next/static` and `public/` — the Next docs say "you should copy
these manually". This script does it.

`diamond.spec` is a **one-folder** PyInstaller bundle (not `--onefile`)
because the Next.js standalone tree is thousands of small files and
`--onefile`'s per-launch unpack to TEMP would add 2-3s to cold-start.
The output at `dist/Diamond/` contains `Diamond.exe` plus its support
files; an installer (Inno Setup / MSIX) wraps the folder for
distribution.

## Configuration

Environment variables (read once at launch):

| Var | Default | Effect |
|---|---|---|
| `DIAMOND_API_PORT` | `8000` | Preferred FastAPI port (auto-fallback to OS-assigned if busy) |
| `DIAMOND_WEB_PORT` | `3000` | Preferred Next.js port (same fallback) |
| `DIAMOND_DESKTOP_LOG` | `INFO` | Python logging level for launcher diagnostics |

CLI flags (override env):

```
diamond-desktop --dev              # connect to running dev.bat servers
diamond-desktop --no-tray          # disable system tray icon
diamond-desktop --port-api 8080
diamond-desktop --port-web 3001
diamond-desktop --log-level DEBUG
```

## Troubleshooting

### Window opens but stays on splash forever

Sidecar boot is timing out (default 45s). Check the launcher log:

```bash
set DIAMOND_DESKTOP_LOG=DEBUG
python -m diamond.desktop
```

Common causes:
- `node` not on PATH → install Node.js 20+
- `web/.next/standalone/` doesn't exist → run `python scripts/build_desktop.py`
- Antivirus quarantining `node.exe` → whitelist or reinstall Node

### "Another Diamond instance is running"

Single-instance mutex held by an existing process. The launcher tries
to focus the existing window. If no window appears, the prior
launcher crashed without releasing — kill it from Task Manager
("Diamond" or `python.exe`) and relaunch.

### Stale `node.exe` on :3000 after a crash

Should never happen with the Job Object active — but if it does
(VM hibernation has been observed to break Job Object kill-on-close),
fall back to the dev-path recovery:

```bash
kill-stale.bat
```

This is a rare edge case in v1; will be eliminated in v2 by Inno Setup
running a service-style cleanup on uninstall.

### Tray icon doesn't appear

Tray is best-effort and fails silently (the launcher logs the
exception at DEBUG level). Run with `--log-level DEBUG` to see the
underlying error. Most common: pystray not installed (`pip install -e ".[desktop]"`).

### "Application error" on the splash

The boot thread caught an exception and called `window.load_html(error_html)`.
The error message is rendered inside the window. Common causes are
listed in DECISIONS.md D32 "Failure modes and recovery".

### Cold start is 5+ seconds

Most of that is Next.js standalone boot. Optimization paths (deferred
to v2):
- Pre-warm the API thread before opening the window
- Pin the standalone server to a smaller route subset
- Bundle Node and use `pkg`-style snapshot

## Distribution (deferred)

Not in scope for D32 ship; tracked in BACKLOG.md:

- **Code signing** — Windows SmartScreen friendliness, Authenticode cert
- **Installer** — Inno Setup script that wraps `dist/Diamond/` into a single MSI / EXE installer with Start Menu shortcut + uninstall entry
- **Auto-update** — Tauri-style updater (download patch, swap binaries, relaunch)
- **Cross-platform** — Mac (Cocoa via PySide6) and Linux (GTK via PySide6); Tauri becomes more attractive at that point

## When to NOT use the desktop shell

- **Engineering hot-reload** — use `dev.bat` instead. The desktop shell uses production builds; you don't get instant Next.js refresh.
- **Headless / CI** — the smoke test (`make smoke`) and CLI commands (`diamond ingest`, etc.) don't need a window. Keep using those directly.
- **Multi-window analytics** — open Metabase Workshop in a real browser tab if you want spillover screen real estate. The PySide6 window is intentionally single-instance single-window.
