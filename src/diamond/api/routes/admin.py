"""Admin endpoint — dev-only utilities for the local-first stack.

Exposes:
- ``POST /api/admin/shutdown``    — kill both dev servers
- ``GET  /api/admin/dump-status`` — list pending dumps (for the
                                    "Refresh" badge in the header)
- ``POST /api/admin/ingest``      — synchronously ingest any new
                                    dumps into the active save's
                                    warehouse, then rebuild L1+L2+L3.
                                    Blocks for the full ingest
                                    duration; the UI shows a spinner.

Why this is OK to ship without auth: Diamond is a single-user local-
first app per D16. CORS already restricts the API to
``localhost:3000``; nothing else can hit these endpoints. When the
Phase-4 web-share path opens we'll either gate them behind a config
flag or remove them entirely depending on the deploy story.

Concurrency story for ingest:

The API holds a single read-write DuckDB connection (the
``_root_con`` singleton in ``warehouse.py``). The ingest pipeline
also needs read-write access. Rather than juggle two RW connections
to the same file (DuckDB doesn't permit that), the ingest handler
runs on the SAME connection — under the warehouse module's
``_lock`` so concurrent requests block on cursor creation until
ingest completes. Acceptable for a single-user app: if you click
"Refresh" your other tabs pause for ~30s-3min, then unblock with
fresh data.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import duckdb
from fastapi import APIRouter, HTTPException

from diamond.api.schemas import DumpStatusResponse, IngestRunResponse
from diamond.api.warehouse import (
    _lock as _warehouse_lock,
    get_active_save,
)
from diamond.schema.build import (
    already_ingested,
    build_warehouse,
    open_warehouse_db,
)

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


@router.get("/admin/metabase-status")
def metabase_status() -> dict[str, object]:
    """Liveness + config probe for Metabase. Frontend uses this for
    the Workshop tab's status check (avoids cross-origin fetch quirks
    on localhost).

    Returns:
        {
          "running": bool,             # is Metabase reachable on the configured URL
          "configured": bool,          # do we have credentials cached for save-switch sync
          "active_save_db": str|None,  # what file Metabase Database 1 currently points at
          "message": str,
        }

    Best-effort + non-blocking — completes in ≤5s even when Metabase
    is down or auth fails.
    """
    from diamond.api.metabase import (
        METABASE_URL,
        METABASE_DATABASE_ID,
        _get_session,
        _is_metabase_reachable,
    )
    import httpx

    out: dict[str, object] = {
        "running": False,
        "configured": False,
        "active_save_db": None,
        "message": "",
    }

    if not _is_metabase_reachable():
        out["message"] = f"Metabase not running at {METABASE_URL}"
        return out
    out["running"] = True

    session = _get_session()
    if session is None:
        out["message"] = (
            "Metabase running but credentials missing or invalid; "
            "create ~/.diamond/metabase_credentials.toml to enable "
            "save-aware sync"
        )
        return out
    out["configured"] = True

    try:
        resp = httpx.get(
            f"{METABASE_URL}/api/database/{METABASE_DATABASE_ID}",
            headers={"X-Metabase-Session": session},
            timeout=5.0,
        )
        if resp.status_code == 200:
            db = resp.json()
            out["active_save_db"] = db.get("details", {}).get("database_file")
            out["message"] = f"Metabase synced to '{db.get('name')}'"
    except httpx.HTTPError as exc:
        out["message"] = f"Metabase metadata read error: {exc}"

    return out


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


# ─────────────────────────────────────────────────────────────────────────────
# Ingest status + on-demand refresh
# ─────────────────────────────────────────────────────────────────────────────


def _list_dumps_on_disk(save) -> list[str]:
    """Sort dump_* folder names alphabetically (= chronologically).

    OOTP names dumps `dump_YYYY_MM`, so lexical order matches
    chronological order.
    """
    if not save.dump_dir.exists():
        return []
    return sorted(
        p.name for p in save.dump_dir.iterdir()
        if p.is_dir() and p.name.startswith("dump_")
    )


@router.get("/admin/dump-status", response_model=DumpStatusResponse)
def get_dump_status() -> DumpStatusResponse:
    """Read-only snapshot of ingest gap.

    Compares dump folders on disk against `_diamond_ingests` rows.
    Returns counts + the list of pending dumps (truncated for the UI
    badge tooltip). Lock-free: opens a temporary read-only connection
    so it's safe to call while ingest is running.
    """
    save = get_active_save()
    on_disk = _list_dumps_on_disk(save)

    db_path = save.save_dir / "diamond" / "diamond.duckdb"
    if not db_path.exists():
        # Fresh save with no warehouse — every dump is pending.
        return DumpStatusResponse(
            save_name=save.save_name,
            has_warehouse=False,
            on_disk_count=len(on_disk),
            ingested_count=0,
            pending_count=len(on_disk),
            pending_dumps=on_disk[:20],
            latest_ingested_dump=None,
            latest_ingested_at=None,
        )

    # Read-only connection — doesn't conflict with the API's RW _root_con
    # because DuckDB allows multiple readers of the same file (or a writer
    # + readers, but we open this one read-only explicitly).
    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except duckdb.Error:
        # Defensive: if read_only=True somehow fails (rare on Windows
        # when the file is locked), fall back to "everything pending"
        # so the UI surfaces the issue rather than silently lying.
        return DumpStatusResponse(
            save_name=save.save_name,
            has_warehouse=True,
            on_disk_count=len(on_disk),
            ingested_count=0,
            pending_count=len(on_disk),
            pending_dumps=on_disk[:20],
            latest_ingested_dump=None,
            latest_ingested_at=None,
        )

    try:
        # Initialize the table existence check — we're read-only so we
        # can't create it; if it doesn't exist, treat as zero ingested.
        try:
            ingested_rows = con.execute(
                "SELECT dump_name, ingest_ts FROM _diamond_ingests "
                "WHERE status = 'success' ORDER BY ingest_ts DESC"
            ).fetchall()
        except duckdb.Error:
            ingested_rows = []

        ingested_set = {r[0] for r in ingested_rows}
        pending = [d for d in on_disk if d not in ingested_set]

        latest_dump = ingested_rows[0][0] if ingested_rows else None
        latest_at = (
            ingested_rows[0][1].isoformat()
            if ingested_rows and isinstance(ingested_rows[0][1], datetime)
            else None
        )

        return DumpStatusResponse(
            save_name=save.save_name,
            has_warehouse=True,
            on_disk_count=len(on_disk),
            ingested_count=len(ingested_set),
            pending_count=len(pending),
            pending_dumps=pending[:20],
            latest_ingested_dump=latest_dump,
            latest_ingested_at=latest_at,
        )
    finally:
        con.close()


@router.post("/admin/ingest", response_model=IngestRunResponse)
def trigger_ingest() -> IngestRunResponse:
    """Synchronously ingest any new dumps + rebuild L1+L2+L3.

    Holds the warehouse module's `_lock` for the entire operation,
    blocking concurrent cursor creation. New requests during ingest
    queue at the lock and unblock when ingest completes.

    Long-running: ~2-3s when nothing's new (no-op fast path), 30s+
    per pending dump on a real ingest. The frontend should show a
    spinner and bump its HTTP timeout to several minutes.
    """
    save = get_active_save()

    # Guard: don't try to ingest if the dump directory doesn't exist
    # (fresh-cloned save without OOTP exports yet).
    if not save.dump_dir.exists():
        raise HTTPException(
            status_code=409,
            detail=(
                f"No dump directory at {save.dump_dir}. "
                f"Run OOTP's CSV-export to populate it first."
            ),
        )

    # Acquire the warehouse module's singleton lock for the duration
    # of ingest. While held: any request that hits get_cursor() ->
    # _ensure_root() will block on _ensure_root's same-name lock,
    # then proceed once we release. We also force the singleton's
    # _root_con to None so ingest opens its own fresh connection
    # (avoids any shared-cursor weirdness during the rebuild).
    from diamond.api import warehouse as wh_module

    started = time.monotonic()
    with _warehouse_lock:
        # Close + null the API's existing connection if any. The next
        # request will lazy-open a fresh one after we release the lock.
        if wh_module._root_con is not None:
            wh_module._root_con.close()
            wh_module._root_con = None

        # Open a fresh RW connection just for the ingest run.
        ingest_con = open_warehouse_db(save)
        try:
            result = build_warehouse(
                ingest_con,
                save,
                dumps=None,        # auto-detect: every dump folder
                force=False,       # skip already-ingested
                rebuild=True,      # always rebuild L1+L2+L3
                verbose=False,     # spammy in API logs; CLI users get rich output
                quiet_per_dump=True,
            )
        finally:
            ingest_con.close()
        # _root_con stays None — next request opens fresh.

    elapsed = time.monotonic() - started
    return IngestRunResponse(
        save_name=save.save_name,
        ingested=list(result.get("ingested", [])),
        skipped=list(result.get("skipped", [])),
        elapsed_seconds=round(elapsed, 2),
    )
