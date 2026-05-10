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
#
# CREATE_NO_WINDOW (0x08000000) prevents the OS from allocating a
# console for the child. That's the canonical flag, but for
# console-subsystem executables (`node.exe`, `java.exe`) Windows can
# still briefly flash a window during CreateProcess on some versions
# (Win10 builds < 1903, Win11 with certain DPI settings). The
# bulletproof recipe combines:
#
#   creationflags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
#   startupinfo with STARTF_USESHOWWINDOW + wShowWindow = SW_HIDE
#
# CREATE_NEW_PROCESS_GROUP isolates the child's signal handling
# (Ctrl+C in our process doesn't propagate to children, which we
# want so the user closing Diamond doesn't accidentally orphan
# anything).
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_CREATE_NEW_PROCESS_GROUP = 0x00000200 if sys.platform == "win32" else 0
_HIDDEN_FLAGS = _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP


def _hidden_startupinfo():
    """Build a STARTUPINFO that fully suppresses any window flash.

    Combined with CREATE_NO_WINDOW in creationflags, this is the
    Win32 recipe for "really, truly no window — not even briefly".
    Returns None on non-Windows where the field is unused.
    """
    if sys.platform != "win32":
        return None
    si = subprocess.STARTUPINFO()
    # STARTF_USESHOWWINDOW = 0x00000001
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    # SW_HIDE = 0
    si.wShowWindow = 0
    return si


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
            creationflags=_HIDDEN_FLAGS,
            startupinfo=_hidden_startupinfo(),
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


def _resolve_java_exe(metabase_dir: Path) -> Optional[Path]:
    """Find java.exe. Tries, in order:

    1. ``JDK_HOME`` env var + ``\\bin\\java.exe``
    2. ``JAVA_HOME`` env var + ``\\bin\\java.exe``
    3. The ``set "JDK_HOME=..."`` line parsed out of metabase.bat
       (so the user's bat is the single source of truth)
    4. ``java`` / ``java.exe`` resolved via ``shutil.which`` on PATH
    """
    candidates: list[Path] = []
    for env_key in ("JDK_HOME", "JAVA_HOME"):
        v = os.environ.get(env_key)
        if v:
            candidates.append(Path(v) / "bin" / "java.exe")

    metabase_bat = metabase_dir / "metabase.bat"
    if metabase_bat.exists():
        try:
            for line in metabase_bat.read_text(encoding="utf-8", errors="ignore").splitlines():
                # `set "JDK_HOME=C:\Program Files\Microsoft\jdk-21..."`
                stripped = line.strip()
                if stripped.lower().startswith("set ") and "jdk_home=" in stripped.lower():
                    # Extract value between first `=` and trailing `"`
                    try:
                        kv = stripped.split("=", 1)[1]
                        if kv.endswith('"'):
                            kv = kv[:-1]
                        candidates.append(Path(kv) / "bin" / "java.exe")
                    except Exception:
                        pass
                    break
        except Exception:
            pass

    import shutil

    on_path = shutil.which("java") or shutil.which("java.exe")
    if on_path:
        candidates.append(Path(on_path))

    for c in candidates:
        if c.exists():
            return c
    return None


def _start_metabase_subprocess(
    *,
    job_handle: Optional[object] = None,
) -> Optional[subprocess.Popen[bytes]]:
    """Spawn Metabase by invoking ``java.exe`` directly.

    We deliberately don't go through ``metabase.bat`` because:

    - The .bat's ``/b`` mode uses ``start /b ...`` which detaches Java
      from our process tree (defeats Job Object inheritance).
    - The .bat's foreground mode runs Java as a child of cmd.exe with
      stdout going to the inherited stdout — when we set DEVNULL,
      Java's startup messages are lost and we have no visibility into
      what's happening if it doesn't come up.

    Direct invocation gives us:
      - Java as a direct child of our Python launcher (clean Job
        Object inheritance)
      - Java's stdout+stderr captured to ``logs/diamond-launcher.log``
        so the user / future-us can debug startup failures
      - Identical env vars to what metabase.bat sets (we mirror the
        config rather than parse the .bat for them — easier to reason
        about than line-by-line .bat parsing)

    Returns None (no raise) when:
      - Metabase isn't installed yet (no metabase.jar) — the Workshop
        tab will show the install guide
      - Port 3001 already in use — assume user kept Metabase running
        from a prior session; don't double-spawn
      - Java not found — spawn fails gracefully
      - Any other exception — logged, Diamond boots normally
    """
    metabase_dir = Path.home() / ".diamond" / "metabase"
    metabase_jar = metabase_dir / "metabase.jar"

    if not metabase_jar.exists():
        log.info(
            "metabase: %s not found — skipping (run `metabase.bat` once "
            "manually for first-time setup, see docs/METABASE.md)",
            metabase_jar,
        )
        return None

    if _port_in_use(3001):
        log.info("metabase: already running on :3001 — skipping spawn")
        return None

    java_exe = _resolve_java_exe(metabase_dir)
    if java_exe is None:
        log.warning(
            "metabase: no java.exe found (set JDK_HOME or JAVA_HOME, or "
            "install Microsoft OpenJDK 21) — skipping spawn"
        )
        return None

    logs_dir = metabase_dir / "logs"
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    metabase_log = logs_dir / "diamond-launcher.log"

    # Mirror the env config from metabase.bat. The launcher is the
    # single source of truth for these from D32 forward; the .bat
    # remains as a fallback for users running Metabase manually.
    env = os.environ.copy()
    env.update({
        "MB_JETTY_HOST": "127.0.0.1",
        "MB_JETTY_PORT": "3001",
        "MB_DB_TYPE": "h2",
        "MB_DB_FILE": str(metabase_dir / "data" / "metabase"),
        "MB_PLUGINS_DIR": str(metabase_dir / "plugins"),
        "MB_ANON_TRACKING_ENABLED": "false",
        "MB_CHECK_FOR_UPDATES": "false",
        "MB_LOAD_SAMPLE_CONTENT": "false",
    })

    cmd = [str(java_exe), "-Xmx2g", "-jar", str(metabase_jar)]
    log.info(
        "metabase: starting java directly (jar=%s, log=%s)",
        metabase_jar,
        metabase_log,
    )

    try:
        # Open the log in append mode so successive Diamond launches
        # accumulate history (truncated by metabase itself if it grows
        # too large via its own log4j rotation).
        log_fh = open(metabase_log, "ab", buffering=0)
        proc = subprocess.Popen(  # noqa: S603 — argv list, no shell
            cmd,
            cwd=str(metabase_dir),
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=_HIDDEN_FLAGS,
            startupinfo=_hidden_startupinfo(),
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
    """No-op on Windows; Job Object handles termination atomically.

    Originally we called terminate() + wait(grace) on each child.
    Two problems with that:

    1. Sequential 3+3=6 seconds of waiting before the launcher exits,
       making the close-window action feel sluggish.
    2. Each terminate() can briefly flash a console window for the
       dying child on Windows (the OS allocates a transient surface
       during process shutdown). With Node + Java + their own helper
       subprocesses, that's 6-7 brief flashes during quit.

    The Job Object's KILL_ON_JOB_CLOSE flag (D32) reaps every
    descendant atomically when the launcher process exits — same
    end state, instant, silent. We rely on that path entirely now.

    The ``grace`` arg is kept for compatibility with the (legacy)
    ``--dev`` mode where we don't own the children. Currently unused.
    """
    # Nothing to do — Job Object closure on launcher exit will kill
    # web_proc + metabase_proc + their descendants. api_thread is
    # daemon and dies with the interpreter.
    del handles, grace
