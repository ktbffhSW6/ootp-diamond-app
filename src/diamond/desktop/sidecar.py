"""Sidecar process management — uvicorn (in-thread) + Next.js (subprocess).

Two halves:

- **API**: uvicorn runs in a daemon thread, in-process. Works in both
  source and frozen modes (no need for ``python.exe`` on PATH inside a
  PyInstaller bundle).

- **Web**: Next.js standalone server runs as a hidden subprocess via
  ``node server.js``. Requires ``node`` on PATH; a friendly error is
  surfaced if it's missing.

Both bind to 127.0.0.1 (localhost-only, never reachable from the
network). Ports are configurable via env (``DIAMOND_API_PORT``,
``DIAMOND_WEB_PORT``); defaults are 8000 / 3000 to match dev.

A readiness probe blocks the launcher until both ports accept TCP
connections, with a sensible timeout (~30s — Next.js cold start
dominates).
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from diamond.desktop import paths

log = logging.getLogger(__name__)


# Windows: hide the console window of spawned children.
# 0x08000000 = CREATE_NO_WINDOW. Equivalent to start /b for cmd, but
# applied to the actual CreateProcess call so even a child that tries
# to AllocConsole gets nothing.
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


@dataclass
class SidecarHandles:
    """References to running sidecars, exposed to the launcher.

    The ``api_thread`` runs uvicorn; it's a daemon thread so it dies
    with the process. The ``web_proc`` is a real OS process and must
    be terminated explicitly on shutdown.
    """

    api_thread: threading.Thread
    web_proc: subprocess.Popen[bytes]
    api_port: int
    web_port: int


def _free_port(preferred: int) -> int:
    """Return ``preferred`` if free, else an OS-assigned port.

    Bind+close pattern; race-free enough for our single-user desktop
    case. Two simultaneous launches are blocked by the single-instance
    mutex anyway.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", preferred))
        return preferred
    except OSError:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 30.0) -> bool:
    """Block until a TCP connect to 127.0.0.1:port succeeds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def _start_uvicorn_thread(port: int) -> threading.Thread:
    """Run uvicorn in a daemon thread.

    We import uvicorn lazily so the ``diamond`` package doesn't take
    a hard import-time dep on it during CLI use (uvicorn is already a
    runtime dep, but lazy import keeps cold-start CLI fast).
    """
    import uvicorn  # noqa: WPS433

    config = uvicorn.Config(
        "diamond.api.app:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",  # quieter than dev; the desktop user has no console
        access_log=False,
        # No reload — that's a dev-only feature that conflicts with PyInstaller.
        reload=False,
        workers=1,
    )
    server = uvicorn.Server(config)

    def _run() -> None:
        try:
            server.run()
        except Exception:  # pragma: no cover — surfaced via logs only
            log.exception("uvicorn thread crashed")

    t = threading.Thread(target=_run, name="diamond-api", daemon=True)
    t.start()
    return t


def _start_next_subprocess(
    port: int,
    *,
    job_handle: Optional[object] = None,
) -> subprocess.Popen[bytes]:
    """Spawn the Next.js production server, hidden, on the given port.

    Two paths, in order of preference:

    1. **Standalone tree** at ``web/.next/standalone/server.js`` —
       self-contained mini-bundle from `next build` with
       ``output: 'standalone'``. Only ``node`` is needed on PATH;
       the bundle's own minimal ``node_modules`` ships beside the
       entry. This is the path PyInstaller-frozen builds use.

    2. **`next start` fallback** — runs ``node web/node_modules/next/
       dist/bin/next start --port N`` from the repo's ``web/``. Used
       when the standalone tree is missing or broken (common on
       Windows + pnpm because `next build` can't always create the
       symlinks the standalone tree needs without Developer Mode).

    Both paths produce identical runtime behavior. The standalone
    path is preferred for shipping; `next start` is preferred for
    local dev where the user may not have flipped Developer Mode
    on.

    If ``job_handle`` is given (Windows), the child is added to the
    Job Object so it dies with the launcher.
    """
    if paths.web_standalone_ok():
        cwd = paths.web_standalone_dir()
        cmd = ["node", str(paths.web_server_entry())]
        log.info("next: using standalone build at %s", cwd)
    else:
        next_bin = paths.web_next_bin()
        if not next_bin.exists():
            raise FileNotFoundError(
                "Next.js not found at "
                f"{next_bin}.\n"
                "Run `cd web && pnpm install && pnpm run build` first "
                "(or `npm install && npm run build`)."
            )
        cwd = paths.web_repo_dir()
        cmd = [
            "node",
            str(next_bin),
            "start",
            "--port",
            str(port),
            "--hostname",
            "127.0.0.1",
        ]
        log.info("next: using `next start` fallback (no standalone tree)")

    # The standalone server reads PORT and HOSTNAME from env; the
    # `next start` path uses CLI flags. Setting env covers both.
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["HOSTNAME"] = "127.0.0.1"
    env["NODE_ENV"] = "production"

    try:
        proc = subprocess.Popen(  # noqa: S603 — argv list, no shell
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=_CREATE_NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "`node` was not found on PATH. Install Node.js 20+ "
            "(https://nodejs.org/) and relaunch Diamond."
        ) from exc

    if job_handle is not None and sys.platform == "win32":
        from diamond.desktop import win_jobobject

        win_jobobject.assign_process(job_handle, proc.pid)

    return proc


def start_sidecars(
    *,
    api_port_pref: int = 8000,
    web_port_pref: int = 3000,
    job_handle: Optional[object] = None,
    boot_timeout: float = 45.0,
) -> SidecarHandles:
    """Boot both sidecars and wait for readiness."""
    api_port = _free_port(api_port_pref)
    web_port = _free_port(web_port_pref)

    log.info("starting api on 127.0.0.1:%s (in-thread)", api_port)
    api_thread = _start_uvicorn_thread(api_port)

    log.info("starting web on 127.0.0.1:%s (subprocess)", web_port)
    web_proc = _start_next_subprocess(web_port, job_handle=job_handle)

    if not _wait_for_port(api_port, timeout=boot_timeout):
        raise RuntimeError(f"FastAPI did not bind 127.0.0.1:{api_port} within {boot_timeout}s")
    if not _wait_for_port(web_port, timeout=boot_timeout):
        raise RuntimeError(f"Next.js did not bind 127.0.0.1:{web_port} within {boot_timeout}s")

    return SidecarHandles(
        api_thread=api_thread,
        web_proc=web_proc,
        api_port=api_port,
        web_port=web_port,
    )


def stop_sidecars(handles: SidecarHandles, *, grace: float = 3.0) -> None:
    """Best-effort orderly shutdown.

    Web subprocess gets a terminate, then a kill on grace timeout.
    The API thread is daemon and dies when the process exits — we
    don't try to gracefully drain it (no in-flight HTTP at quit time
    in normal use).
    """
    if handles.web_proc.poll() is None:
        try:
            handles.web_proc.terminate()
            handles.web_proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            try:
                handles.web_proc.kill()
            except Exception:
                pass
        except Exception:
            pass
    # api_thread: daemon — interpreter exit cleans it up.
