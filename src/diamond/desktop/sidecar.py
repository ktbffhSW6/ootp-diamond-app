"""Sidecar process management — uvicorn (in-thread) + Next.js + Metabase.

Three halves:

- **API**: uvicorn runs in a daemon thread, in-process. Works in both
  source and frozen modes (no need for ``python.exe`` on PATH inside a
  PyInstaller bundle).

- **Web**: Next.js standalone server runs as a hidden subprocess via
  ``node server.js``. Requires ``node`` on PATH; a friendly error is
  surfaced if it's missing.

- **Metabase** (D31 / D32 ext): launched if ``~/.diamond/metabase/
  metabase.bat`` exists. Joined to the Windows Job Object so it dies
  with Diamond. Skipped if port 3001 is already in use (assumes user
  has Metabase running manually from a prior session). Best-effort —
  if Metabase fails to spawn, the rest of Diamond still boots and
  the Workshop tab shows its cold-start guide.

All three bind to 127.0.0.1 (localhost-only, never reachable from the
network). Ports are configurable via env (``DIAMOND_API_PORT``,
``DIAMOND_WEB_PORT``); defaults are 8000 / 3000 to match dev.
Metabase always uses 3001 (D31 fixed port).

A readiness probe blocks the launcher until API + Web ports accept
TCP connections (~30s — Next.js cold start dominates). Metabase is
fire-and-forget — it takes ~30s on its own and the Workshop UI
polls ``/api/admin/metabase-status`` to morph from "starting" to
"ready" without blocking the cockpit.
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
    with the process. ``web_proc`` and ``metabase_proc`` are real OS
    processes and must be terminated explicitly on shutdown.

    ``metabase_proc`` is None when Metabase is not installed, was
    skipped because it's already running, or failed to spawn — in
    all cases the launcher continues without it.
    """

    api_thread: threading.Thread
    web_proc: subprocess.Popen[bytes]
    metabase_proc: Optional[subprocess.Popen[bytes]]
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


def _port_in_use(port: int) -> bool:
    """One-shot check — True if something is already listening."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
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
        # log_config=None disables uvicorn's logging.config.dictConfig call.
        # uvicorn's default config registers formatters that call
        # sys.stderr.isatty() during init, which crashes under pythonw.exe
        # where sys.stderr is None ("Unable to configure formatter 'default'").
        # Our launcher's own logging.basicConfig handles output.
        log_config=None,
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


def _start_metabase_subprocess(
    *,
    job_handle: Optional[object] = None,
) -> Optional[subprocess.Popen[bytes]]:
    """Spawn Metabase via ``~/.diamond/metabase/metabase.bat``.

    Returns ``None`` (without raising) in any of these cases:

    - Metabase isn't installed (the .bat doesn't exist) — the user
      hasn't gone through the one-time D31 setup. Workshop tab will
      show the install guide.
    - Port 3001 is already in use — something is already listening,
      most likely a Metabase from a prior session the user kept up.
      We assume that's intentional and don't double-spawn.
    - Spawn fails for any other reason — logged at WARNING; rest of
      Diamond boots normally.

    When successful, returns the Popen handle. The bat is invoked
    WITHOUT the ``/b`` flag (which would `start /b` and detach Java
    from our process tree). Foreground invocation keeps Java as a
    descendant of our launcher, so the Job Object kill-on-close can
    take it down with Diamond.
    """
    metabase_dir = Path.home() / ".diamond" / "metabase"
    metabase_bat = metabase_dir / "metabase.bat"

    if not metabase_bat.exists():
        log.info(
            "metabase: %s not found — skipping (Workshop tab will show install guide)",
            metabase_bat,
        )
        return None

    if _port_in_use(3001):
        log.info("metabase: already running on :3001 — skipping spawn")
        return None

    log.info("metabase: starting via %s (foreground; joins Job Object)", metabase_bat)
    try:
        # cmd /c invokes the .bat synchronously inside cmd.exe; java
        # spawns as a child of cmd. Both end up as descendants of our
        # Python launcher and inherit Job Object membership — so
        # KILL_ON_JOB_CLOSE takes the entire tree down with Diamond.
        proc = subprocess.Popen(  # noqa: S603 — argv list, no shell
            ["cmd.exe", "/c", str(metabase_bat)],
            cwd=str(metabase_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=_CREATE_NO_WINDOW,
        )
    except Exception as exc:
        log.warning("metabase: spawn failed (%s) — Workshop tab unaffected", exc)
        return None

    if job_handle is not None and sys.platform == "win32":
        try:
            from diamond.desktop import win_jobobject

            win_jobobject.assign_process(job_handle, proc.pid)
        except Exception:
            log.debug("metabase: Job Object assignment failed", exc_info=True)
    return proc


def start_sidecars(
    *,
    api_port_pref: int = 8000,
    web_port_pref: int = 3000,
    job_handle: Optional[object] = None,
    boot_timeout: float = 45.0,
) -> SidecarHandles:
    """Boot all sidecars and wait for FastAPI + Next.js readiness.

    Metabase is fire-and-forget — it takes ~30s on its own and the
    Workshop UI polls liveness so we don't block the cockpit on it.
    """
    api_port = _free_port(api_port_pref)
    web_port = _free_port(web_port_pref)

    log.info("starting api on 127.0.0.1:%s (in-thread)", api_port)
    api_thread = _start_uvicorn_thread(api_port)

    log.info("starting web on 127.0.0.1:%s (subprocess)", web_port)
    web_proc = _start_next_subprocess(web_port, job_handle=job_handle)

    # Metabase boots in parallel; we don't gate the cockpit on it.
    metabase_proc = _start_metabase_subprocess(job_handle=job_handle)

    if not _wait_for_port(api_port, timeout=boot_timeout):
        raise RuntimeError(f"FastAPI did not bind 127.0.0.1:{api_port} within {boot_timeout}s")
    if not _wait_for_port(web_port, timeout=boot_timeout):
        raise RuntimeError(f"Next.js did not bind 127.0.0.1:{web_port} within {boot_timeout}s")

    return SidecarHandles(
        api_thread=api_thread,
        web_proc=web_proc,
        metabase_proc=metabase_proc,
        api_port=api_port,
        web_port=web_port,
    )


def stop_sidecars(handles: SidecarHandles, *, grace: float = 3.0) -> None:
    """Best-effort orderly shutdown.

    Each subprocess gets a terminate, then a kill on grace timeout.
    The API thread is daemon and dies when the process exits — we
    don't try to gracefully drain it (no in-flight HTTP at quit time
    in normal use).

    Note: even if this function is skipped (hard kill), the Job Object
    in win_jobobject.py guarantees the children die with the launcher
    process. This is the orderly path; the Job Object is the safety
    net.
    """
    procs = [handles.web_proc]
    if handles.metabase_proc is not None:
        procs.append(handles.metabase_proc)

    for proc in procs:
        if proc.poll() is not None:
            continue
        try:
            proc.terminate()
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
        except Exception:
            pass
    # api_thread: daemon — interpreter exit cleans it up.
