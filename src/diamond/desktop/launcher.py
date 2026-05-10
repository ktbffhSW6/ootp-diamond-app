"""Diamond desktop launcher — entry point for the native shell.

Run modes:

    python -m diamond.desktop          # source mode, dev path
    diamond-desktop                    # console-script entry (same)
    Diamond.exe                        # PyInstaller-frozen prod build

Architecture (single-window-morph, PySide6 + QtWebEngine):

    1. Parse CLI flags (--dev, --no-tray, --port-api, --port-web).
    2. Acquire single-instance mutex (focus existing window if held).
    3. Create Job Object (Windows) so kids die with launcher.
    4. Construct QApplication + QMainWindow + QWebEngineView. Load
       the splash HTML at the final window size. The user sees a
       polished loading screen instantly.
    5. Start a background "boot" thread that:
         - launches uvicorn + Next.js (sidecar.start_sidecars)
         - on success, signals the main thread to load the main URL
         - on failure, signals the main thread to render the error HTML
    6. Optionally start the tray icon thread.
    7. Block on app.exec() — the Qt event loop. Returns when window
       closes.
    8. On window close: stop sidecars, release lock, exit.

Why PySide6 directly (not pywebview): pywebview pulls `pythonnet` as
a hard Windows dependency, which has no Python 3.14 wheel and can't
build from source without the .NET toolchain. PySide6 ships an
`abi3` wheel that works across Python versions. As a bonus, Qt
brings its own Chromium so end-users don't need the Microsoft
WebView2 runtime installed.

Cross-thread signal pattern: Qt widgets must only be touched from
the GUI thread. The boot thread can't call `view.load(url)` directly.
We use a custom QObject (`_BootSignals`) with `urlReady` and
`errorReady` Qt signals; the main thread connects slots on those
signals to the actual widget updates. Qt auto-marshals the call.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Callable, Optional


# ---- pythonw.exe stdio guard (must run BEFORE any other import that
#      might write to stdout/stderr) ---------------------------------
#
# When launched via Diamond.vbs or as Diamond.exe, the process has no
# console allocated; sys.stdout / sys.stderr are None. Any library
# that does `sys.stderr.isatty()` or `print(...)` then crashes with
# AttributeError. uvicorn's default log config hits this immediately
# ("Unable to configure formatter 'default'"); pystray, click, and
# other transitive deps can hit it too.
#
# Solution: assign null sinks to stdout/stderr (so writes succeed and
# disappear), and tee real diagnostic output to a log file the user
# can read for debugging.

def _ensure_stdio() -> Path | None:
    """Reroute None stdio to a debug log file under %LOCALAPPDATA%."""
    if sys.stdout is not None and sys.stderr is not None:
        return None  # console-mode launch (python -m diamond.desktop)
    log_dir = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "Diamond"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None
    log_path = log_dir / "launcher.log"
    try:
        # Truncate to 1MB if the log gets big.
        if log_path.exists() and log_path.stat().st_size > 1_000_000:
            log_path.write_text("", encoding="utf-8")
        sink = open(log_path, "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = sink
        if sys.stderr is None:
            sys.stderr = sink
        return log_path
    except Exception:
        # Last resort: discard everything so libraries don't crash.
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")
        return None


_LAUNCHER_LOG_PATH = _ensure_stdio()


from diamond.desktop import paths, sidecar, splash  # noqa: E402  (after _ensure_stdio)


log = logging.getLogger("diamond.desktop")

WINDOW_TITLE = "Diamond — Building the Green Monster"


# ---- platform-specific helpers (Windows job object + single-instance) -------


def _acquire_single_instance_or_focus() -> Optional[object]:
    """Return a held mutex handle, or None if another instance is running."""
    if sys.platform != "win32":
        return object()
    try:
        from diamond.desktop import single_instance
    except Exception:
        log.debug("single_instance module unavailable", exc_info=True)
        return object()

    handle = single_instance.acquire()
    if handle is None:
        single_instance.try_focus_existing()
        return None
    return handle


def _create_job_object() -> Optional[object]:
    """Return a Windows Job Object handle, or None when unavailable."""
    if sys.platform != "win32":
        return None
    try:
        from diamond.desktop import win_jobobject
    except Exception:
        log.debug("win_jobobject module unavailable", exc_info=True)
        return None
    try:
        return win_jobobject.create_kill_on_close_job()
    except Exception:
        log.warning("failed to create Job Object — children may outlive launcher", exc_info=True)
        return None


# ---- main flow --------------------------------------------------------------


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="diamond-desktop")
    p.add_argument(
        "--dev",
        action="store_true",
        help="Skip the standalone-build check and load the running dev "
        "server instead (assumes `dev.bat` is up). For desktop UI iteration.",
    )
    p.add_argument("--no-tray", action="store_true", help="Disable the system tray icon.")
    p.add_argument(
        "--port-api",
        type=int,
        default=int(os.environ.get("DIAMOND_API_PORT", "8000")),
    )
    p.add_argument(
        "--port-web",
        type=int,
        default=int(os.environ.get("DIAMOND_WEB_PORT", "3000")),
    )
    p.add_argument(
        "--log-level",
        default=os.environ.get("DIAMOND_DESKTOP_LOG", "INFO"),
        help="Python logging level for launcher diagnostics.",
    )
    return p.parse_args(argv)


def _error_html(message: str) -> str:
    """Render a fatal-error screen inside the existing window."""
    safe = (
        message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    return f"""\
<!doctype html><html><head><meta charset="utf-8"><title>Diamond — error</title>
<style>
html,body{{margin:0;height:100%;background:#1a0e0e;color:#fee;
font-family:-apple-system,Segoe UI,Roboto,sans-serif;
display:flex;align-items:center;justify-content:center}}
.box{{max-width:640px;padding:32px;border:1px solid #6b2a2a;border-radius:8px;
background:#2a1212}}
h1{{margin:0 0 12px;font-size:18px;color:#ffb4b4}}
pre{{margin:0;white-space:pre-wrap;font-size:12px;color:#fcc;
background:#1a0808;padding:12px;border-radius:6px}}
.hint{{margin-top:14px;font-size:12px;color:#caa}}
</style></head><body>
<div class="box">
  <h1>Diamond couldn't start.</h1>
  <pre>{safe}</pre>
  <div class="hint">Close this window and check the launcher logs. If the
  problem persists, run <code>dev.bat</code> from a terminal to see live logs.</div>
</div></body></html>
"""


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    # `force=True` lets us reconfigure if anything else already touched
    # the root logger (uvicorn / httpx import-time noise, etc.). The
    # handler writes to whatever sys.stderr resolves to — under pythonw
    # that's now the log file we set up in _ensure_stdio() above.
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    if _LAUNCHER_LOG_PATH is not None:
        log.info("launcher log: %s", _LAUNCHER_LOG_PATH)

    # 1. Single-instance lock.
    instance_handle = _acquire_single_instance_or_focus()
    if instance_handle is None:
        log.info("another Diamond instance is running — focused it instead.")
        return 0

    # 2. Job Object.
    job_handle = _create_job_object()

    # 3. Qt application + main window. PySide6 ships its own Chromium
    #    via QtWebEngine — no Microsoft WebView2 runtime needed on
    #    the end-user machine.
    from PySide6.QtCore import QObject, QUrl, Qt, Signal
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QMainWindow

    # High-DPI handling: Qt 6 enables this automatically; we just need
    # to opt into rounded device-pixel-ratio scaling for crisp text on
    # 125%/150% Windows scale factors.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Diamond")
    app.setOrganizationName("Diamond")

    view = QWebEngineView()
    # Opt-in browser features the Diamond UI may rely on:
    s = view.settings()
    s.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

    view.setHtml(splash.html())

    win = QMainWindow()
    win.setWindowTitle(WINDOW_TITLE)
    win.setCentralWidget(view)
    win.resize(1600, 1000)
    win.setMinimumSize(1100, 700)
    win.show()

    # 4. Cross-thread signaling. Boot thread emits; slots in this
    #    main thread run on the GUI thread (Qt auto-marshals).
    class _BootSignals(QObject):
        urlReady = Signal(str)
        errorReady = Signal(str)

    signals = _BootSignals()
    signals.urlReady.connect(lambda u: view.load(QUrl(u)))
    signals.errorReady.connect(lambda html: view.setHtml(html))

    # 5. Boot thread — load sidecars, then signal the morph.
    handles_box: dict[str, Optional[sidecar.SidecarHandles]] = {"h": None}

    def _boot() -> None:
        try:
            if args.dev:
                if not sidecar._wait_for_port(args.port_api, timeout=5.0):  # noqa: SLF001
                    raise RuntimeError(
                        f"FastAPI not running on :{args.port_api} (run dev.bat first)."
                    )
                if not sidecar._wait_for_port(args.port_web, timeout=5.0):  # noqa: SLF001
                    raise RuntimeError(
                        f"Next.js not running on :{args.port_web} (run dev.bat first)."
                    )
                api_port, web_port = args.port_api, args.port_web
            else:
                handles = sidecar.start_sidecars(
                    api_port_pref=args.port_api,
                    web_port_pref=args.port_web,
                    job_handle=job_handle,
                )
                handles_box["h"] = handles
                api_port, web_port = handles.api_port, handles.web_port

            url = f"http://127.0.0.1:{web_port}"
            log.info("sidecars ready (api=%s, web=%s) — loading %s", api_port, web_port, url)
            signals.urlReady.emit(url)
        except Exception as exc:
            log.exception("boot failed")
            signals.errorReady.emit(_error_html(str(exc)))

    boot_thread = threading.Thread(target=_boot, name="diamond-boot", daemon=True)
    boot_thread.start()

    # 6. Optional tray. Daemon thread; can outlive nothing critical.
    tray_stop: Optional[Callable[[], None]] = None
    if not args.no_tray:
        try:
            from diamond.desktop import tray

            tray_stop = tray.start(
                main_url=f"http://127.0.0.1:{args.port_web}",
                api_url=f"http://127.0.0.1:{args.port_api}",
                on_quit=lambda: app.quit(),
            )
        except Exception:
            log.debug("tray unavailable", exc_info=True)

    # 7. Cleanup on app exit (window closed / tray quit / OS signal).
    def _cleanup() -> None:
        log.info("shutting down sidecars")
        h = handles_box["h"]
        if h is not None:
            try:
                sidecar.stop_sidecars(h)
            except Exception:
                log.exception("stop_sidecars raised")
        if tray_stop is not None:
            try:
                tray_stop()
            except Exception:
                log.debug("tray stop failed", exc_info=True)

    app.aboutToQuit.connect(_cleanup)

    # 8. Block on Qt event loop.
    try:
        rc = app.exec()
    finally:
        # Belt-and-suspenders: cleanup runs via aboutToQuit normally.
        h = handles_box["h"]
        if h is not None and getattr(h, "web_proc", None):
            try:
                sidecar.stop_sidecars(h)
            except Exception:
                pass

    log.info("Diamond exited cleanly")
    return int(rc)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
