"""Admin endpoint — dev-only utilities for the local-first stack.

Exposes:
- ``GET  /api/admin/dump-status`` — list pending dumps (for the
                                    "Refresh" badge in the header)
- ``POST /api/admin/ingest``      — synchronously ingest any new
                                    dumps into the active save's
                                    warehouse, then rebuild L1+L2+L3.
                                    Blocks for the full ingest
                                    duration; the UI shows a spinner.
- ``GET  /api/admin/metabase-status`` — Metabase reachability + Pattern
                                    A active-save info (D31).

History: ``POST /api/admin/shutdown`` was removed in D34 (2026-05-16)
along with the redundant header Quit button. Shutdown is now handled
by the desktop shell's window-X / tray-Quit + Job Object lifecycle
(D32); the dev path uses Ctrl+C in each cmd window.

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

import time
from datetime import datetime
from pathlib import Path

from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from diamond.api.schemas import DumpStatusResponse, IngestRunResponse
from diamond.api.warehouse import (
    _lock as _warehouse_lock,
    get_active_save,
    get_cursor,
)
from diamond.schema.build import (
    already_ingested,
    build_warehouse,
    open_warehouse_db,
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Metabase liveness probe (D31)
# ─────────────────────────────────────────────────────────────────────────────


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

    Best-effort + non-blocking — completes in <=5s even when Metabase
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
def get_dump_status(
    con: Annotated[duckdb.DuckDBPyConnection, Depends(get_cursor)],
) -> DumpStatusResponse:
    """Read-only snapshot of ingest gap.

    Compares dump folders on disk against `_diamond_ingests` rows.
    Returns counts + the list of pending dumps (truncated for the UI
    badge tooltip).

    Uses the shared API cursor (`get_cursor`) rather than opening its
    own connection — DuckDB on Windows holds an exclusive file lock
    when uvicorn has the warehouse open RW, so a second
    `duckdb.connect(read_only=True)` from the same process raises
    IOException and the endpoint silently returned "everything
    pending" (badge would falsely show all dumps unprocessed). The
    fast-but-quiet failure is documented in `docs/DECISIONS.md`.
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

    # Probe table existence first — if the warehouse exists but
    # `_diamond_ingests` doesn't (very-old warehouse or one that errored
    # mid-build), treat as zero ingested rather than 500.
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
