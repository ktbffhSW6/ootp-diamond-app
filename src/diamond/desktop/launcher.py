"""Diamond desktop launcher — entry point for the native shell.

Run modes:

    python -m diamond.desktop          # source mode, dev path
    diamond-desktop                    # console-script entry (same)
    Diamond.exe                        # PyInstaller-frozen prod build

Architecture (single-window-morph):

    1. Parse CLI flags (--dev, --no-tray, --port-api, --port-web).
    2. Acquire single-instance mutex (focus existing window if held).
    3. Create Job Object (Windows) so kids die with launcher.
    4. Create the ONE pywebview window with splash HTML and the final
       window size. The user sees a polished loading screen instantly.
    5. Start a background "boot" thread that:
         - launches uvicorn + Next.js (sidecar.start_sidecars)
         - on success, calls window.load_url(main_url) — atomic swap
         - on failure, calls window.load_html(error_html) + logs
    6. Optionally start the tray icon thread.
    7. Call webview.start() — blocks on GUI loop until window closed.
    8. On window close: stop sidecars, release lock, exit.

pywebview's ``window.load_url`` is thread-safe (posts to the GUI
thread internally), so the boot thread can drive the morph without
any explicit synchronization with the main thread.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from typing import Callable, Optional

from diamond.desktop import paths, sidecar, splash


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


# ---- WebView2 runtime check (Windows) ---------------------------------------


def _check_webview2_or_warn() -> bool:
    """Detect Microsoft WebView2 runtime; show a fixable error if missing.

    pywebview on Windows uses Edge Chromium WebView2. Bundled with
    Windows 11; Windows 10 may not have it. If absent, pywebview will
    fail to render and the user sees a confusing error. We pre-check
    via the registry and surface a friendly message with the install
    URL.

    Returns True if WebView2 is present (or check is unavailable —
    we'd rather attempt boot than block on a false negative).
    """
    if sys.platform != "win32":
        return True
    try:
        import winreg  # type: ignore
    except Exception:
        return True

    # Per-machine and per-user install locations.
    keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
    ]
    for hive, sub in keys:
        try:
            with winreg.OpenKey(hive, sub) as k:
                version, _ = winreg.QueryValueEx(k, "pv")
                if version and version != "0.0.0.0":
                    log.debug("WebView2 found: %s", version)
                    return True
        except OSError:
            continue

    msg = (
        "Microsoft WebView2 runtime is not installed.\n\n"
        "Diamond uses WebView2 to render its UI. Install it from:\n"
        "https://developer.microsoft.com/microsoft-edge/webview2/\n\n"
        "After installing, relaunch Diamond."
    )
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, msg, "Diamond — WebView2 required", 0x10)
    except Exception:
        log.error(msg)
    return False


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
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # 1. Single-instance lock.
    instance_handle = _acquire_single_instance_or_focus()
    if instance_handle is None:
        log.info("another Diamond instance is running — focused it instead.")
        return 0

    # 2. WebView2 sanity check (Windows).
    if not _check_webview2_or_warn():
        return 3

    # 3. Job Object.
    job_handle = _create_job_object()

    # 4. Create the (one) window with splash HTML at final size.
    import webview

    window = webview.create_window(
        title=WINDOW_TITLE,
        html=splash.html(),
        width=1600,
        height=1000,
        min_size=(1100, 700),
        confirm_close=False,
        background_color="#0b1220",
    )

    # 5. Boot thread — load sidecars, then morph window URL.
    handles_box: dict[str, Optional[sidecar.SidecarHandles]] = {"h": None}

    def _boot() -> None:
        try:
            if args.dev:
                # Dev mode: assume dev.bat is up; just check ports.
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
            try:
                window.load_url(url)
            except Exception:
                log.exception("window.load_url failed")
        except Exception as exc:
            log.exception("boot failed")
            try:
                window.load_html(_error_html(str(exc)))
            except Exception:
                pass

    boot_thread = threading.Thread(target=_boot, name="diamond-boot", daemon=True)
    boot_thread.start()

    # 6. Optional tray.
    tray_stop: Optional[Callable[[], None]] = None
    if not args.no_tray:
        try:
            from diamond.desktop import tray

            tray_stop = tray.start(
                main_url=f"http://127.0.0.1:{args.port_web}",
                api_url=f"http://127.0.0.1:{args.port_api}",
                on_quit=_request_quit,
            )
        except Exception:
            log.debug("tray unavailable", exc_info=True)

    # 7. Cleanup hook fires on window close.
    def _on_closed() -> None:
        log.info("main window closed — shutting down sidecars")
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

    window.events.closed += _on_closed

    # 8. GUI loop. Blocks until window closes.
    try:
        webview.start(private_mode=False, http_server=False)
    finally:
        # Belt-and-suspenders for callback skips.
        h = handles_box["h"]
        if h is not None:
            try:
                sidecar.stop_sidecars(h)
            except Exception:
                pass

    log.info("Diamond exited cleanly")
    return 0


# ---- helpers ----------------------------------------------------------------


def _request_quit() -> None:
    """Tray-initiated quit. Closes every pywebview window which
    triggers the closed-event handlers and unwinds the GUI loop."""
    try:
        import webview

        for w in list(webview.windows):
            try:
                w.destroy()
            except Exception:
                pass
    except Exception:
        log.debug("quit request raised", exc_info=True)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
