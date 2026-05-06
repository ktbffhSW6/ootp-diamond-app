"""Admin endpoint — dev-only utilities for the local-first stack.

Currently exposes:
- ``POST /api/admin/shutdown`` — kill both dev servers (Next.js :3000
  and this FastAPI :8000) so the user can quit the app from a button
  in the UI rather than closing two console windows.

Why this is OK to ship without auth: Diamond is a single-user local-
first app per D16. CORS already restricts the API to
``localhost:3000``; nothing else can hit this endpoint. When the
Phase-4 web-share path opens we'll either gate this behind a config
flag or remove it entirely depending on the deploy story.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import tempfile

from fastapi import APIRouter, HTTPException

router = APIRouter()


# Inline Python script run by a fully-detached subprocess.
#
# Two non-obvious bugs informed the current shape:
#
# A. The kill subprocess is spawned by uvicorn, which is itself a child
#    of the cmd window from api.bat. ``taskkill /F /T`` on that cmd
#    cascades through the parent-child tree and would kill the
#    subprocess mid-execution unless the subprocess fully detaches.
#    ``DETACHED_PROCESS`` alone is insufficient on Windows — we need
#    ``cmd /c start /B`` to reparent the subprocess off the dying tree.
#
# B. Even with detachment working, kill order matters: if we kill API-
#    side processes first and the detachment is partial, we cut
#    ourselves off before the web-side kills run. So we kill **web
#    side first, API side last** for defense in depth.
#
# Five-stage shutdown:
#
# 1. Web-stack ``node.exe`` processes — pnpm wrapper, the next CLI,
#    and the start-server.js worker. Pnpm's child-spawn semantics on
#    Windows often place these in their own process groups, escaping
#    ``taskkill /T`` from the cmd parent. Empirically a `pnpm dev` of
#    this project launches three node.exe processes:
#
#      a. node "...\\node_modules\\pnpm\\bin\\pnpm.cjs" dev
#      b. node "...\\node_modules\\.bin\\..\\next\\dist\\bin\\next" dev --port 3000
#      c. node "...\\node_modules\\.pnpm\\next@<ver>...\\next\\dist\\server\\lib\\start-server.js"
#
#    Process (c) is the one actually listening on :3000. The literal
#    "dev" appears in (a) and (b) but NOT (c); "next" appears in (b)
#    and (c) but NOT (a). The combined regex below catches each by a
#    stable signature: ``pnpm\.cjs`` for (a), ``node_modules.{0,500}
#    next`` for (b) and (c), plus ``next-server`` as a defensive
#    catch-all.
#
# 2. Web cmd parent (matches ``web.bat``).
#
# 3. Port :3000 — anything still listening, regardless of how it was
#    launched (manual ``pnpm dev`` from a terminal, etc.).
#
# 4. API-side python uvicorn (matches ``uvicorn ... diamond.api``).
#
# 5. API cmd parent (matches ``api.bat``) plus port :8000 mop-up.
#    Anything from this point on may kill our own subprocess via the
#    parent-child cascade if step A's detachment was partial — so it
#    runs last. Web side is already dead by then.
#
# We use PowerShell + ``Get-CimInstance Win32_Process`` rather than
# ``tasklist /V`` because tasklist's WindowTitle column reads "N/A"
# when a process was spawned from a non-console parent (the exact
# case for shells launched out of Explorer); CommandLine is always
# populated through CIM.
_KILL_SCRIPT = r"""
import subprocess
import time


def kill_matching(image_name, regex):
    # PowerShell one-liner: read every process matching the image
    # name via CIM (modern WMI replacement), filter by CommandLine
    # against the regex, emit PIDs one per line. We then run
    # taskkill /F /T on each — a separate step so partial PowerShell
    # failure doesn't block taskkill execution.
    ps_cmd = (
        f"Get-CimInstance Win32_Process -Filter \"name='{image_name}'\" | "
        f"Where-Object {{ $_.CommandLine -match '{regex}' }} | "
        "ForEach-Object { $_.ProcessId }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        capture_output=True, text=True, check=False,
        encoding="utf-8", errors="ignore",
    )
    for line in result.stdout.splitlines():
        pid = line.strip()
        if pid.isdigit():
            subprocess.run(
                ["taskkill", "/F", "/PID", pid, "/T"],
                capture_output=True,
            )


def kill_port(port):
    result = subprocess.run(
        ["netstat", "-ano"],
        capture_output=True, text=True, check=False,
        encoding="utf-8", errors="ignore",
    )
    pids = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        # netstat -ano columns: Proto, Local, Foreign, State, PID
        if len(parts) >= 5 and "LISTENING" in line and f":{port}" in parts[1]:
            pids.add(parts[4])
    for pid in pids:
        subprocess.run(
            ["taskkill", "/F", "/PID", pid, "/T"],
            capture_output=True,
        )


# Sleep so the HTTP response that triggered shutdown gets to flush
# back to the browser before any uvicorn-killing happens.
time.sleep(1.0)

# ─── Web side first — finishes regardless of API-side cascade ──────
kill_matching(
    "node.exe",
    "pnpm\\.cjs|node_modules.{0,500}next|next-server",
)
kill_port(3000)
kill_matching("cmd.exe", "web\\.bat")

# ─── API side last — these may take us with them via parent kill ──
kill_matching("python.exe", "uvicorn.*diamond\\.api")
kill_matching("cmd.exe", "api\\.bat")
kill_port(8000)
"""


@router.post("/admin/shutdown")
def shutdown_app() -> dict[str, object]:
    """Kill the Next.js dev server (:3000) and this FastAPI process (:8000).

    Writes the kill script to a temp .py file and spawns it via
    ``cmd /c start /B`` so the resulting Python process is fully
    detached from the API's process tree. Without that detachment
    the kill subprocess gets terminated mid-execution when its
    grandparent cmd is killed — which leaves the web-side dev
    server still running.

    Returns immediately.
    """
    if platform.system() != "Windows":
        raise HTTPException(
            status_code=501,
            detail="Shutdown endpoint is Windows-only for now.",
        )

    # Write the kill script to a tempfile because passing it inline
    # to `python -c "..."` through `cmd /c start /B` runs into nested
    # quoting hell (the script contains both single and double quotes
    # plus PowerShell pipeline syntax). A file is robust.
    fd, script_path = tempfile.mkstemp(suffix=".py", prefix="diamond_shutdown_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(_KILL_SCRIPT)
    except Exception:
        os.unlink(script_path)
        raise

    # `cmd /c start /B "" python script.py` runs python in the
    # background, reparented off our process tree so that taskkill
    # /T from anywhere can't reach it. The empty-string second arg
    # to `start` is required when the next argument is a quoted
    # path (otherwise `start` interprets it as the window title).
    subprocess.Popen(
        f'cmd /c start /B "" "{sys.executable}" "{script_path}"',
        shell=True,
        # Detached + new process group + ignore stdio handles. These
        # are belt-and-suspenders on top of `start /B`.
        creationflags=(
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"status": "shutting_down", "ports": [3000, 8000]}
